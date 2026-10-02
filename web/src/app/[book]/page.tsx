import Link from "next/link";
import { notFound } from "next/navigation";
import { loadLibrary, narrationSeconds } from "@/lib/data";
import type { ChapterEntry } from "@/lib/types";

export const dynamicParams = false;

export async function generateStaticParams() {
  return (await loadLibrary()).map((b) => ({ book: b.id }));
}

// A book's narrated units, grouped by Part in reading order.
export default async function BookPage({ params }: PageProps<"/[book]">) {
  const { book: bookId } = await params;
  const book = (await loadLibrary()).find((b) => b.id === bookId);
  if (!book) notFound();

  const narrated = book.chapters.filter((c) => c.rendered);
  const mins = await Promise.all(narrated.map(async (c) => Math.round((await narrationSeconds(book.id, c.id)) / 60)));
  const minsById = new Map(narrated.map((c, i) => [c.id, mins[i]]));
  const parts: [string, ChapterEntry[]][] = [];
  for (const ch of narrated) {
    const last = parts[parts.length - 1];
    if (last && last[0] === ch.part) last[1].push(ch);
    else parts.push([ch.part, [ch]]);
  }

  return (
    // See app/page.tsx: my-auto + min-h-0 keep tall content scrollable.
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto p-6">
      <div className="my-auto w-full max-w-md">
        <Link href="/" className="text-xs text-neutral-500 hover:text-neutral-300">← All textbooks</Link>
        <h1 className="mt-2 text-2xl font-semibold text-neutral-100">{book.title}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          {narrated.length} narrated {narrated.length === 1 ? "unit" : "units"}. Pick one to start listening.
        </p>

        {narrated.length === 0 ? (
          <p className="mt-6 text-sm text-neutral-400">
            Nothing narrated yet. Run <code className="text-emerald-400">python -m src.chapters render &lt;chapter&gt;</code>.
          </p>
        ) : (
          parts.map(([part, chapters]) => (
            <section key={part} className="mt-6">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">{part}</p>
              <ul className="space-y-2">
                {chapters.map((ch) => (
                  <li key={ch.id}>
                    <Link
                      href={`/${book.id}/${ch.id}`}
                      className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900/60 px-4 py-3 hover:border-emerald-700"
                    >
                      <span className="w-6 shrink-0 text-right text-lg tabular-nums text-emerald-400">{ch.num}</span>
                      <span className="min-w-0 flex-1 truncate text-sm text-neutral-100">{ch.title}</span>
                      <span className="shrink-0 text-xs tabular-nums text-neutral-500">{minsById.get(ch.id)} min</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
