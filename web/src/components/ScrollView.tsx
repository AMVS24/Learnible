"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Chunk, PageInfo } from "@/lib/types";

// Scroll mode: every page of the unit stacked top to bottom, like a PDF in a
// browser. Every chunk is a click target ("read from here"); the chunk being
// read keeps the green highlight. The view follows the narration until the
// reader scrolls on their own; then a side button points back (up or down) to
// the passage being read, and clicking it -- or any explicit navigation
// (skip / scrub / clicking a chunk) -- turns following back on.

type Where = "visible" | "above" | "below";

const ArrowIcon = ({ up }: { up: boolean }) => (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={up ? "" : "rotate-180"}>
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
);

export default function ScrollView({
  base,
  pages,
  chunks,
  active,
  highlight,
  recenterKey,
  onPick,
}: {
  base: string;
  pages: Record<number, PageInfo>;
  chunks: Chunk[];
  active: Chunk | null;     // the chunk at the current time (also during the gap after it)
  highlight: Chunk | null;  // the chunk being spoken right now (green box)
  recenterKey: number;      // bumped by explicit navigation: follow again
  onPick: (c: Chunk) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<number, HTMLElement>());
  const [follow, setFollow] = useState(true);
  const [where, setWhere] = useState<Where>("visible");

  const pageNums = Object.keys(pages).map(Number).sort((a, b) => a - b);
  const byPage = new Map<number, Chunk[]>();
  for (const c of chunks) byPage.set(c.page, [...(byPage.get(c.page) ?? []), c]);

  // Where the active chunk is relative to the viewport.
  const measure = useCallback(() => {
    const el = active ? boxes.current.get(active.index) : null;
    const sc = scroller.current;
    if (!el || !sc) return;
    const r = el.getBoundingClientRect(), v = sc.getBoundingClientRect();
    setWhere(r.bottom < v.top + 8 ? "above" : r.top > v.bottom - 8 ? "below" : "visible");
  }, [active]);

  const bringIntoView = useCallback((smooth = true) => {
    const el = active ? boxes.current.get(active.index) : null;
    const sc = scroller.current;
    if (!el || !sc) return;
    // Only move when the passage is outside the middle band of the view, so
    // following the narration doesn't jitter on every chunk.
    const r = el.getBoundingClientRect(), v = sc.getBoundingClientRect();
    const band = v.height * 0.18;
    if (r.top >= v.top + band && r.bottom <= v.bottom - band) return;
    el.scrollIntoView({ block: "center", behavior: smooth ? "smooth" : "auto" });
  }, [active]);

  // Follow the narration.
  useEffect(() => {
    if (follow) bringIntoView();
    measure();
  }, [follow, bringIntoView, measure]);

  // Explicit navigation (skip, scrub, chunk click) re-enables following.
  useEffect(() => {
    if (recenterKey === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a navigation request, not derived state
    setFollow(true);
    bringIntoView();
  }, [recenterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // The reader scrolling on their own stops following. Only real input
  // counts (wheel, touch, scroll keys, dragging the scrollbar) -- not the
  // smooth scrolls this component starts itself.
  useEffect(() => {
    const sc = scroller.current;
    if (!sc) return;
    const stop = () => setFollow(false);
    const onKey = (e: KeyboardEvent) => {
      if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(e.key)) stop();
    };
    const onPointer = (e: PointerEvent) => {
      // A press on the scrollbar itself (outside the content box).
      if (e.target === sc && e.offsetX > sc.clientWidth) stop();
    };
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(measure);
    };
    sc.addEventListener("wheel", stop, { passive: true });
    sc.addEventListener("touchmove", stop, { passive: true });
    sc.addEventListener("keydown", onKey);
    sc.addEventListener("pointerdown", onPointer);
    sc.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      sc.removeEventListener("wheel", stop);
      sc.removeEventListener("touchmove", stop);
      sc.removeEventListener("keydown", onKey);
      sc.removeEventListener("pointerdown", onPointer);
      sc.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [measure]);

  const backToCurrent = () => {
    setFollow(true);
    const el = active ? boxes.current.get(active.index) : null;
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  };

  return (
    <div className="relative h-full">
      <div ref={scroller} tabIndex={0} className="h-full overflow-y-auto bg-neutral-900 outline-none">
        <div className="mx-auto flex max-w-[860px] flex-col gap-5 px-3 py-6 sm:px-6">
          {pageNums.map((p) => {
            const info = pages[p];
            return (
              <div key={p} className="relative">
                <div
                  className="relative w-full overflow-hidden rounded-sm bg-neutral-800 shadow-2xl"
                  style={{ aspectRatio: `${info.width} / ${info.height}` }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- pipeline-generated, not a static build asset */}
                  <img
                    src={`${base}/pages/${info.image}`}
                    alt={`PDF page ${p}`}
                    loading="lazy"
                    decoding="async"
                    className="absolute inset-0 h-full w-full"
                  />
                  {(byPage.get(p) ?? []).map((c) => {
                    const lit = highlight?.index === c.index;
                    return (
                      <button
                        key={c.index}
                        ref={(el) => { if (el) boxes.current.set(c.index, el); else boxes.current.delete(c.index); }}
                        onClick={() => { setFollow(true); onPick(c); }}
                        title="Read from here"
                        aria-label={`Read from here: ${c.text.slice(0, 80)}`}
                        className={`absolute cursor-pointer rounded-sm transition-colors duration-200 ${
                          lit
                            ? "bg-emerald-400/25 ring-2 ring-emerald-400/70"
                            : "hover:bg-emerald-400/10 hover:ring-1 hover:ring-emerald-400/40 focus-visible:ring-1 focus-visible:ring-emerald-400/60"
                        }`}
                        style={{
                          left: `${(c.bbox[0] / info.width) * 100}%`,
                          top: `${(c.bbox[1] / info.height) * 100}%`,
                          width: `${((c.bbox[2] - c.bbox[0]) / info.width) * 100}%`,
                          height: `${((c.bbox[3] - c.bbox[1]) / info.height) * 100}%`,
                        }}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Back to the passage being read: only once the reader has scrolled
          away from it. */}
      <button
        onClick={backToCurrent}
        aria-label="Back to the passage being read"
        title="Back to the passage being read"
        className={`absolute right-4 top-1/2 flex -translate-y-1/2 touch-manipulation items-center gap-2 rounded-full bg-emerald-500 py-2.5 pl-3 pr-3.5 text-sm font-medium text-neutral-950 shadow-lg shadow-black/50 transition-all duration-200 hover:bg-emerald-400 active:scale-95 ${
          !follow && active && where !== "visible" ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-4 opacity-0"
        }`}
      >
        <ArrowIcon up={where !== "below"} />
        <span className="hidden sm:inline">Now reading</span>
      </button>
    </div>
  );
}
