import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import type { Book, Manifest } from "./types";

// Data is synced from ../output (the Python pipeline's output dir) into
// public/data by scripts/sync-data.mjs -- see that file for why: Next.js
// can't serve files from outside the project root, and copying keeps dev
// and a Vercel deploy working the same way. Layout:
//   public/data/<book>/catalog.json
//   public/data/<book>/<chapter>/{manifest.json, narration.mp3, pages/}
const DATA_DIR = path.join(process.cwd(), "public", "data");

export async function loadLibrary(): Promise<Book[]> {
  let entries: string[] = [];
  try {
    entries = await fs.readdir(DATA_DIR);
  } catch {
    return [];
  }
  const books: Book[] = [];
  for (const name of entries.sort()) {
    try {
      const raw = await fs.readFile(path.join(DATA_DIR, name, "catalog.json"), "utf-8");
      books.push(JSON.parse(raw));
    } catch {
      // not a book dir
    }
  }
  return books;
}

export function chapterBase(bookId: string, chapterId: string): string {
  return `/data/${bookId}/${chapterId}`;
}

// Narration length of a rendered unit: the last chunk's end time.
export async function narrationSeconds(bookId: string, chapterId: string): Promise<number> {
  const { chunks } = await loadManifest(bookId, chapterId);
  return chunks.length ? chunks[chunks.length - 1].t1 : 0;
}

export async function loadManifest(bookId: string, chapterId: string): Promise<Manifest> {
  const raw = await fs.readFile(path.join(DATA_DIR, bookId, chapterId, "manifest.json"), "utf-8");
  return JSON.parse(raw);
}
