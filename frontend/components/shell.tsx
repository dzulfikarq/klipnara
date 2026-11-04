"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, Film, FolderOpen, Gauge, Home, Layers, MoreHorizontal, Scissors, Settings2, UsersRound } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { API } from "@/lib/api";
import { ThemeToggle } from "@/components/theme-provider";

const sections = [
  { label: "WORKSPACE", items: [
    { href: "/", label: "Ringkasan", icon: Home, mobile: "main" },
    { href: "/create", label: "Buat Video", icon: Scissors, mobile: "main" },
    { href: "/clips", label: "Clip Library", icon: Film, mobile: "main" },
    { href: "/library", label: "Asset Library", icon: FolderOpen, mobile: "more" },
    { href: "/batches", label: "Batch Creator", icon: Layers, mobile: "more" },
  ] },
  { label: "DISTRIBUSI", items: [
    { href: "/publishing", label: "Publishing Studio", icon: CalendarDays, mobile: "main" },
    { href: "/accounts", label: "Akun Terhubung", icon: UsersRound, mobile: "more" },
  ] },
  { label: "UTILITY", items: [
    { href: "/settings", label: "Pengaturan", icon: Settings2, mobile: "more" },
  ] },
] as const;

const allItems = sections.flatMap((section) => section.items);

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [online, setOnline] = useState(false);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  useEffect(() => {
    fetch(`${API}/api/health`).then((res) => setOnline(res.ok)).catch(() => setOnline(false));
  }, [path]);
  const active = (href: string) => href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`);
  const current = allItems.find((item) => active(item.href))?.label || (path.startsWith("/mood") ? "AI Mood Quotes" : "Review kandidat");
  const moreItems = allItems.filter((item) => item.mobile === "more");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="Klipnara · AI Video Studio"><Image src="/branding/klipnara-mark.png" alt="" width={38} height={38} className="brand-mark"/><span className="brand-wordmark">Klipnara<small>AI VIDEO STUDIO</small></span></Link>
        <nav className="side-nav" aria-label="Navigasi utama">
          {sections.map((section) => <div className="nav-group" key={section.label}>
            <div className="nav-caption">{section.label}</div>
            {section.items.map(({ href, label, icon: Icon, mobile }) => {
              const selected = active(href);
              return <Link key={href} href={href} aria-current={selected ? "page" : undefined} onClick={() => setMobileMoreOpen(false)} className={`nav-link${selected ? " active" : ""}${mobile === "more" ? " mobile-nav-extra" : ""}`}><Icon size={19} strokeWidth={1.8}/><span className="nav-label-desktop">{label}</span><span className="nav-label-mobile">{href === "/publishing" ? "Publish" : label}</span>{href === "/create" && <span className="nav-plus">+</span>}</Link>;
            })}
          </div>)}
          <button type="button" className={`mobile-more-button ${mobileMoreOpen || moreItems.some((item) => active(item.href)) ? "active" : ""}`} aria-expanded={mobileMoreOpen} aria-controls="mobile-more-menu" onClick={() => setMobileMoreOpen((open) => !open)}><MoreHorizontal size={19} strokeWidth={1.8}/><span>Lainnya</span></button>
        </nav>
        <nav id="mobile-more-menu" className="mobile-more-menu" aria-label="Navigasi lainnya" hidden={!mobileMoreOpen}>
          {moreItems.map(({ href, label, icon: Icon }) => {
            const selected = active(href);
            return <Link key={href} href={href} aria-current={selected ? "page" : undefined} onClick={() => setMobileMoreOpen(false)} className={selected ? "active" : ""}><Icon size={17}/><span>{label}</span></Link>;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card"><div className="local-card-icon"><Gauge size={17}/></div><div><strong>Local workspace</strong><span>File tetap di perangkat ini</span></div></div>
          <div className="sidebar-status"><i className={online ? "status-dot" : "status-dot offline"}/>{online ? "Backend terhubung" : "Backend offline"}</div>
          <div className="sidebar-footer">KLIPNARA <span>V2.11.0</span></div>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar"><div className="topbar-inner"><div className="mobile-brand"><Image src="/branding/klipnara-mark.png" alt="" width={26} height={26}/><span>Klipnara</span></div><div className="breadcrumb">Workspace <span>/</span> <strong>{current}</strong></div><div className="topbar-right"><span className="privacy-pill"><i/>LOCAL-FIRST</span><ThemeToggle compact/><Link href="/settings" aria-label="Pengaturan" className="avatar">K</Link></div></div></header>
        <main className="main-content">{children}</main>
      </div>
    </div>
  );
}
