import type { Metadata } from "next";
import localFont from "next/font/local";
import { Shell } from "@/components/shell";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";
import "./theme.css";

const inter = localFont({
  src: "./fonts/InterVariable.woff2",
  variable: "--font-inter",
  display: "swap",
  weight: "100 900",
});

const themeInitScript = `try{const theme=localStorage.getItem("klipnara-theme");document.documentElement.dataset.theme=theme==="light"?"light":"dark"}catch{document.documentElement.dataset.theme="dark"}`;

export const metadata: Metadata = {
  title: "Klipnara — AI Video Studio",
  description: "Buat Quick Clip, AI Smart Clip, dan AI Mood Quotes secara lokal.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id" data-theme="dark" className={inter.variable} suppressHydrationWarning><head><script dangerouslySetInnerHTML={{ __html: themeInitScript }}/></head><body><ThemeProvider><ConfirmProvider><Shell>{children}</Shell></ConfirmProvider></ThemeProvider></body></html>;
}
