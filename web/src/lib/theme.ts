import { useEffect, useState } from "react";

// App-wide light/dark theme. The resolved theme lives as `data-theme` on <html>
// — set pre-paint by an inline script in index.html (no flash) and toggled here.
// CSS keys purely on `:root[data-theme="dark"]`; light is the default. Keep the
// storage key in sync with that inline script.
export type Theme = "light" | "dark";

const KEY = "eukahub-theme";
const systemMq = () => window.matchMedia("(prefers-color-scheme: dark)");

/** The user's explicit choice, or null when they've never toggled (= follow system). */
export function getStored(): Theme | null {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" ? v : null;
}

/** The theme to actually render: explicit choice, else the OS preference. */
export function resolveTheme(): Theme {
  return getStored() ?? (systemMq().matches ? "dark" : "light");
}

// Tiny pub/sub so every mounted useTheme() re-renders together on a toggle.
const listeners = new Set<() => void>();

export function setTheme(t: Theme): void {
  localStorage.setItem(KEY, t);
  document.documentElement.dataset.theme = t;
  listeners.forEach((l) => l());
}

export function toggleTheme(): void {
  setTheme(resolveTheme() === "dark" ? "light" : "dark");
}

/** Subscribe to the resolved theme; also follows the OS while no explicit choice is set. */
export function useTheme(): Theme {
  const [theme, setThemeState] = useState<Theme>(resolveTheme);
  useEffect(() => {
    const update = () => setThemeState(resolveTheme());
    listeners.add(update);
    const mq = systemMq();
    const onSystem = () => {
      if (!getStored()) update();
    };
    mq.addEventListener("change", onSystem);
    return () => {
      listeners.delete(update);
      mq.removeEventListener("change", onSystem);
    };
  }, []);
  return theme;
}
