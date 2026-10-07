"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { Chunk } from "@/lib/types";

// Press-and-hold audio scrubber, after the iPhone camera's zoom dial: hold
// the gizmo and a ruler pops up over the player; drag (finger / mouse) or
// two-finger-scroll (touchpad) to slide the tape under a fixed needle, and
// release to resume playback from there. A quick tap opens it "sticky" for
// touchpad scrolling; it commits after a short idle, Esc cancels.
//
// Tape semantics: content follows the finger. Dragging right pulls earlier
// audio under the needle (rewind); dragging left goes forward.

const PX_PER_SEC = 14;          // ruler scale
const SNAP_SEC = 0.35;          // snap to a chunk start within this distance
const DRAG_THRESHOLD_PX = 6;    // below this a press counts as a tap
const STICKY_IDLE_MS = 1100;    // sticky mode commits after this much quiet
const HAPTIC_EVERY_SEC = 5;

function fmt(t: number): string {
  const s = Math.max(0, Math.round(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function fmtOffset(d: number): string {
  const sign = d < -0.05 ? "−" : d > 0.05 ? "+" : "±";
  return `${sign}${fmt(Math.abs(d))}`;
}

const WheelIcon = () => (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
    <path d="M4 9v6M8 7.5v9M12 5v14M16 7.5v9M20 9v6" />
  </svg>
);

type Mode = "closed" | "held" | "sticky";

export default function ScrubWheel({
  audioRef,
  chunks,
  onPreview,
  onCommit,
}: {
  audioRef: RefObject<HTMLAudioElement | null>;
  chunks: Chunk[];
  onPreview: (t: number | null) => void; // drive the page/highlight while scrubbing
  onCommit: (t: number) => void;         // seek + resume
}) {
  const [mode, setMode] = useState<Mode>("closed");
  const [preview, setPreview] = useState(0);
  // Where scrubbing started and the track length, captured on open (render
  // must not read refs).
  const [origin, setOrigin] = useState({ base: 0, duration: 0 });
  const st = useRef({ startX: 0, startT: 0, base: 0, moved: false, wasPlaying: false, lastHaptic: 0 });
  const idleTimer = useRef<number | null>(null);
  const previewRef = useRef(0);

  const duration = useCallback(
    () => audioRef.current?.duration || chunks.at(-1)?.t1 || 0,
    [audioRef, chunks],
  );

  // Gentle magnet: the nearest passage start within SNAP_SEC, so "go back to
  // the start of what was just said" lands exactly.
  const snap = useCallback((t: number) => {
    let best = t, bestD = SNAP_SEC;
    for (const c of chunks) {
      const d = Math.abs(c.t0 - t);
      if (d < bestD) { best = c.t0; bestD = d; }
    }
    return best;
  }, [chunks]);

  const setT = useCallback((raw: number) => {
    const t = Math.min(Math.max(0, raw), duration());
    const shown = snap(t);
    previewRef.current = shown;
    setPreview(shown);
    onPreview(shown);
    const bucket = Math.floor(shown / HAPTIC_EVERY_SEC);
    if (bucket !== st.current.lastHaptic) {
      st.current.lastHaptic = bucket;
      navigator.vibrate?.(4);
    }
  }, [onPreview, snap, duration]);

  const open = (m: Mode) => {
    const a = audioRef.current;
    st.current.wasPlaying = !!a && !a.paused;
    a?.pause();
    st.current.base = a?.currentTime ?? 0;
    st.current.lastHaptic = Math.floor(st.current.base / HAPTIC_EVERY_SEC);
    previewRef.current = st.current.base;
    setOrigin({ base: st.current.base, duration: duration() });
    setPreview(st.current.base);
    onPreview(st.current.base);
    setMode(m);
  };

  const close = useCallback((commit: boolean) => {
    if (idleTimer.current) window.clearTimeout(idleTimer.current);
    setMode("closed");
    onPreview(null);
    if (commit) onCommit(previewRef.current);
    else if (st.current.wasPlaying) audioRef.current?.play();
  }, [audioRef, onCommit, onPreview]);

  const armIdle = useCallback(() => {
    if (idleTimer.current) window.clearTimeout(idleTimer.current);
    idleTimer.current = window.setTimeout(() => close(true), STICKY_IDLE_MS);
  }, [close]);

  // --- pointer: press-hold-drag on the gizmo (or on the open ruler) --------
  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    try {
      // Keep receiving moves even when the finger/cursor leaves the button.
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      // pointer already gone (or synthetic) -- scrubbing still works while over it
    }
    if (mode === "closed") open("held");
    else setMode("held");
    if (idleTimer.current) window.clearTimeout(idleTimer.current);
    st.current.startX = e.clientX;
    st.current.startT = previewRef.current;
    st.current.moved = false;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (mode !== "held") return;
    const dx = e.clientX - st.current.startX;
    if (Math.abs(dx) > DRAG_THRESHOLD_PX) st.current.moved = true;
    if (st.current.moved) setT(st.current.startT - dx / PX_PER_SEC);
  };
  const onPointerUp = () => {
    if (mode !== "held") return;
    if (st.current.moved || previewRef.current !== st.current.base) close(true);
    else { setMode("sticky"); armIdle(); } // a tap: stay open for touchpad scrolling
  };

  // --- touchpad / mouse wheel while open ------------------------------------
  useEffect(() => {
    if (mode === "closed") return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      // Horizontal two-finger swipe is the natural gesture; vertical works too.
      const d = Math.abs(e.deltaX) >= Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const px = e.deltaMode === 1 ? d * 16 : d;
      setT(previewRef.current + px / PX_PER_SEC);
      st.current.moved = true;
      if (mode === "sticky") armIdle();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
      if (e.key === "Enter") close(true);
      if (e.key === "ArrowLeft") { setT(previewRef.current - 1); if (mode === "sticky") armIdle(); }
      if (e.key === "ArrowRight") { setT(previewRef.current + 1); if (mode === "sticky") armIdle(); }
    };
    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKey);
    };
  }, [mode, setT, armIdle, close]);

  useEffect(() => () => { if (idleTimer.current) window.clearTimeout(idleTimer.current); }, []);

  // --- ruler geometry ---------------------------------------------------------
  const HALF_SPAN = 26; // seconds visible either side of the needle
  const first = Math.floor(preview - HALF_SPAN), last = Math.ceil(preview + HALF_SPAN);
  const ticks: { t: number; kind: "minor" | "mid" | "major" }[] = [];
  for (let t = Math.max(0, first); t <= last; t++) {
    ticks.push({ t, kind: t % 10 === 0 ? "major" : t % 5 === 0 ? "mid" : "minor" });
  }
  const markers = chunks.filter((c) => c.t0 >= preview - HALF_SPAN && c.t0 <= preview + HALF_SPAN);
  const x = (t: number) => `calc(50% + ${(t - preview) * PX_PER_SEC}px)`;
  const isOpen = mode !== "closed";
  const offset = preview - origin.base;

  return (
    <>
      <button
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => close(false)}
        onContextMenu={(e) => e.preventDefault()}
        title="Hold and drag (or scroll) to scrub; release to resume"
        aria-label="Scrub audio"
        className={`flex h-10 w-10 touch-none select-none items-center justify-center rounded-full transition active:scale-90 ${
          isOpen ? "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/60" : "text-neutral-300 hover:bg-neutral-800 hover:text-white"
        }`}
      >
        <WheelIcon />
      </button>

      {/* The dial: pops up just above the player bar (PlayerBar's footer is
          its positioned ancestor), only while active. */}
      <div
        aria-hidden={!isOpen}
        className={`pointer-events-none absolute inset-x-0 bottom-[calc(100%_+_12px)] z-50 flex justify-center px-4 transition-all duration-200 ease-out ${
          isOpen ? "translate-y-0 scale-100 opacity-100" : "translate-y-3 scale-95 opacity-0"
        }`}
      >
        <div
          onPointerDown={isOpen ? onPointerDown : undefined}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          className={`relative w-[min(92vw,560px)] touch-none select-none overflow-hidden rounded-2xl border border-white/10 bg-neutral-900/85 shadow-2xl shadow-black/60 backdrop-blur-md ${
            isOpen ? "pointer-events-auto" : ""
          }`}
        >
          <div className="flex items-baseline justify-between px-4 pt-3">
            <span className="text-xl font-semibold tabular-nums text-white">{fmtOffset(offset)}</span>
            <span className="text-xs tabular-nums text-neutral-400">
              {fmt(preview)} / {fmt(origin.duration)}
            </span>
          </div>

          {/* tape */}
          <div className="relative mt-1 h-16" style={{ maskImage: "linear-gradient(90deg, transparent, #000 18%, #000 82%, transparent)" }}>
            {ticks.map(({ t, kind }) => (
              <div key={t} className="absolute bottom-3" style={{ left: x(t) }}>
                <div
                  className={`-translate-x-1/2 rounded-full ${
                    kind === "major" ? "h-7 w-[2px] bg-neutral-200" : kind === "mid" ? "h-5 w-[1.5px] bg-neutral-400" : "h-3 w-px bg-neutral-600"
                  }`}
                />
                {kind === "major" && (
                  <span className="absolute -top-5 -translate-x-1/2 text-[10px] tabular-nums text-neutral-400">{fmt(t)}</span>
                )}
              </div>
            ))}
            {/* chunk starts: where a passage begins (snap points) */}
            {markers.map((c) => (
              <div key={c.index} className="absolute bottom-0.5 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-emerald-400/80" style={{ left: x(c.t0) }} />
            ))}
            {/* needle */}
            <div className="absolute inset-y-1 left-1/2 w-[3px] -translate-x-1/2 rounded-full bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.7)]" />
          </div>

          <p className="px-4 pb-3 text-center text-[11px] text-neutral-500">
            {mode === "sticky" ? "Scroll to scrub · resumes when you stop · Esc to cancel" : "Release to resume"}
          </p>
        </div>
      </div>
    </>
  );
}
