"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

// How a book's units are listed: by the course's slide decks ("exam", the
// default) or as the textbook's own contents page ("textbook"). Shared by
// the sidebar and the book page; remembered per browser.
export type ListMode = "exam" | "textbook";

const KEY = "learnible.listMode";
const ModeContext = createContext<{ mode: ListMode; setMode: (m: ListMode) => void }>({
  mode: "exam",
  setMode: () => {},
});

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ListMode>("exam");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time restore after hydration
      if (saved === "exam" || saved === "textbook") setModeState(saved);
    } catch {
      // storage unavailable (private mode etc.): keep the default
    }
  }, []);
  const setMode = (m: ListMode) => {
    setModeState(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      // ignore
    }
  };
  return <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>;
}

export function useListMode() {
  return useContext(ModeContext);
}

export function ModeToggle({ className = "" }: { className?: string }) {
  const { mode, setMode } = useListMode();
  const btn = (m: ListMode, label: string) => (
    <button
      onClick={() => setMode(m)}
      aria-pressed={mode === m}
      className={`flex-1 rounded-md px-2.5 py-1 text-xs transition ${
        mode === m ? "bg-neutral-700 text-white" : "text-neutral-400 hover:text-neutral-200"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className={`flex gap-1 rounded-lg bg-neutral-900 p-1 ${className}`}>
      {btn("exam", "Exam")}
      {btn("textbook", "Textbook")}
    </div>
  );
}
