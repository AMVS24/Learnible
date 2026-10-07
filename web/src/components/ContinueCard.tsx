"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fmtTime, progress, type BookLast } from "@/lib/progress";

// "Continue listening" -- the last chapter + time you were on in each given
// textbook (from localStorage, so it only appears after hydration, and only
// for books you've actually listened to on this device).
export default function ContinueCard({ books }: { books: { id: string; title: string }[] }) {
  const [items, setItems] = useState<{ id: string; title: string; last: BookLast }[]>([]);
  useEffect(() => {
    const found = books
      .map((b) => ({ ...b, last: progress.bookLast(b.id) }))
      .filter((b): b is { id: string; title: string; last: BookLast } => !!b.last)
      .sort((a, b) => b.last.at - a.last.at);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of browser storage after hydration
    setItems(found);
  }, [books]);

  if (!items.length) return null;
  return (
    <div className="w-full space-y-2 text-left">
      <p className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">Continue listening</p>
      {items.map(({ id, title, last }) => (
        <Link
          key={id}
          href={`/${id}/${last.chapter}`}
          className="flex items-center gap-3 rounded-xl border border-emerald-800/60 bg-emerald-950/30 px-4 py-3 transition hover:border-emerald-600 hover:bg-emerald-950/50"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-neutral-950">
            <svg width={16} height={16} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.6v12.8a1.1 1.1 0 0 0 1.68.93l10.1-6.4a1.1 1.1 0 0 0 0-1.86l-10.1-6.4A1.1 1.1 0 0 0 8 5.6Z" />
            </svg>
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-neutral-100">{last.title}</span>
            <span className="block truncate text-xs text-neutral-500">
              {books.length > 1 ? `${title} · ` : ""}at {fmtTime(last.t)}
            </span>
          </span>
        </Link>
      ))}
    </div>
  );
}
