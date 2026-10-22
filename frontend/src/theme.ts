// Theme preference: "light", "dark" or "system" (follows the OS). Stored per
// device in localStorage like the language; applied on <html data-theme> so
// the build-time dark stylesheet (dark-theme.mjs) takes effect.
import {useEffect, useState} from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';
const KEY = 'touchline_theme';
const listeners = new Set<() => void>();
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

export function getThemeChoice(): ThemeChoice {
  const value = localStorage.getItem(KEY);
  return value === 'light' || value === 'dark' ? value : 'system';
}
export function effectiveTheme(choice = getThemeChoice()): 'light' | 'dark' {
  return choice === 'system' ? (media?.matches ? 'dark' : 'light') : choice;
}
export function applyTheme() {
  document.documentElement.dataset.theme = effectiveTheme();
  listeners.forEach((fn) => fn());
}
export function setThemeChoice(choice: ThemeChoice) {
  if (choice === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, choice);
  applyTheme();
}
export function toggleTheme() {
  setThemeChoice(effectiveTheme() === 'dark' ? 'light' : 'dark');
}
media?.addEventListener('change', () => { if (getThemeChoice() === 'system') applyTheme(); });

export function useTheme(): {choice: ThemeChoice; theme: 'light' | 'dark'} {
  const [, setTick] = useState(0);
  useEffect(() => { const fn = () => setTick((n) => n + 1); listeners.add(fn); return () => { listeners.delete(fn); }; }, []);
  return {choice: getThemeChoice(), theme: effectiveTheme()};
}
