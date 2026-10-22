import type { Metadata } from "next";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Klipnara — AI Video Clipper & Publisher",
  description: "Dari Video Panjang, Jadi Konten Menarik.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body><Shell>{children}</Shell></body></html>;
}
