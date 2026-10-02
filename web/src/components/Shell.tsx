"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import type { Book, ChapterEntry } from "@/lib/types";

function groupByPart(chapters: ChapterEntry[]): [string, ChapterEntry[]][] {
  const groups: [string, ChapterEntry[]][] = [];
  for (const ch of chapters) {
    const last = groups[groups.length - 1];
    if (last && last[0] === ch.part) last[1].push(ch);
    else groups.push([ch.part, [ch]]);
  }
  return groups;
}

function BookIndex({ book, pathname, onPick }: { book: Book; pathname: string; onPick: () => void }) {
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

      <nav className="mt-1 space-y-3 pb-4 pl-2">
        {groupByPart(book.chapters).map(([part, chapters]) => (
          <div key={part}>
            <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-600">{part}</p>
            <ul>
              {chapters.map((ch) => {
                const href = `/${book.id}/${ch.id}`;
                // Partial units sit under their parent chapter, marked ↳,
                // with the section range in the title ("§28.1–28.2 (partial)").
                const label = (
                  <>
                    <span className="w-6 shrink-0 text-right tabular-nums text-neutral-600">
                      {ch.partial ? "↳" : ch.num}
                    </span>
                    <span className={`min-w-0 flex-1 truncate ${ch.partial ? "pl-2" : ""}`}>{ch.title}</span>
                  </>
                );
                if (!ch.rendered) {
                  return (
                    <li
                      key={ch.id}
                      title={ch.partial
                        ? `Not narrated yet (from ${ch.start_heading ?? "chapter start"} to before ${ch.stop_heading ?? "end"})`
                        : `Not narrated yet (PDF pages ${ch.pdf_start}-${ch.pdf_end})`}
                      className="flex gap-2 px-2 py-1 text-xs text-neutral-600"
                    >
                      {label}
                    </li>
                  );
                }
                const active = pathname === href;
                return (
                  <li key={ch.id}>
                    <Link
                      href={href}
                      onClick={onPick}
                      title={`PDF pages ${ch.pdf_start}-${ch.body_end}`}
                      className={`flex items-center gap-2 rounded-md px-2 py-1 text-xs transition ${
                        active
                          ? "bg-emerald-600/20 text-emerald-300"
                          : "text-neutral-200 hover:bg-neutral-800"
                      }`}
                    >
                      {label}
                      <span className="text-emerald-500" aria-label="narrated">♪</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </details>
  );
}

// App frame: a textbook/chapter index in a sidebar (always visible on
// desktop, a slide-over drawer on mobile) next to the page content.
export default function Shell({ books, children }: { books: Book[]; children: ReactNode }) {
  const pathname = usePathname();
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
      <p className="px-4 pb-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">Textbooks</p>
      <div className="flex-1 overflow-y-auto px-2">
        {books.length === 0 ? (
          <p className="px-2 text-xs text-neutral-600">No textbooks synced yet.</p>
        ) : (
          books.map((b) => <BookIndex key={b.id} book={b} pathname={pathname} onPick={() => setOpen(false)} />)
        )}
      </div>
    </aside>
  );

  return (
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
  );
}
