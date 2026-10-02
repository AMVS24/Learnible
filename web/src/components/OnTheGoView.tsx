import type { FigureEntry, PageInfo } from "@/lib/types";

const PAD_PT = 6; // padding around the figure+caption union, in PDF points

// Crops a figure (plus its caption, if any) straight out of the full page
// image -- no separate cropped-PNG export needed. Ported from the recovered
// original app's fig-crop technique, but done in point-space percentages
// instead of pixel offsets against a known zoom factor: the outer card's
// aspect-ratio is fixed to the crop region's own aspect ratio, and the full
// page <img> is sized/positioned as percentages of that box. CSS resolves
// `top`/`left` percentages against the containing block's height/width
// respectively, so this lines up without needing the image's pixel dims.
function FigureCrop({ base, figure, pageInfo }: { base: string; figure: FigureEntry; pageInfo: PageInfo }) {
  let [x0, y0, x1, y1] = figure.bbox;
  if (figure.caption_bbox) {
    const [cx0, cy0, cx1, cy1] = figure.caption_bbox;
    x0 = Math.min(x0, cx0); y0 = Math.min(y0, cy0);
    x1 = Math.max(x1, cx1); y1 = Math.max(y1, cy1);
  }
  x0 -= PAD_PT; y0 -= PAD_PT; x1 += PAD_PT; y1 += PAD_PT;
  const cropW = x1 - x0, cropH = y1 - y0;

  return (
    <div
      className="relative overflow-hidden rounded-xl shadow-2xl ring-1 ring-neutral-800"
      style={{ width: "min(90vw, 560px)", aspectRatio: `${cropW} / ${cropH}` }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- pipeline-generated, not a static build asset */}
      <img
        src={`${base}/pages/${pageInfo.image}`}
        alt={figure.label ?? `figure ${figure.index}`}
        className="absolute max-w-none"
        style={{
          width: `${(pageInfo.width / cropW) * 100}%`,
          left: `${(-x0 / cropW) * 100}%`,
          top: `${(-y0 / cropH) * 100}%`,
        }}
      />
    </div>
  );
}

// The "on the go" mode: full-bleed, one figure, nothing else -- meant to be
// glanced at without reading a transcript while the narration plays.
export default function OnTheGoView({
  base,
  figures,
  pages,
  page,
}: {
  base: string; // chapter data dir, e.g. "/data/ostep/ch16"
  figures: FigureEntry[];
  pages: Record<number, PageInfo>;
  page: number;
}) {
  const figure = figures[figures.length - 1] ?? null;
  const pageInfo = figure ? pages[figure.page] : undefined;

  if (!figure || !pageInfo) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-neutral-600">
        <p className="text-lg">No figure active yet</p>
        <p className="text-sm">Page {page}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <FigureCrop base={base} figure={figure} pageInfo={pageInfo} />
      <div className="text-center">
        <p className="text-xl font-medium text-emerald-400">{figure.label}</p>
        <p className="mt-1 max-w-md text-sm text-neutral-500">{figure.caption}</p>
      </div>
    </div>
  );
}
