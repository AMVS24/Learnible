"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Book, ChapterEntry } from "@/lib/types";
import { EXAM_PLANS } from "@/lib/exam";
import { useListMode } from "./mode";

type Variant = "sidebar" | "page";

function groupByPart(chapters: ChapterEntry[]): [string, ChapterEntry[]][] {
  const groups: [string, ChapterEntry[]][] = [];
  for (const ch of chapters) {
    const last = groups[groups.length - 1];
    if (last && last[0] === ch.part) last[1].push(ch);
    else groups.push([ch.part, [ch]]);
  }
  return groups;
}

function UnitRow({
  book, ch, variant, minutes, onPick, showNum = true,
}: {
  book: Book; ch: ChapterEntry; variant: Variant; minutes?: number; onPick?: () => void; showNum?: boolean;
}) {
  const pathname = usePathname();
  const href = `/${book.id}/${ch.id}`;
  const active = pathname === href;
  const small = variant === "sidebar";
  const body = (
    <>
      {showNum && (
        <span className={`w-6 shrink-0 text-right tabular-nums ${ch.rendered ? "text-emerald-400" : "text-neutral-600"} ${small ? "" : "text-base"}`}>
          {ch.num}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">{ch.title}</span>
      {ch.rendered
        ? !small && minutes != null && <span className="shrink-0 text-xs tabular-nums text-neutral-500">{minutes} min</span>
        : !small && <span className="shrink-0 text-[10px] uppercase tracking-wide text-neutral-600">not narrated</span>}
      {ch.rendered && small && <span className="text-emerald-500" aria-label="narrated">♪</span>}
    </>
  );
  const base = small
    ? "flex items-center gap-2 rounded-md px-2 py-1 text-xs"
    : "flex items-center gap-3 rounded-lg border px-4 py-3 text-sm";
  if (!ch.rendered) {
    return <div className={`${base} ${small ? "text-neutral-600" : "border-neutral-900 text-neutral-600"}`}>{body}</div>;
  }
  return (
    <Link
      href={href}
      onClick={onPick}
      className={`${base} transition ${
        active
          ? small ? "bg-emerald-600/20 text-emerald-300" : "border-emerald-700 bg-emerald-600/10 text-emerald-200"
          : small ? "text-neutral-200 hover:bg-neutral-800" : "border-neutral-800 bg-neutral-900/60 text-neutral-100 hover:border-emerald-700"
      }`}
    >
      {body}
    </Link>
  );
}

// Exam mode: the course's slide decks as headings, the units that cover each
// underneath, in study order.
function ExamView({ book, variant, minutes, onPick }: { book: Book; variant: Variant; minutes?: Record<string, number>; onPick?: () => void }) {
  const plan = EXAM_PLANS[book.id];
  const byId = new Map(book.chapters.map((c) => [c.id, c]));
  if (!plan) return <TextbookView book={book} variant={variant} minutes={minutes} onPick={onPick} />;
  const small = variant === "sidebar";
  return (
    <div className={small ? "space-y-3" : "space-y-7"}>
      {!small && <p className="text-xs text-neutral-500">{plan.course}</p>}
      {plan.decks.map((deck) => {
        const units = deck.units.map((id) => byId.get(id)).filter((c): c is ChapterEntry => !!c);
        return (
          <section key={deck.num}>
            <p className={small
              ? "flex gap-1.5 px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-500"
              : "mb-2 flex items-baseline gap-2 text-sm font-medium text-neutral-300"}>
              <span className={small ? "text-neutral-600" : "text-emerald-500"}>{small ? `${deck.num}.` : `Deck ${deck.num}`}</span>
              <span>{deck.title}</span>
            </p>
            {units.length === 0 ? (
              <p className={small ? "px-2 text-xs italic text-neutral-700" : "text-xs italic text-neutral-600"}>
                No OSTEP reading for this deck
              </p>
            ) : (
              <ul className={small ? "" : "space-y-2"}>
                {units.map((ch) => (
                  <li key={ch.id}>
                    <UnitRow book={book} ch={ch} variant={variant} minutes={minutes?.[ch.id]} onPick={onPick} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

// Textbook mode: the book's own contents page -- every chapter by Part, with
// partial units nested under their chapter. On the full page it's styled like
// a printed index (serif, dot leaders, page numbers).
function TextbookView({ book, variant, minutes, onPick }: { book: Book; variant: Variant; minutes?: Record<string, number>; onPick?: () => void }) {
  const pathname = usePathname();
  if (variant === "sidebar") {
    return (
      <div className="space-y-3">
        {groupByPart(book.chapters).map(([part, chapters]) => (
          <div key={part}>
            <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-600">{part}</p>
            <ul>
              {chapters.map((ch) => (
                <li key={ch.id} className={ch.partial ? "pl-4" : ""}>
                  <UnitRow book={book} ch={ch} variant="sidebar" onPick={onPick} showNum={!ch.partial} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="font-serif">
      <p className="mb-6 text-center text-xs uppercase tracking-[0.3em] text-neutral-500">Contents</p>
      {groupByPart(book.chapters).map(([part, chapters]) => (
        <section key={part} className="mb-6">
          <h2 className="mb-2 text-base font-semibold text-neutral-200">{part}</h2>
          <ul className="space-y-1">
            {chapters.map((ch) => {
              const href = `/${book.id}/${ch.id}`;
              const row = (
                <span className={`flex items-baseline gap-2 ${ch.partial ? "pl-9 text-[13px] italic" : "text-[15px]"}`}>
                  {!ch.partial && <span className="w-7 shrink-0 text-right tabular-nums">{ch.num}</span>}
                  <span className="min-w-0 truncate">{ch.title}</span>
                  {ch.rendered && minutes?.[ch.id] != null && (
                    <span className="shrink-0 font-sans text-[10px] text-emerald-500">♪ {minutes[ch.id]} min</span>
                  )}
                  <span className="mb-1 min-w-4 flex-1 border-b border-dotted border-neutral-700" />
                  <span className="shrink-0 tabular-nums text-neutral-500">
                    {book.page_offset != null ? ch.pdf_start - book.page_offset : ch.pdf_start}
                  </span>
                </span>
              );
              return (
                <li key={ch.id}>
                  {ch.rendered ? (
                    <Link
                      href={href}
                      className={`block rounded px-1 transition hover:bg-neutral-900 ${
                        pathname === href ? "text-emerald-300" : "text-neutral-100"
                      }`}
                    >
                      {row}
                    </Link>
                  ) : (
                    <div className="px-1 text-neutral-600">{row}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <p className="mt-4 font-sans text-[11px] text-neutral-600">
        {book.page_offset != null ? "Page numbers are the book's printed pages." : "Page numbers are PDF pages."}{" "}
        ♪ = narrated; greyed entries aren&apos;t narrated yet.
      </p>
    </div>
  );
}

export default function BookContents(props: {
  book: Book;
  variant: Variant;
  minutes?: Record<string, number>;
  onPick?: () => void;
}) {
  const { mode } = useListMode();
  return mode === "exam" ? <ExamView {...props} /> : <TextbookView {...props} />;
}
