import type { Metadata } from "next";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Klipnara Studio — AI Video Creator",
  description: "Buat Quick Clip, AI Smart Clip, dan AI Mood Quotes secara lokal.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body><Shell>{children}</Shell></body></html>;
}
