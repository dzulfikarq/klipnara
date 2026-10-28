import type { Metadata } from "next";
import { Shell } from "@/components/shell";
import { ConfirmProvider } from "@/components/confirm-dialog";
import "./globals.css";

export const metadata: Metadata = {
  title: "Klipnara — AI Video Studio",
  description: "Buat Quick Clip, AI Smart Clip, dan AI Mood Quotes secara lokal.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body><ConfirmProvider><Shell>{children}</Shell></ConfirmProvider></body></html>;
}
