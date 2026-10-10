#!/usr/bin/env node
// Uploads each rendered chapter's narration.mp3 from ../output to the GitHub
// Release named in audio-host.json, as <book>-<chapter>.mp3. Only new or
// changed files (by size) are uploaded. Needs the GitHub CLI, signed in
// (`gh auth login`). Run before `npm run sync-data` + deploy.
import { copyFile, mkdtemp, readFile, readdir, rm, stat } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outputDir = path.join(webRoot, "..", "output");
const host = JSON.parse(await readFile(path.join(webRoot, "audio-host.json"), "utf-8"));
const GH = process.env.GH ?? (process.platform === "win32" ? "C:\\Program Files\\GitHub CLI\\gh.exe" : "gh");

function gh(args, opts = {}) {
  return execFileSync(GH, ["--repo", host.repo, ...args], { encoding: "utf-8", stdio: ["ignore", "pipe", "inherit"], ...opts });
}

// The release (created once).
let assets = new Map();
try {
  const info = JSON.parse(gh(["release", "view", host.tag, "--json", "assets"]));
  assets = new Map(info.assets.map((a) => [a.name, a.size]));
} catch {
  console.log(`Creating release "${host.tag}" in ${host.repo} ...`);
  gh(["release", "create", host.tag, "--title", "Narration audio",
      "--notes", "Narration MP3s for the Learnible web app (uploaded by web/scripts/upload-audio.mjs)."]);
}

const tmp = await mkdtemp(path.join(os.tmpdir(), "learnible-audio-"));
let uploaded = 0, current = 0;
try {
  for (const book of await readdir(outputDir, { withFileTypes: true })) {
    if (!book.isDirectory() || book.name.startsWith("_")) continue;
    for (const ch of await readdir(path.join(outputDir, book.name), { withFileTypes: true })) {
      if (!ch.isDirectory() || ch.name.startsWith("_")) continue;
      const mp3 = path.join(outputDir, book.name, ch.name, "narration.mp3");
      const size = await stat(mp3).then((s) => s.size, () => null);
      if (size == null) continue;
      const name = `${book.name}-${ch.name}.mp3`;
      if (assets.get(name) === size) { current++; continue; }
      const staged = path.join(tmp, name); // the asset is named after the file
      await copyFile(mp3, staged);
      console.log(`  uploading ${name} (${(size / 1e6).toFixed(1)} MB)`);
      gh(["release", "upload", host.tag, staged, "--clobber"]);
      uploaded++;
    }
  }
} finally {
  await rm(tmp, { recursive: true, force: true });
}
console.log(`Audio: ${uploaded} uploaded, ${current} already current -> https://github.com/${host.repo}/releases/tag/${host.tag}`);
