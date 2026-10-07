// "Exam mode" grouping: a course's slide decks, each listing the narrated
// units (catalog ids) that cover it, in study order. Deck titles match the
// CS F372 slide files ("8 - Intro to Threads and Concurrency.pdf", ...).
// A deck with no units has no OSTEP reading.

export interface Deck {
  num: number;
  title: string;
  units: string[];
}

export interface ExamPlan {
  course: string;
  decks: Deck[];
}

export const EXAM_PLANS: Record<string, ExamPlan> = {
  ostep: {
    course: "CS F372 · Operating Systems midsem",
    decks: [
      { num: 1, title: "Course Outline", units: [] },
      // The I/O material (devices, polling, DMA, interrupts) is in deck 2, not 3.
      { num: 2, title: "Intro to OS", units: ["ch02-s1-3", "ch36-s1-7"] },
      { num: 3, title: "Booting", units: [] },
      { num: 4, title: "Processes", units: ["ch04"] },
      { num: 5, title: "Processes System Calls", units: ["ch05"] },
      { num: 6, title: "Process Switching", units: ["ch06-s1-3"] },
      { num: 7, title: "CPU Scheduling", units: ["ch07", "ch08"] },
      { num: 8, title: "Intro to Threads and Concurrency", units: ["ch26", "ch27", "ch28-s1-2", "ch31-s1-2", "ch32-deadlock"] },
      { num: 9, title: "Virtual Memory", units: ["ch13", "ch15", "ch16", "ch23-s3"] },
      { num: 10, title: "Memory Syscalls and Free List", units: ["ch14", "ch17"] },
      { num: 11, title: "Paging", units: ["ch18", "ch19-s1-5", "ch20-s1-4"] },
      { num: 12, title: "Demand Paging", units: ["ch21", "ch22"] },
    ],
  },
};
