import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { loadLibrary } from "@/lib/data";
import Shell from "@/components/Shell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Learnible",
  description: "Audiobook-style reader with figure cues for textbooks",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const books = await loadLibrary();
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Shell books={books}>{children}</Shell>
      </body>
    </html>
  );
}
