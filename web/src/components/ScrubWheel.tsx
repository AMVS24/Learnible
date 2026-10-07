"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { Chunk } from "@/lib/types";

// Press-and-hold audio scrubber, after the iPhone camera's zoom dial: hold
// the gizmo (or the Q key, on a laptop) and a ruler pops up over the player;
// drag (finger / mouse), two-finger-scroll (touchpad), or -- while Q is held
// -- just move the cursor to slide the tape under a fixed needle, and release
// to resume playback from there. A quick tap on the gizmo opens it "sticky"
// for touchpad scrolling; it commits after a short idle, Esc cancels.
//
// Tape semantics: content follows the finger. Dragging right pulls earlier
// audio under the needle (rewind); dragging left goes forward.
//
// Feedback: soft clicks as the needle crosses each second (deeper every 5 s),
// a blip on open and on commit, a light haptic tick on phones, and the passage
// under the needle shown in the dial.

const PX_PER_SEC = 56;          // ruler scale (4x finer than the first cut's 14)
const SNAP_SEC = 0.25;          // snap to a chunk start within this distance
const DRAG_THRESHOLD_PX = 6;    // below this a press counts as a tap
const STICKY_IDLE_MS = 1100;    // sticky mode commits after this much quiet
const HALF_SPAN = 6;            // seconds visible either side of the needle

function fmt(t: number): string {
  const s = Math.max(0, Math.round(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
// Offset readout with tenths -- at this resolution whole seconds hide the movement.
function fmtOffset(d: number): string {
  const sign = d < -0.05 ? "−" : d > 0.05 ? "+" : "±";
  const a = Math.abs(d);
  const m = Math.floor(a / 60), s = a - m * 60;
  return `${sign}${m}:${s.toFixed(1).padStart(4, "0")}`;
}

// --- sound -------------------------------------------------------------------
// Tiny WebAudio blips, synthesised (no assets). The context is created on the
// first press / Q (a user gesture, so browsers allow audio).
let ctx: AudioContext | null = null;
let lastTick = 0;
function blip(freq: number, ms: number, gain: number, toFreq?: number) {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const t = ctx.currentTime;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, t);
    if (toFreq) osc.frequency.exponentialRampToValueAtTime(toFreq, t + ms / 1000);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);
    osc.connect(g).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + ms / 1000 + 0.02);
  } catch {
    // no audio available -- feedback is a nicety
  }
}
const sound = {
  tick(major: boolean) {
    const now = performance.now();
    if (now - lastTick < 28) return; // a fast fling shouldn't buzz
    lastTick = now;
    if (major) blip(1300, 28, 0.09);
    else blip(2400, 14, 0.045);
  },
  open: () => blip(520, 70, 0.06, 820),
  commit: () => blip(880, 90, 0.07, 560),
  cancel: () => blip(420, 80, 0.05, 300),
};

const WheelIcon = () => (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
    <path d="M4 9v6M8 7.5v9M12 5v14M16 7.5v9M20 9v6" />
  </svg>
);

// held: gizmo pressed; sticky: opened by a tap, scroll to scrub; key: Q held
type Mode = "closed" | "held" | "sticky" | "key";

