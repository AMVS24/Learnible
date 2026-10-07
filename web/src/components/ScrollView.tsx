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

// Zoom like a browser PDF viewer: scale 1 = the page at its printed size
// (PDF points at 96 dpi), shown as a percentage; one column, centred, and
// wider-than-the-window pages scroll sideways. "fit" (the default) tracks the
// window width. Ctrl/Cmd + scroll, touchpad pinch, Ctrl +/-/0 and the small
// control all zoom. Remembered per browser.
type Zoom = "fit" | number;
const SCALE_MIN = 0.25, SCALE_MAX = 5, STEP = 1.1;
const PT_TO_PX = 96 / 72;
const PAD = 16;   // horizontal padding around the column
const GAP = 16;   // space between pages
const ZOOM_KEY = "learnible.pdfZoom"; // new key: earlier builds stored a different scale
const clampScale = (z: number) => Math.min(SCALE_MAX, Math.max(SCALE_MIN, z));

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
  insetTop = 0,
  insetBottom = 0,
}: {
  base: string;
  pages: Record<number, PageInfo>;
  chunks: Chunk[];
  active: Chunk | null;     // the chunk at the current time (also during the gap after it)
  highlight: Chunk | null;  // the chunk being spoken right now (green box)
  recenterKey: number;      // bumped by explicit navigation: follow again
  onPick: (c: Chunk) => void;
  // Height of the translucent header / player overlaid on the view: the first
  // and last page clear them, the controls sit below the header.
  insetTop?: number;
  insetBottom?: number;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<number, HTMLElement>());
  const [follow, setFollow] = useState(true);
  const [where, setWhere] = useState<Where>("visible");
  // Available width for the column, and the zoom (null until restored).
  const [innerW, setInnerW] = useState(0);
  const [zoom, setZoomState] = useState<Zoom | null>(null);
  // Point to keep fixed across a zoom (content px + its viewport position),
  // applied right after the re-layout.
  const anchor = useRef<{ x: number; y: number; vx: number; vy: number; ratio: number } | null>(null);
  // So long-lived listeners (wheel, keys) always zoom from the current scale.
  const zoomRef = useRef<((factor: number | "fit", vx?: number, vy?: number) => void) | null>(null);

  const setZoom = useCallback((z: Zoom) => {
    const v = z === "fit" ? z : clampScale(z);
    setZoomState(v);
    try { localStorage.setItem(ZOOM_KEY, String(v)); } catch { /* not remembered */ }
  }, []);

  useLayoutEffect(() => {
    const sc = scroller.current;
    if (!sc) return;
    const ro = new ResizeObserver(() => setInnerW(Math.max(1, sc.clientWidth - 2 * PAD)));
    ro.observe(sc);
    setInnerW(Math.max(1, sc.clientWidth - 2 * PAD));
    let saved: Zoom = "fit";
    try {
      const raw = localStorage.getItem(ZOOM_KEY);
      if (raw && raw !== "fit" && Number(raw)) saved = clampScale(Number(raw));
    } catch { /* none */ }
    setZoomState(saved);
    return () => ro.disconnect();
  }, []);

  const widestPt = Math.max(...Object.values(pages).map((i) => i.width));
  const fitScale = innerW ? innerW / (widestPt * PT_TO_PX) : 1;
  const scale = zoom == null ? null : zoom === "fit" ? fitScale : zoom;

  // Zoom to `next`, keeping a viewport point (default: the centre) fixed.
  const zoomTo = useCallback((next: Zoom, vx?: number, vy?: number) => {
    const sc = scroller.current;
    if (!sc || scale == null) return;
    const target = next === "fit" ? fitScale : clampScale(next);
    const px = vx ?? sc.clientWidth / 2, py = vy ?? sc.clientHeight / 2;
    anchor.current = { x: sc.scrollLeft + px, y: sc.scrollTop + py, vx: px, vy: py, ratio: target / scale };
    setZoom(next === "fit" ? "fit" : target);
  }, [scale, fitScale, setZoom]);

  useLayoutEffect(() => {
    const sc = scroller.current, a = anchor.current;
    if (!sc || !a) return;
    anchor.current = null;
    sc.scrollLeft = a.x * a.ratio - a.vx;
    sc.scrollTop = a.y * a.ratio - a.vy;
  }, [scale]);

  useEffect(() => {
    zoomRef.current = (f, vx, vy) => {
      if (scale == null) return;
      zoomTo(f === "fit" ? "fit" : scale * f, vx, vy);
    };
  }, [scale, zoomTo]);

  // Ctrl/Cmd + "+", "-", "0" zoom the document, not the whole site.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomRef.current?.(STEP); }
      else if (e.key === "-") { e.preventDefault(); zoomRef.current?.(1 / STEP); }
      else if (e.key === "0") { e.preventDefault(); zoomRef.current?.("fit"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
        // Continuous: small pinch deltas give small steps, a mouse notch ~10%.
        const d = Math.max(-120, Math.min(120, e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY));
        zoomRef.current?.(Math.exp(-d * 0.0015), e.clientX - r.left, e.clientY - r.top);
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

  // After a zoom, keep following the narration if we were.
  useEffect(() => {
    if (follow) bringIntoView(false);
    measure();
  }, [scale]); // eslint-disable-line react-hooks/exhaustive-deps

  // One whole page in view (between the bars).
  const fitPage = () => {
    const sc = scroller.current;
    const first = pages[Object.keys(pages).map(Number).sort((a, b) => a - b)[0]];
    if (!sc || !first) return;
    zoomTo((sc.clientHeight - insetTop - insetBottom - 2 * GAP) / (first.height * PT_TO_PX));
  };

  const backToCurrent = () => {
    setFollow(true);
    const el = active ? boxes.current.get(active.index) : null;
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  };

  return (
    <div className="relative h-full">
      <div ref={scroller} tabIndex={0} className="h-full overflow-auto bg-neutral-900 outline-none">
        {/* One centred column; it grows to the page width when zoomed past
            the window, so the overflow scrolls sideways. */}
        <div
          className="flex min-w-full flex-col items-center"
          style={{
            gap: GAP,
            width: "max-content",
            paddingInline: PAD,
            paddingTop: insetTop + GAP,
            paddingBottom: insetBottom + GAP,
          }}
        >
          {pageNums.map((p) => {
            const info = pages[p];
            return (
              <div key={p} className="relative shrink-0" style={{ width: scale ? info.width * PT_TO_PX * scale : "100%" }}>
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

      {/* Zoom control (Ctrl + scroll, pinch and Ctrl +/-/0 work too). */}
      <div
        className="absolute right-4 flex items-center gap-0.5 rounded-full border border-white/10 bg-neutral-950/70 p-1 text-xs text-neutral-300 shadow-lg shadow-black/40 backdrop-blur-md"
        style={{ top: insetTop + 10 }}
      >
        <button
          onClick={() => zoomRef.current?.(1 / STEP)}
          aria-label="Zoom out"
          title="Zoom out (Ctrl + scroll / Ctrl −)"
          className="flex h-7 w-7 touch-manipulation items-center justify-center rounded-full text-base hover:bg-neutral-800"
        >
          −
        </button>
        <button
          onClick={() => zoomRef.current?.("fit")}
          title={zoom === "fit" ? "Fitting the width" : "Fit width (Ctrl 0)"}
          className={`w-12 rounded-full py-1 text-center tabular-nums hover:bg-neutral-800 ${zoom === "fit" ? "text-emerald-300" : ""}`}
        >
          {scale ? `${Math.round(scale * 100)}%` : ""}
        </button>
        <button
          onClick={() => zoomRef.current?.(STEP)}
          aria-label="Zoom in"
          title="Zoom in (Ctrl + scroll / Ctrl +)"
          className="flex h-7 w-7 touch-manipulation items-center justify-center rounded-full text-base hover:bg-neutral-800"
        >
          +
        </button>
        <span className="mx-0.5 h-4 w-px bg-neutral-700" />
        <button onClick={fitPage} title="Whole page in view" className="touch-manipulation rounded-full px-2 py-1 hover:bg-neutral-800">
          Page
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
