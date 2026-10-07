import Link from "next/link";
import { notFound } from "next/navigation";
import { loadLibrary, narrationSeconds } from "@/lib/data";
import BookContents from "@/components/BookContents";
import { ModeToggle } from "@/components/mode";
import ContinueCard from "@/components/ContinueCard";

export const dynamicParams = false;

export async function generateStaticParams() {
  return (await loadLibrary()).map((b) => ({ book: b.id }));
}

// A book's units: grouped by the course's slide decks (exam mode, default) or
// laid out as the textbook's contents page (textbook mode).
export default async function BookPage({ params }: PageProps<"/[book]">) {
  const { book: bookId } = await params;
  const book = (await loadLibrary()).find((b) => b.id === bookId);
  if (!book) notFound();

  const narrated = book.chapters.filter((c) => c.rendered);
  const minutes: Record<string, number> = {};
  for (const c of narrated) minutes[c.id] = Math.round((await narrationSeconds(book.id, c.id)) / 60);

  return (
    // See app/page.tsx: min-h-0 keeps tall content scrollable from the top.
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto p-6">
      <div className="w-full max-w-xl">
        <Link href="/" className="text-xs text-neutral-500 hover:text-neutral-300">← All textbooks</Link>
        <h1 className="mt-2 text-2xl font-semibold text-neutral-100">{book.title}</h1>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-neutral-500">
            {narrated.length} narrated {narrated.length === 1 ? "unit" : "units"}. Pick one to start listening.
          </p>
          <ModeToggle className="w-44" />
        </div>
        <div className="mt-5">
          <ContinueCard books={[{ id: book.id, title: book.title }]} />
        </div>
        <div className="mt-6 pb-8">
          <BookContents book={book} variant="page" minutes={minutes} />
        </div>
      </div>
    </div>
  );
}