function isTyping(el: EventTarget | null): boolean {
  const n = el as HTMLElement | null;
  return !!n && (n.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(n.tagName));
}

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
  const st = useRef({ startX: 0, startT: 0, base: 0, moved: false, wasPlaying: false });
  const idleTimer = useRef<number | null>(null);
  const previewRef = useRef(0);
  const modeRef = useRef<Mode>("closed");
  useEffect(() => { modeRef.current = mode; }, [mode]);

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
    const before = previewRef.current;
    const t = Math.min(Math.max(0, raw), duration());
    const shown = snap(t);
    previewRef.current = shown;
    setPreview(shown);
    onPreview(shown);
    // Feedback for each whole second crossed (deeper + haptic every 5 s).
    if (Math.floor(shown) !== Math.floor(before)) {
      const major = Math.floor(shown / 5) !== Math.floor(before / 5);
      sound.tick(major);
      if (major) navigator.vibrate?.(4);
    }
  }, [onPreview, snap, duration]);

  const open = useCallback((m: Mode) => {
    const a = audioRef.current;
    st.current.wasPlaying = !!a && !a.paused;
    a?.pause();
    st.current.base = a?.currentTime ?? 0;
    st.current.moved = false;
    previewRef.current = st.current.base;
    setOrigin({ base: st.current.base, duration: duration() });
    setPreview(st.current.base);
    onPreview(st.current.base);
    setMode(m);
    sound.open();
  }, [audioRef, duration, onPreview]);

  const close = useCallback((commit: boolean) => {
    if (idleTimer.current) window.clearTimeout(idleTimer.current);
    setMode("closed");
    onPreview(null);
    if (commit) {
      sound.commit();
      onCommit(previewRef.current);
    } else {
      sound.cancel();
      if (st.current.wasPlaying) audioRef.current?.play();
    }
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

  // --- laptop: hold Q ------------------------------------------------------------
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      if ((e.key === "q" || e.key === "Q") && modeRef.current === "closed") {
        e.preventDefault();
        open("key");
      }
    };
    const up = (e: KeyboardEvent) => {
      if ((e.key === "q" || e.key === "Q") && modeRef.current === "key") {
        close(st.current.moved || previewRef.current !== st.current.base);
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [open, close]);

  // While Q is held, plain cursor movement (no click needed) scrubs too.
  useEffect(() => {
    if (mode !== "key") return;
    const move = (e: PointerEvent) => {
      if (!e.movementX) return;
      st.current.moved = true;
      setT(previewRef.current - e.movementX / PX_PER_SEC);
    };
    window.addEventListener("pointermove", move);
    return () => window.removeEventListener("pointermove", move);
  }, [mode, setT]);

  // --- touchpad / mouse wheel + keys while open -------------------------------
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
      if (e.key === "ArrowLeft") { setT(previewRef.current - 1); st.current.moved = true; if (mode === "sticky") armIdle(); }
      if (e.key === "ArrowRight") { setT(previewRef.current + 1); st.current.moved = true; if (mode === "sticky") armIdle(); }
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
  // Quarter-second minor ticks, a taller one each second, labelled every 5 s.
  const ticks: { t: number; kind: "minor" | "mid" | "major" }[] = [];
  for (let q = Math.max(0, Math.floor((preview - HALF_SPAN) * 4)); q <= Math.ceil((preview + HALF_SPAN) * 4); q++) {
    const t = q / 4;
    ticks.push({ t, kind: q % 20 === 0 ? "major" : q % 4 === 0 ? "mid" : "minor" });
  }
  const markers = chunks.filter((c) => c.t0 >= preview - HALF_SPAN && c.t0 <= preview + HALF_SPAN);
  const x = (t: number) => `calc(50% + ${(t - preview) * PX_PER_SEC}px)`;
  const isOpen = mode !== "closed";
  const offset = preview - origin.base;
  // The passage under the needle, so you can see where you'd land.
  let here: Chunk | null = null;
  for (const c of chunks) { if (c.t0 <= preview) here = c; else break; }

  const hint = {
    closed: "",
    held: "Release to resume",
    sticky: "Scroll to scrub · resumes when you stop · Esc to cancel",
    key: "Scroll or move the cursor · release Q to resume · Esc to cancel",
  }[mode];

  return (
    <>
      <button
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => close(false)}
        onContextMenu={(e) => e.preventDefault()}
        title="Hold and drag (or scroll) to scrub; release to resume. On a keyboard: hold Q."
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
                    kind === "major" ? "h-7 w-[2px] bg-neutral-200" : kind === "mid" ? "h-5 w-[1.5px] bg-neutral-400" : "h-2.5 w-px bg-neutral-600"
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

          {here && (
            <p className="mx-4 line-clamp-2 border-l-2 border-emerald-500/60 pl-2 text-[12px] leading-snug text-neutral-300">
              {here.text}
            </p>
          )}
          <p className="px-4 pb-3 pt-1.5 text-center text-[11px] text-neutral-500">{hint}</p>
        </div>
      </div>
    </>
  );
}
