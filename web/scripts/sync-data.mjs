#!/usr/bin/env node
// Copies the Python pipeline's per-chapter output into web/public/data/ so
// Next.js can serve it. Next.js can only serve static files from inside the
// project (public/), so `../output` isn't reachable directly -- this is the
// bridge. Re-run after every `python -m src.chapters render ...`.
//
//   output/<book>/catalog.json              -> public/data/<book>/catalog.json
//   output/<book>/<chapter>/manifest.json   -> public/data/<book>/<chapter>/...
//                          /narration.mp3
//                          /pages/
//
// Only the mp3 ships, never narration.wav: Vercel (Hobby plan) rejects any
// single file over 100MB. reading_sequence.json is pipeline-internal (the
// manifest already carries everything the app needs).
import { cp, mkdir, access, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outputDir = path.join(webRoot, "..", "output");
const dataDir = path.join(webRoot, "public", "data");
const CHAPTER_FILES = ["manifest.json", "narration.mp3", "pages"];

async function exists(p) {
  try { await access(p); return true; } catch { return false; }
}

async function main() {
  if (!(await exists(outputDir))) {
    console.error(`No output/ dir found at ${outputDir} -- run the Python pipeline first.`);
    process.exit(1);
  }
  let books = 0;
  for (const entry of await readdir(outputDir, { withFileTypes: true })) {
    const catalogPath = path.join(outputDir, entry.name, "catalog.json");
    if (!entry.isDirectory() || !(await exists(catalogPath))) continue;
    books++;
    const catalog = JSON.parse(await readFile(catalogPath, "utf-8"));
    const bookOut = path.join(dataDir, catalog.id);
    await mkdir(bookOut, { recursive: true });

    // `rendered` is recomputed from what's actually on disk, so the sidebar
    // never links a chapter whose files didn't make it across.
    for (const ch of catalog.chapters) {
      const src = path.join(outputDir, entry.name, ch.id);
      const present = await Promise.all(CHAPTER_FILES.map((f) => exists(path.join(src, f))));
      ch.rendered = present.every(Boolean);
      if (!ch.rendered) continue;
      for (const f of CHAPTER_FILES) {
        await cp(path.join(src, f), path.join(bookOut, ch.id, f), { recursive: true });
      }
      console.log(`  synced ${catalog.id}/${ch.id}  ${ch.title}`);
    }
    await writeFile(path.join(bookOut, "catalog.json"), JSON.stringify(catalog, null, 2));
  }
  if (!books) {
    console.error("No output/<book>/catalog.json found -- run `python -m src.chapters scan` first.");
    process.exit(1);
  }
  console.log(`Data synced -> ${dataDir}`);
}

main();
