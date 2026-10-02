import { notFound } from "next/navigation";
import { chapterBase, loadLibrary, loadManifest } from "@/lib/data";
import Reader from "@/components/Reader";

// Only narrated chapters get a page; everything else 404s.
export const dynamicParams = false;

export async function generateStaticParams() {
  const books = await loadLibrary();
  return books.flatMap((b) =>
    b.chapters.filter((c) => c.rendered).map((c) => ({ book: b.id, chapter: c.id }))
  );
}

export default async function ChapterPage({ params }: PageProps<"/[book]/[chapter]">) {
  const { book: bookId, chapter: chapterId } = await params;
  const book = (await loadLibrary()).find((b) => b.id === bookId);
  const chapter = book?.chapters.find((c) => c.id === chapterId);
  if (!book || !chapter?.rendered) notFound();

  const manifest = await loadManifest(bookId, chapterId);
  return (
    <Reader
      key={`${bookId}/${chapterId}`}
      manifest={manifest}
      base={chapterBase(bookId, chapterId)}
      title={`${chapter.num}. ${chapter.title}`}
    />
  );
}
