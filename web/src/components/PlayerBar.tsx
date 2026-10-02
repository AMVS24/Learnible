"use client";

import { useState, type RefObject } from "react";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

export default function PlayerBar({
  audioRef,
  audioSrc,
  onTimeUpdate,
  onPrevPage,
  onNextPage,
  onPrevChunk,
  onNextChunk,
}: {
  audioRef: RefObject<HTMLAudioElement | null>;
  audioSrc: string;
  onTimeUpdate: (t: number) => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onPrevChunk: () => void;
  onNextChunk: () => void;
}) {
  const [playing, setPlaying] = useState(false);

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play(); else a.pause();
  };

  return (
    <footer className="border-t border-neutral-800 bg-neutral-900/60 px-4 py-3">
      <audio
        ref={audioRef}
        src={audioSrc}
        onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />
      {/* flex-wrap: on a narrow (mobile) viewport, five buttons + a volume
          slider + a select don't fit on one row -- without wrapping, the
          row overflows and the leftmost button (Previous page) ends up
          rendered off-screen to the left, unreachable, not just visually
          cramped. Transport controls get their own row so they never
          reflow around the volume/speed controls. */}
      <div className="flex flex-col items-center gap-2">
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={onPrevPage}
            title="Previous page"
            className="rounded-md px-2 py-1.5 text-lg text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
          >
            ⏮
          </button>
          <button
            onClick={onPrevChunk}
            title="Previous chunk"
            className="rounded-md px-2 py-1.5 text-lg text-neutral-300 hover:bg-neutral-800 hover:text-white"
          >
            ⏪
          </button>
          <button
            onClick={togglePlay}
            title="Play / pause"
            className="mx-1 rounded-full bg-emerald-600 px-4 py-2 text-lg text-white hover:bg-emerald-500"
          >
            {playing ? "⏸" : "▶"}
          </button>
          <button
            onClick={onNextChunk}
            title="Next chunk"
            className="rounded-md px-2 py-1.5 text-lg text-neutral-300 hover:bg-neutral-800 hover:text-white"
          >
            ⏩
          </button>
          <button
            onClick={onNextPage}
            title="Next page"
            className="rounded-md px-2 py-1.5 text-lg text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
          >
            ⏭
          </button>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <label className="flex items-center gap-1.5 text-neutral-500" title="Volume">
            🔊
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
            className="rounded-md border border-neutral-700 bg-neutral-900 px-1.5 py-1 text-xs text-neutral-300"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>{s}×</option>
            ))}
          </select>
        </div>
      </div>
    </footer>
  );
}
