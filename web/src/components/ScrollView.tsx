"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Chunk, PageInfo } from "@/lib/types";

// Scroll mode: every page of the unit stacked top to bottom, like a PDF in a
// browser. Every chunk is a click target ("read from here"); the chunk being
// read keeps the green highlight. The view follows the narration until the
// reader scrolls on their own; then a side button points back (up or down) to
// the passage being read, and clicking it -- or any explicit navigation
// (skip / scrub / clicking a chunk) -- turns following back on.

type Where = "visible" | "above" | "below";

// Zoom = page width as a fraction of the available width ("fit width" = 1).
// Below ~0.5 pages sit side by side in rows; above 1 the view scrolls
// sideways. Remembered per browser.
const ZOOM_MIN = 0.15, ZOOM_MAX = 3, ZOOM_STEP = 1.2;
const PAD = 16;   // horizontal padding of the page column
const GAP = 20;   // space between pages
const ZOOM_KEY = "learnible.scrollZoom";
const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

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
  // Available width for pages, and the zoom (null until measured / restored).
  const [innerW, setInnerW] = useState(0);
  const [zoom, setZoomState] = useState<number | null>(null);
  // Point to keep fixed across a zoom (content px + its position in the
  // viewport), applied after the re-layout.
  const anchor = useRef<{ x: number; y: number; vx: number; vy: number; ratio: number } | null>(null);
  // A ref so the long-lived wheel listener always sees the current zoom.
  const zoomRef = useRef<((factor: number, vx: number, vy: number) => void) | null>(null);

  const setZoom = useCallback((z: number) => {
    const v = clampZoom(z);
    setZoomState(v);
    try { localStorage.setItem(ZOOM_KEY, String(v)); } catch { /* not remembered */ }
  }, []);

  // Track the available width; first time, restore the saved zoom or start
  // at the old comfortable reading width (~860 px, at most fit-width).
  useLayoutEffect(() => {
    const sc = scroller.current;
    if (!sc) return;
    const ro = new ResizeObserver(() => setInnerW(Math.max(1, sc.clientWidth - 2 * PAD)));
    ro.observe(sc);
    const w = Math.max(1, sc.clientWidth - 2 * PAD);
    setInnerW(w);
    let saved: number | null = null;
    try { saved = Number(localStorage.getItem(ZOOM_KEY)) || null; } catch { /* none */ }
    setZoomState(clampZoom(saved ?? Math.min(1, 860 / w)));
    return () => ro.disconnect();
  }, []);

  const pageW = innerW && zoom ? Math.round(innerW * zoom) : null;

  // Zoom keeping a given viewport point (default: the centre) fixed.
  const zoomAround = useCallback((next: number, vx?: number, vy?: number) => {
    const sc = scroller.current;
    if (!sc || !zoom) return;
    const z = clampZoom(next);
    const px = vx ?? sc.clientWidth / 2, py = vy ?? sc.clientHeight / 2;
    anchor.current = { x: sc.scrollLeft + px, y: sc.scrollTop + py, vx: px, vy: py, ratio: z / zoom };
    setZoom(z);
  }, [zoom, setZoom]);

  useLayoutEffect(() => {
    const sc = scroller.current, a = anchor.current;
    if (!sc || !a) return;
    anchor.current = null;
    sc.scrollLeft = a.x * a.ratio - a.vx;
    sc.scrollTop = a.y * a.ratio - a.vy;
  }, [zoom]);

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
    // Ctrl/Cmd + wheel (a touchpad pinch arrives as this too) zooms around
    // the cursor instead of scrolling; a plain wheel scrolls (and stops
    // following).
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const r = sc.getBoundingClientRect();
        zoomRef.current?.(Math.exp(-e.deltaY * 0.0025), e.clientX - r.left, e.clientY - r.top);
        return;
      }
      stop();
    };
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
    sc.addEventListener("wheel", onWheel, { passive: false });
    sc.addEventListener("touchmove", stop, { passive: true });
    sc.addEventListener("keydown", onKey);
    sc.addEventListener("pointerdown", onPointer);
    sc.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      sc.removeEventListener("wheel", onWheel);
      sc.removeEventListener("touchmove", stop);
      sc.removeEventListener("keydown", onKey);
      sc.removeEventListener("pointerdown", onPointer);
      sc.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [measure]);

  // Keep the wheel listener's zoom handler current.
  useEffect(() => {
    zoomRef.current = (factor, vx, vy) => { if (zoom) zoomAround(zoom * factor, vx, vy); };
  }, [zoom, zoomAround]);

  // After a zoom, keep following the narration if we were.
  useEffect(() => {
    if (follow) bringIntoView(false);
    measure();
  }, [pageW]); // eslint-disable-line react-hooks/exhaustive-deps

  // One whole page in view.
  const fitPage = () => {
    const sc = scroller.current;
    const first = pages[Object.keys(pages).map(Number).sort((a, b) => a - b)[0]];
    if (!sc || !first || !innerW) return;
    zoomAround(((sc.clientHeight - 48) * (first.width / first.height)) / innerW);
  };

  const backToCurrent = () => {
    setFollow(true);
    const el = active ? boxes.current.get(active.index) : null;
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  };

  return (
    <div className="relative h-full">
      <div ref={scroller} tabIndex={0} className="h-full overflow-auto bg-neutral-900 outline-none">
        {/* "safe center": centred, but when zoomed past fit-width the
            overflow stays scrollable on both sides. */}
        <div
          className="flex min-w-full flex-wrap py-6"
          style={{
            gap: GAP,
            paddingInline: PAD,
            justifyContent: "safe center",
            width: pageW && pageW > innerW ? pageW + 2 * PAD : undefined,
          }}
        >
          {pageNums.map((p) => {
            const info = pages[p];
            return (
              <div key={p} className="relative shrink-0" style={{ width: pageW ?? "min(100%, 860px)" }}>
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

      {/* Zoom: buttons, fit width / fit page; Ctrl + scroll or pinch also works. */}
      <div className="absolute right-4 top-3 flex items-center gap-0.5 rounded-full border border-white/10 bg-neutral-950/85 p-1 text-xs text-neutral-300 shadow-lg shadow-black/40 backdrop-blur">
        <button
          onClick={() => zoom && zoomAround(zoom / ZOOM_STEP)}
          aria-label="Zoom out"
          title="Zoom out (Ctrl + scroll)"
          className="flex h-7 w-7 touch-manipulation items-center justify-center rounded-full text-base hover:bg-neutral-800"
        >
          −
        </button>
        <span className="w-11 text-center tabular-nums" title="Page width as a share of the available width">
          {zoom ? `${Math.round(zoom * 100)}%` : ""}
        </span>
        <button
          onClick={() => zoom && zoomAround(zoom * ZOOM_STEP)}
          aria-label="Zoom in"
          title="Zoom in (Ctrl + scroll)"
          className="flex h-7 w-7 touch-manipulation items-center justify-center rounded-full text-base hover:bg-neutral-800"
        >
          +
        </button>
        <span className="mx-1 h-4 w-px bg-neutral-700" />
        <button onClick={() => zoomAround(1)} className="touch-manipulation rounded-full px-2 py-1 hover:bg-neutral-800">
          Fit width
        </button>
        <button onClick={fitPage} className="touch-manipulation rounded-full px-2 py-1 hover:bg-neutral-800">
          Fit page
        </button>
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
