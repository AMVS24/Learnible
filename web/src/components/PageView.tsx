"use client";

import { useEffect, useRef, useState } from "react";
import type { Chunk, PageInfo } from "@/lib/types";

// Reading mode: the actual PDF page (diagrams, layout, everything, exactly
// as printed) with a translucent green box drawn over whichever chunk the
// narration is currently reading -- not a reflowed wall of extracted text.
//
// The <img> is keyed by its src, so a page turn swaps it out immediately:
// browsers otherwise keep painting the *previous* image until the new one
// has downloaded, which (with the header and highlight already on the new
// page) read as "the skip didn't register" / "the page changed seconds
// late". Until the new image arrives, a page-shaped placeholder holds its
// place; Reader preloads neighbouring pages so this is usually instant.
export default function PageView({
  base,
  pageInfo,
  chunk,
}: {
  base: string; // chapter data dir, e.g. "/data/ostep/ch16"
  pageInfo: PageInfo | undefined;
  chunk: Chunk | null;
}) {
  const src = pageInfo ? `${base}/pages/${pageInfo.image}` : "";
  // Which src has finished loading; anything else is still in flight.
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const loaded = loadedSrc === src;
  const imgRef = useRef<HTMLImageElement>(null);
  // A cached image (or one that finished before hydration) can complete
  // before onLoad is attached; catch that case so the page doesn't stay hidden.
  useEffect(() => {
    const el = imgRef.current;
    if (el && el.complete && el.naturalWidth > 0) setLoadedSrc(src);
  }, [src]);

  if (!pageInfo) {
    return (
      <div className="flex h-full items-center justify-center text-neutral-600">
        No page image for this page.
      </div>
    );
  }

  const box = chunk && loaded
    ? {
        left: (chunk.bbox[0] / pageInfo.width) * 100,
        top: (chunk.bbox[1] / pageInfo.height) * 100,
        width: ((chunk.bbox[2] - chunk.bbox[0]) / pageInfo.width) * 100,
        height: ((chunk.bbox[3] - chunk.bbox[1]) / pageInfo.height) * 100,
      }
    : null;

  return (
    <div className="flex h-full items-center justify-center overflow-auto bg-neutral-900 p-6">
      <div
        className="relative shrink-0 shadow-2xl"
        // Width-driven so it never overflows a narrow screen; capped so the
        // page is at most 85vh tall (as before). aspect-ratio reserves the
        // page's exact shape while the image is still loading.
        style={{
          aspectRatio: `${pageInfo.width} / ${pageInfo.height}`,
          width: `min(100%, calc(85vh * ${pageInfo.width / pageInfo.height}))`,
        }}
      >
        {!loaded && <div className="absolute inset-0 animate-pulse rounded-sm bg-neutral-800" />}
        {/* eslint-disable-next-line @next/next/no-img-element -- pipeline-generated, not a static build asset */}
        <img
          key={src}
          ref={imgRef}
          src={src}
          alt={`Page ${chunk?.page ?? ""}`}
          onLoad={() => setLoadedSrc(src)}
          className={`block h-full w-full transition-opacity duration-150 ${loaded ? "opacity-100" : "opacity-0"}`}
        />
        {box && (
          <div
            className="absolute rounded-sm bg-emerald-400/25 ring-2 ring-emerald-400/70 transition-all duration-300 ease-out"
            style={{
              left: `${box.left}%`,
              top: `${box.top}%`,
              width: `${box.width}%`,
              height: `${box.height}%`,
            }}
          />
        )}
      </div>
    </div>
  );
}
