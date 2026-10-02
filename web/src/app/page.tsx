import Link from "next/link";
import { loadLibrary, narrationSeconds } from "@/lib/data";

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

// Intro page: pick a textbook. Each book's narrated units live at /<book>.
export default async function Home() {
  const books = await loadLibrary();
  const cards = await Promise.all(
    books.map(async (b) => {
      const narrated = b.chapters.filter((c) => c.rendered);
      const secs = (await Promise.all(narrated.map((c) => narrationSeconds(b.id, c.id)))).reduce((a, x) => a + x, 0);
      return { book: b, narrated: narrated.length, chapters: b.chapters.filter((c) => !c.partial).length, secs };
    })
  );

  return (
    // Centred with my-auto, not justify-center: with justify-center, content
    // taller than the viewport overflows upward too, and that top part can't
    // be scrolled to. Auto margins collapse to 0 once the content overflows.
    // min-h-0 lets this flex child shrink so overflow-y-auto actually scrolls.
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto p-6 text-center">
      <div className="my-auto flex w-full max-w-lg flex-col items-center gap-8">
        <div>
          <h1 className="text-3xl font-semibold text-neutral-100">Learnible</h1>
          <p className="mt-2 text-sm text-neutral-400">Textbooks, read aloud with the page and figures in sync.</p>
        </div>

        <div className="w-full">
          <p className="mb-3 text-left text-[11px] font-medium uppercase tracking-wide text-neutral-500">
            Select a textbook
          </p>
          {cards.length === 0 ? (
            <p className="text-sm text-neutral-400">
              No textbooks yet. Run <code className="text-emerald-400">python -m src.chapters scan</code>, then{" "}
              <code className="text-emerald-400">npm run sync-data</code>.
            </p>
          ) : (
            <ul className="space-y-3">
              {cards.map(({ book, narrated, chapters, secs }) => (
                <li key={book.id}>
                  <Link
                    href={`/${book.id}`}
                    className="flex items-center gap-4 rounded-xl border border-neutral-800 bg-neutral-900/60 px-5 py-4 text-left transition hover:border-emerald-700 hover:bg-neutral-900"
                  >
                    <span className="flex h-16 w-14 shrink-0 items-center justify-center rounded-md bg-emerald-600/20 text-[11px] font-semibold uppercase text-emerald-300 ring-1 ring-emerald-700/50">
                      {book.id}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-base font-medium text-neutral-100">{book.title}</span>
                      <span className="mt-0.5 block text-xs text-neutral-500">
                        {narrated} narrated {narrated === 1 ? "unit" : "units"} &middot; {formatDuration(secs)} of audio
                        &middot; {chapters} chapters
                      </span>
                    </span>
                    <span className="text-neutral-600">→</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
