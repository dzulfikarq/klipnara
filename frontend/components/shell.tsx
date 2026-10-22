"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Clapperboard, Film, FolderOpen, Gauge, Home, Scissors, Settings2 } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { API } from "@/lib/api";

const nav = [
  { href: "/", label: "Ringkasan", icon: Home },
  { href: "/create", label: "Buat Klip AI", icon: Scissors },
  { href: "/library", label: "Video Library", icon: FolderOpen },
  { href: "/clips", label: "Clip Library", icon: Film },
  { href: "/settings", label: "Pengaturan", icon: Settings2 },
];

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [online, setOnline] = useState(false);
  useEffect(() => {
    fetch(`${API}/api/health`).then((res) => setOnline(res.ok)).catch(() => setOnline(false));
  }, [path]);
  const current = nav.find((item) => item.href === path)?.label || (path.startsWith("/sources/") ? "Review kandidat" : "Editor klip");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark"><Clapperboard size={21} strokeWidth={2.1} /></span>
          <span>Klipnara<small>AI VIDEO CLIPPER &amp; PUBLISHER</small></span>
        </Link>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="side-nav">
          {nav.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`);
            return <Link key={href} href={href} className={`nav-link ${active ? "active" : ""}`}><Icon size={18} strokeWidth={1.8} /><span>{label}</span>{href === "/create" && <span className="nav-plus">+</span>}</Link>;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card"><div className="local-card-icon"><Gauge size={17} /></div><div><strong>Local workspace</strong><span>File tetap di perangkat ini</span></div></div>
          <div className="sidebar-status"><i className={online ? "status-dot" : "status-dot offline"} />{online ? "Backend terhubung" : "Backend offline"}</div>
          <div className="sidebar-footer">KLIPNARA <span>V1.0</span></div>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar"><div className="mobile-brand"><Clapperboard size={18} /> Klipnara</div><div className="breadcrumb">Workspace <span>/</span> <strong>{current}</strong></div><div className="topbar-right"><span className="privacy-pill"><i />LOCAL-FIRST</span><Link href="/settings" aria-label="Pengaturan" className="avatar">K</Link></div></header>
        <main className="main-content">{children}</main>
      </div>
    </div>
  );
}
