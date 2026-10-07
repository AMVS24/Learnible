"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Chunk, FigureEntry, Manifest } from "@/lib/types";
import PageView from "./PageView";
import OnTheGoView from "./OnTheGoView";
import PlayerBar from "./PlayerBar";
import ScrubWheel from "./ScrubWheel";
import ScrollView from "./ScrollView";
import { progress, type ReaderMode } from "@/lib/progress";

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
  bookId,
  chapterId,
}: {
  manifest: Manifest;
  base: string; // chapter data dir, e.g. "/data/ostep/ch16"
  title: string;
  bookId: string;    // for remembering where you left off (lib/progress.ts)
  chapterId: string;
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

  // reading: one page at a time; scroll: all pages stacked, click a chunk
  // to read it; onTheGo: just the active figure.
  const [mode, setModeState] = useState<ReaderMode>("reading");
  const setMode = (m: ReaderMode) => { setModeState(m); progress.saveMode(m); };
  // Bumped by explicit navigation so scroll mode starts following again.
  const [recenterKey, setRecenterKey] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  // While the scrub wheel is open, the page/highlight follow its preview
  // position instead of the (paused) audio.
  const [previewTime, setPreviewTime] = useState<number | null>(null);
  const [displayPage, setDisplayPage] = useState(narratedPages[0]);
  const audioRef = useRef<HTMLAudioElement>(null);

  const shownTime = previewTime ?? currentTime;
  const active = useMemo(() => chunkAt(chunks, shownTime), [chunks, shownTime]);

  // Ported from the original app's onTime(): the highlight box only shows
  // while a chunk is actually being read (not during the inter-chunk pause),
  // but the active-figure set persists through the pause (see
  // Chunk.active_figures in tts/synth_local.py's build_manifest).
  const inChunk = !!active && shownTime <= active.t1 + 0.05;
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

  // --- where you left off ----------------------------------------------------
  // Saved (throttled) as you listen, and on pause / seek / leaving the page;
  // restored once on open -- cued, not auto-played. `restored` guards against
  // the audio's initial t=0 updates overwriting the saved spot before it's
  // been applied.
  const restored = useRef(false);
  const lastSave = useRef(0);
  const save = (t: number, force = false) => {
    if (!restored.current) return;
    const now = Date.now();
    if (!force && now - lastSave.current < 2000) return;
    lastSave.current = now;
    progress.save(bookId, chapterId, title, t);
  };

  const handleTimeUpdate = (t: number) => {
    setCurrentTime(t);
    const c = chunkAt(chunks, t);
    if (c && c.page !== displayPage) setDisplayPage(c.page);
    save(t);
  };

  useEffect(() => {
    const m = progress.mode();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a stored preference after hydration
    if (m) setModeState(m);
    const a = audioRef.current;
    const pos = progress.chapter(bookId, chapterId);
    if (!a || !pos || pos.t < 1) { restored.current = true; return; }
    const apply = () => {
      const t = Math.min(pos.t, (a.duration || pos.t) - 0.5);
      a.currentTime = t;
      setCurrentTime(t);
      const c = chunkAt(chunks, t);
      if (c) setDisplayPage(c.page);
      setRecenterKey((k) => k + 1);
      restored.current = true;
    };
    if (a.readyState >= 1) apply();
    else a.addEventListener("loadedmetadata", apply, { once: true });
    return () => a.removeEventListener("loadedmetadata", apply);
  }, [bookId, chapterId, chunks]);

  // Save immediately on pause / seek, and when leaving or hiding the page.
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const now = () => save(a.currentTime, true);
    const onHide = () => { if (document.visibilityState === "hidden") now(); };
    a.addEventListener("pause", now);
    a.addEventListener("seeked", now);
    window.addEventListener("pagehide", now);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      a.removeEventListener("pause", now);
      a.removeEventListener("seeked", now);
      window.removeEventListener("pagehide", now);
      document.removeEventListener("visibilitychange", onHide);
    };
  });

  // Seek somewhere on purpose (skip, scrub, click): scroll mode re-follows.
  const jumpTo = (t: number, play = false) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = t;
    handleTimeUpdate(t);
    setRecenterKey((k) => k + 1);
    if (play) void a.play();
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
    if (first) jumpTo(first.t0);
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
    if (target != null) jumpTo(target);
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
        <div className="flex shrink-0 gap-1 rounded-lg bg-neutral-900 p-1">
          {([["reading", "Reading"], ["scroll", "Scroll"], ["onTheGo", "On the go"]] as const).map(([m, label]) => (
            <button
              key={m}
              onClick={() => { setMode(m); if (m === "scroll") setRecenterKey((k) => k + 1); }}
              className={`rounded-md px-2.5 py-1.5 text-sm transition sm:px-3 ${
                mode === m ? "bg-neutral-700 text-white" : "text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        {mode === "reading" ? (
          <PageView base={base} pageInfo={pages[displayPage]} chunk={highlightChunk} />
        ) : mode === "scroll" ? (
          <ScrollView
            base={base}
            pages={pages}
            chunks={chunks}
            active={active}
            highlight={highlightChunk}
            recenterKey={recenterKey}
            onPick={(c) => jumpTo(c.t0, true)}
          />
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
        scrub={
          <ScrubWheel
            audioRef={audioRef}
            chunks={chunks}
            onPreview={(t) => {
              setPreviewTime(t);
              const c = t == null ? null : chunkAt(chunks, t);
              if (c && c.page !== displayPage) setDisplayPage(c.page);
            }}
            onCommit={(t) => jumpTo(t, true)}
          />
        }
      />
    </div>
  );
}
