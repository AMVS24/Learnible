// Mirrors output/manifest.json from tts/synth_local.py's `build_manifest`.
// Keep in sync by hand -- there's no shared schema between the two languages.

export type ChunkCategory =
  | "info"
  | "reference"
  | "exercise"
  | "illustrative_example"
  | "title"
  | "isolated_textbox"
  | "code_listing"
  | "other";

export interface Chunk {
  index: number;
  page: number;
  category: ChunkCategory;
  text: string;
  bbox: [number, number, number, number]; // PDF points, same space as PageInfo.width/height
  t0: number; // seconds into the narration audio
  t1: number;
  active_figures: string[]; // last non-empty figure_refs seen up to this chunk
}

export interface FigureEntry {
  index: number;
  page: number;
  label: string | null;
  category: "referable" | "table" | "code_listing" | "misc_textbox" | "decorative" | "other";
  source: "text" | "visual";
  confidence: number;
  bbox: [number, number, number, number];
  caption_bbox: [number, number, number, number] | null;
  caption: string;
}

export interface PageInfo {
  image: string; // filename in /data/pages/
  width: number; // PDF points
  height: number; // PDF points
}

export interface Manifest {
  source: {
    pdf: string;
    page_start: number;
    page_end: number;
    chapter_start?: number; // chapter opener page; absent on older whole-chapter renders (== page_start)
    // Printed page = PDF page - page_offset, for books with one continuous
    // numbering (Lewis & Papadimitriou: 14). null/absent = per-chapter
    // numbering (OSTEP), counted from chapter_start.
    page_offset?: number | null;
    trim?: { start: string | null; stop: string | null }; // partial units only
  };
  audio: string; // filename in /data/, e.g. "narration.mp3"
  pages: Record<number, PageInfo>;
  chunks: Chunk[];
  figures: FigureEntry[];
  orphan_figures: string[];
}

// Mirrors output/<book>/catalog.json from src/chapters.py. Page numbers are
// PDF pages (1-based), not the book's printed page numbers.
export interface ChapterEntry {
  id: string; // "ch16", "appB" -- also the URL segment and data dir name
  num: string;
  title: string;
  part: string; // "Part I: Virtualization", "Appendix", ...
  pdf_start: number;
  pdf_end: number;
  body_end: number; // last narrated page (References/Homework excluded)
  verified: boolean;
  rendered: boolean; // manifest.json + narration.mp3 exist for this chapter
  // Partial-chapter units (src/ostep_units.json): narrated from start_heading
  // up to but not including stop_heading; listed right after `parent`.
  partial?: boolean;
  parent?: string;
  start_heading?: string | null;
  stop_heading?: string | null;
}

export interface Book {
  id: string; // "ostep"
  title: string;
  page_offset?: number | null; // see Manifest.source.page_offset
  chapters: ChapterEntry[];
}
