// Where you left off, per textbook and per chapter -- kept in this browser's
// localStorage (a per-device convenience, not synced anywhere). Every access
// is guarded: storage can be unavailable (private mode, blocked site data),
// in which case nothing is remembered and nothing breaks.

export type ReaderMode = "reading" | "scroll" | "onTheGo";

export interface ChapterPos {
  t: number;      // seconds into the chapter's narration
  at: number;     // when it was saved (ms since epoch)
}

export interface BookLast {
  chapter: string; // chapter id, e.g. "ch22"
  title: string;   // e.g. "22. Beyond Physical Memory: Policies"
  t: number;
  at: number;
}

const k = {
  chapter: (book: string, ch: string) => `learnible.pos.${book}.${ch}`,
  book: (book: string) => `learnible.last.${book}`,
  mode: "learnible.readerMode",
};

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable: just don't remember
  }
}

export const progress = {
  chapter: (book: string, ch: string) => read<ChapterPos>(k.chapter(book, ch)),
  bookLast: (book: string) => read<BookLast>(k.book(book)),
  save(book: string, ch: string, title: string, t: number) {
    const at = Date.now();
    write(k.chapter(book, ch), { t, at } satisfies ChapterPos);
    write(k.book(book), { chapter: ch, title, t, at } satisfies BookLast);
  },
  mode: () => read<ReaderMode>(k.mode),
  saveMode: (m: ReaderMode) => write(k.mode, m),
};

export function fmtTime(t: number): string {
  const s = Math.max(0, Math.floor(t));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
