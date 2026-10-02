import type { Chunk, PageInfo } from "@/lib/types";

// Reading mode: the actual PDF page (diagrams, layout, everything, exactly
// as printed) with a translucent green box drawn over whichever chunk the
// narration is currently reading -- not a reflowed wall of extracted text.
export default function PageView({
  base,
  pageInfo,
  chunk,
}: {
  base: string; // chapter data dir, e.g. "/data/ostep/ch16"
  pageInfo: PageInfo | undefined;
  chunk: Chunk | null;
}) {
  if (!pageInfo) {
    return (
      <div className="flex h-full items-center justify-center text-neutral-600">
        No page image for this page.
      </div>
    );
  }

  const box = chunk
    ? {
        left: (chunk.bbox[0] / pageInfo.width) * 100,
        top: (chunk.bbox[1] / pageInfo.height) * 100,
        width: ((chunk.bbox[2] - chunk.bbox[0]) / pageInfo.width) * 100,
        height: ((chunk.bbox[3] - chunk.bbox[1]) / pageInfo.height) * 100,
      }
    : null;

  return (
    <div className="flex h-full items-center justify-center overflow-auto bg-neutral-900 p-6">
      <div className="relative inline-block shadow-2xl">
        {/* eslint-disable-next-line @next/next/no-img-element -- pipeline-generated, not a static build asset */}
        <img
          src={`${base}/pages/${pageInfo.image}`}
          alt={`Page ${chunk?.page ?? ""}`}
          className="block max-h-[85vh] w-auto"
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
