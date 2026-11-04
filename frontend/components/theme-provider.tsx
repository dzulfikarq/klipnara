"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "dark" | "light";
const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    if (document.documentElement.dataset.theme === "light") setTheme("light");
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("klipnara-theme", next); } catch { /* Theme remains active for this page load. */ }
    setTheme(next);
  };

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("ThemeToggle must be used within ThemeProvider");
  const { theme, toggleTheme } = context;
  const Icon = theme === "dark" ? Sun : Moon;
  const next = theme === "dark" ? "terang" : "gelap";

  return <button type="button" className={`theme-toggle${compact ? " theme-toggle-compact" : ""}`} onClick={toggleTheme} aria-label={`Aktifkan tema ${next}`} title={`Aktifkan tema ${next}`}><Icon size={16}/>{!compact && <span>{theme === "dark" ? "Gelap" : "Terang"}</span>}</button>;
}
