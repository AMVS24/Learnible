"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Chunk, FigureEntry, Manifest } from "@/lib/types";
import PageView from "./PageView";
import OnTheGoView from "./OnTheGoView";
import PlayerBar from "./PlayerBar";

// Latest chunk with t0 <= t (binary search -- chunks are in t0 order because
// build_manifest lays them out sequentially). Ported from the recovered
// original app's `segAt`.
function chunkAt(chunks: Chunk[], t: number): Chunk | null {
  let lo = 0, hi = chunks.length - 1, ans: Chunk | null = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (chunks[mid].t0 <= t) { ans = chunks[mid]; lo = mid + 1; }
    else hi = mid - 1;
  }
  return ans;
}

export default function Reader({
  manifest,
  base,
  title,
}: {
  manifest: Manifest;
  base: string; // chapter data dir, e.g. "/data/ostep/ch16"
  title: string;
}) {
  const { chunks, figures, pages } = manifest;

  const narratedPages = useMemo(
    () => [...new Set(chunks.map((c) => c.page))].sort((a, b) => a - b),
    [chunks]
  );
  const figureByLabel = useMemo(() => {
    const m = new Map<string, FigureEntry>();
    for (const f of figures) if (f.label) m.set(f.label, f);
    return m;
  }, [figures]);

  const [mode, setMode] = useState<"reading" | "onTheGo">("reading");
  const [currentTime, setCurrentTime] = useState(0);
  const [displayPage, setDisplayPage] = useState(narratedPages[0]);
  const audioRef = useRef<HTMLAudioElement>(null);

  const active = useMemo(() => chunkAt(chunks, currentTime), [chunks, currentTime]);

  // Ported from the original app's onTime(): the highlight box only shows
  // while a chunk is actually being read (not during the inter-chunk pause),
  // but the active-figure set persists through the pause (see
  // Chunk.active_figures in tts/synth_local.py's build_manifest).
  const inChunk = !!active && currentTime <= active.t1 + 0.05;
  const highlightChunk = inChunk ? active : null;
  const activeFigures = (active?.active_figures ?? [])
    .map((l) => figureByLabel.get(l))
    .filter((f): f is FigureEntry => !!f);

  // Page images download on demand, so a page turn used to wait on the
  // network. Warm the browser cache: the pages either side of the current
  // one right away, then every other page of the unit once the browser is
  // idle (a unit is ~5-15 pages of ~50-120 KB WebP).
  useEffect(() => {
    const warm = (p: number) => {
      const info = pages[p];
      if (info) new Image().src = `${base}/pages/${info.image}`;
    };
    const i = narratedPages.indexOf(displayPage);
    for (const d of [1, -1, 2]) if (narratedPages[i + d] != null) warm(narratedPages[i + d]);
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 1500));
    const cancel = window.cancelIdleCallback ?? window.clearTimeout;
    const id = idle(() => narratedPages.forEach(warm));
    return () => cancel(id);
  }, [base, pages, narratedPages, displayPage]);

  const handleTimeUpdate = (t: number) => {
    setCurrentTime(t);
    const c = chunkAt(chunks, t);
    if (c && c.page !== displayPage) setDisplayPage(c.page);
  };

  // Jump to the next/previous page that actually has narrated content, not
  // just displayPage +/- 1 -- a page with no chunks (pure figure/table) is
  // skipped over, matching the original app's `skipPage`.
  const skipPage = (dir: 1 | -1) => {
    const idx = narratedPages.indexOf(displayPage);
    const target = idx === -1
      ? narratedPages.find((p) => (dir > 0 ? p > displayPage : p < displayPage))
      : narratedPages[idx + dir];
    if (target == null) return;
    const first = chunks.find((c) => c.page === target);
    if (first && audioRef.current) {
      audioRef.current.currentTime = first.t0;
      handleTimeUpdate(first.t0);
    }
  };

  // Restart the current chunk if we're >2s into it; otherwise go to the
  // previous one. Matches the original app's `skipChunk`.
  const skipChunk = (dir: 1 | -1) => {
    if (!audioRef.current) return;
    const t = audioRef.current.currentTime;
    let i = -1;
    for (let k = 0; k < chunks.length; k++) {
      if (chunks[k].t0 <= t + 0.01) i = k; else break;
    }
    let target: number | null = null;
    if (dir > 0) {
      if (i + 1 < chunks.length) target = chunks[i + 1].t0;
    } else {
      const cur = chunks[i];
      if (cur && t - cur.t0 > 2) target = cur.t0;
      else if (i > 0) target = chunks[i - 1].t0;
      else if (cur) target = cur.t0;
    }
    if (target != null) {
      audioRef.current.currentTime = target;
      handleTimeUpdate(target);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between gap-3 border-b border-neutral-800 px-4 py-3">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-medium text-neutral-300">{title}</h1>
          {/* Chapter-relative page (what's printed on the page) plus the
              PDF page -- they differ: OSTEP restarts numbering per chapter. */}
          <p className="text-xs text-neutral-500">
            Page {manifest.source.page_offset != null
              ? displayPage - manifest.source.page_offset
              : displayPage - (manifest.source.chapter_start ?? manifest.source.page_start) + 1}{" "}
            &middot; PDF p.{displayPage} &middot;{" "}
            {narratedPages.indexOf(displayPage) + 1} / {narratedPages.length}
          </p>
        </div>
        <div className="flex gap-1 rounded-lg bg-neutral-900 p-1">
          <button
            onClick={() => setMode("reading")}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              mode === "reading" ? "bg-neutral-700 text-white" : "text-neutral-400 hover:text-neutral-200"
            }`}
          >
            Reading
          </button>
          <button
            onClick={() => setMode("onTheGo")}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              mode === "onTheGo" ? "bg-neutral-700 text-white" : "text-neutral-400 hover:text-neutral-200"
            }`}
          >
            On the go
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        {mode === "reading" ? (
          <PageView base={base} pageInfo={pages[displayPage]} chunk={highlightChunk} />
        ) : (
          <OnTheGoView base={base} figures={activeFigures} pages={pages} page={displayPage} />
        )}
      </main>

      <PlayerBar
        audioRef={audioRef}
        audioSrc={`${base}/${manifest.audio}`}
        onTimeUpdate={handleTimeUpdate}
        onPrevPage={() => skipPage(-1)}
        onNextPage={() => skipPage(1)}
        onPrevChunk={() => skipChunk(-1)}
        onNextChunk={() => skipChunk(1)}
      />
    </div>
  );
}
