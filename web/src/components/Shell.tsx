"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import type { Book } from "@/lib/types";
import BookContents from "./BookContents";
import { ModeProvider, ModeToggle } from "./mode";

function BookIndex({ book, onPick }: { book: Book; onPick: () => void }) {
  const rendered = book.chapters.filter((c) => c.rendered).length;
  const total = book.chapters.filter((c) => !c.partial).length;
  return (
    <details open className="group">
      <summary className="flex cursor-pointer list-none items-start gap-2 rounded-md px-2 py-2 hover:bg-neutral-900">
        <span className="mt-0.5 text-xs text-neutral-500 transition group-open:rotate-90">▶</span>
        <span className="min-w-0">
          <span className="block text-sm font-medium text-neutral-200">{book.title}</span>
          <span className="block text-xs text-neutral-500">
            {rendered} narrated &middot; {total} chapters
          </span>
        </span>
      </summary>
      <nav className="mt-1 pb-4 pl-2">
        <BookContents book={book} variant="sidebar" onPick={onPick} />
      </nav>
    </details>
  );
}

// App frame: a textbook index in a sidebar (always visible on desktop, a
// slide-over drawer on mobile) next to the page content. The Exam/Textbook
// toggle (see mode.tsx) switches how both the sidebar and the book page list
// a book's units.
export default function Shell({ books, children }: { books: Book[]; children: ReactNode }) {
  const [open, setOpen] = useState(false);

  const sidebar = (
    <aside className="flex h-full w-72 flex-col border-r border-neutral-800 bg-neutral-950">
      <div className="flex items-center justify-between px-4 py-3">
        <Link href="/" onClick={() => setOpen(false)} className="text-sm font-semibold text-neutral-100">
          Learnible
        </Link>
        <button
          onClick={() => setOpen(false)}
          className="rounded-md px-2 py-1 text-neutral-400 hover:bg-neutral-800 md:hidden"
          aria-label="Close menu"
        >
          ✕
        </button>
      </div>
      <ModeToggle className="mx-4 mb-3" />
      <p className="px-4 pb-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">Textbooks</p>
      <div className="flex-1 overflow-y-auto px-2">
        {books.length === 0 ? (
          <p className="px-2 text-xs text-neutral-600">No textbooks synced yet.</p>
        ) : (
          books.map((b) => <BookIndex key={b.id} book={b} onPick={() => setOpen(false)} />)
        )}
      </div>
    </aside>
  );

  return (
    <ModeProvider>
      <div className="flex h-dvh bg-neutral-950 text-neutral-100">
        <div className="hidden md:block">{sidebar}</div>
        {open && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
            <div className="relative h-full w-72 max-w-[85vw]">{sidebar}</div>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-neutral-800 px-3 py-2 md:hidden">
            <button
              onClick={() => setOpen(true)}
              className="rounded-md px-2 py-1 text-lg text-neutral-300 hover:bg-neutral-800"
              aria-label="Open textbooks menu"
            >
              ☰
            </button>
            <span className="text-sm font-semibold">Learnible</span>
          </div>
          {children}
        </div>
      </div>
    </ModeProvider>
  );
}
