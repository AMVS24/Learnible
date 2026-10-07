"use client";

import { useState, type ReactNode, type RefObject } from "react";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

// Inline SVG icons (24x24 grid, currentColor) instead of emoji glyphs, which
// render differently on every platform and look out of place.
function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      {children}
    </svg>
  );
}
const PrevPageIcon = () => (
  <Icon><rect x="5" y="5" width="2.4" height="14" rx="1.2" /><path d="M19 6.2v11.6a1 1 0 0 1-1.55.83l-8.6-5.8a1 1 0 0 1 0-1.66l8.6-5.8A1 1 0 0 1 19 6.2Z" /></Icon>
);
const NextPageIcon = () => (
  <Icon><rect x="16.6" y="5" width="2.4" height="14" rx="1.2" /><path d="M5 6.2v11.6a1 1 0 0 0 1.55.83l8.6-5.8a1 1 0 0 0 0-1.66l-8.6-5.8A1 1 0 0 0 5 6.2Z" /></Icon>
);
const PrevChunkIcon = () => (
  <Icon><path d="M11.5 7v10a.8.8 0 0 1-1.28.64L3.6 12.64a.8.8 0 0 1 0-1.28l6.62-5A.8.8 0 0 1 11.5 7Z" /><path d="M20.5 7v10a.8.8 0 0 1-1.28.64l-6.62-5a.8.8 0 0 1 0-1.28l6.62-5A.8.8 0 0 1 20.5 7Z" /></Icon>
);
const NextChunkIcon = () => (
  <Icon><path d="M12.5 7v10a.8.8 0 0 0 1.28.64l6.62-5a.8.8 0 0 0 0-1.28l-6.62-5A.8.8 0 0 0 12.5 7Z" /><path d="M3.5 7v10a.8.8 0 0 0 1.28.64l6.62-5a.8.8 0 0 0 0-1.28l-6.62-5A.8.8 0 0 0 3.5 7Z" /></Icon>
);
const PlayIcon = () => (
  <Icon size={22}><path d="M8 5.6v12.8a1.1 1.1 0 0 0 1.68.93l10.1-6.4a1.1 1.1 0 0 0 0-1.86l-10.1-6.4A1.1 1.1 0 0 0 8 5.6Z" /></Icon>
);
const PauseIcon = () => (
  <Icon size={22}><rect x="6" y="5" width="4.2" height="14" rx="1.3" /><rect x="13.8" y="5" width="4.2" height="14" rx="1.3" /></Icon>
);
const VolumeIcon = () => (
  <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M11 5 6 9H3v6h3l5 4V5Z" fill="currentColor" stroke="none" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7" />
    <path d="M18.5 5.5a9 9 0 0 1 0 13" />
  </svg>
);

// touch-manipulation: no double-tap-to-zoom wait on mobile, so taps register
// immediately.
const btn =
  "flex h-9 w-9 touch-manipulation items-center justify-center rounded-full text-neutral-300 transition hover:bg-neutral-800 hover:text-white active:scale-90";

export default function PlayerBar({
  audioRef,
  audioSrc,
  onTimeUpdate,
  onPrevPage,
  onNextPage,
  onPrevChunk,
  onNextChunk,
  scrub,
  translucent = false,
}: {
  audioRef: RefObject<HTMLAudioElement | null>;
  audioSrc: string;
  onTimeUpdate: (t: number) => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onPrevChunk: () => void;
  onNextChunk: () => void;
  scrub?: ReactNode; // the press-and-hold scrub gizmo (ScrubWheel), next to the transport
  translucent?: boolean; // frosted, see-through (scroll mode lays it over the pages)
}) {
  const [playing, setPlaying] = useState(false);

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play(); else a.pause();
  };

  return (
    <footer
      className={`relative border-t px-4 py-2 ${
        translucent ? "border-white/5 bg-neutral-950/55 backdrop-blur-md" : "border-neutral-800 bg-neutral-900/60"
      }`}
    >
      <audio
        ref={audioRef}
        src={audioSrc}
        preload="auto"
        // While a seek is still fetching audio, ignore time updates (the
        // skip handlers already moved the page/highlight to the target), and
        // re-sync once the seek lands.
        onTimeUpdate={(e) => { if (!e.currentTarget.seeking) onTimeUpdate(e.currentTarget.currentTime); }}
        onSeeked={(e) => onTimeUpdate(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />
      {/* One row: transport centred; volume + speed at the right. The left
          spacer balances the right group so the transport stays centred on
          wider screens; on phones the volume slider is hidden (hardware
          buttons) and everything fits on one line. */}
      <div className="flex items-center gap-2">
        <div className="hidden flex-1 sm:block" />
        <div className="flex flex-1 items-center justify-center gap-1 sm:flex-none">
          <button onClick={onPrevPage} title="Previous page" aria-label="Previous page" className={btn}>
            <PrevPageIcon />
          </button>
          <button onClick={onPrevChunk} title="Previous chunk" aria-label="Previous chunk" className={btn}>
            <PrevChunkIcon />
          </button>
          <button
            onClick={togglePlay}
            title="Play / pause"
            aria-label={playing ? "Pause" : "Play"}
            className="mx-1.5 flex h-11 w-11 touch-manipulation items-center justify-center rounded-full bg-emerald-500 text-neutral-950 shadow-lg shadow-emerald-900/40 transition hover:bg-emerald-400 active:scale-95"
          >
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
          <button onClick={onNextChunk} title="Next chunk" aria-label="Next chunk" className={btn}>
            <NextChunkIcon />
          </button>
          <button onClick={onNextPage} title="Next page" aria-label="Next page" className={btn}>
            <NextPageIcon />
          </button>
          {scrub && <div className="ml-1 border-l border-neutral-700/60 pl-1">{scrub}</div>}
        </div>

        <div className="flex items-center justify-end gap-3 sm:flex-1">
          <label className="hidden items-center gap-1.5 text-neutral-400 sm:flex" title="Volume">
            <VolumeIcon />
            <input
              type="range" min={0} max={1} step={0.05} defaultValue={1}
              onChange={(e) => { if (audioRef.current) audioRef.current.volume = +e.target.value; }}
              className="w-20 accent-emerald-500"
            />
          </label>
          <select
            title="Playback speed"
            defaultValue={1}
            onChange={(e) => { if (audioRef.current) audioRef.current.playbackRate = +e.target.value; }}
            className="rounded-md border border-neutral-700 bg-neutral-900/80 px-1.5 py-1 text-xs text-neutral-300"
          >
            {SPEEDS.map((sp) => (
              <option key={sp} value={sp}>{sp}×</option>
            ))}
          </select>
        </div>
      </div>
    </footer>
  );
}
