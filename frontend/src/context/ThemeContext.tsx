import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { AppTheme, ImagingTheme } from '@/lib/types';

interface ThemeContextValue {
  appTheme: AppTheme;
  imagingTheme: ImagingTheme;
  resolvedTheme: 'light' | 'dark';
  resolvedImagingTheme: 'light' | 'dark';
  setAppTheme: (t: AppTheme) => void;
  setImagingTheme: (t: ImagingTheme) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

function getSystemPreference(): 'light' | 'dark' {
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return 'light';
}

function applyTheme(dark: boolean) {
  const root = document.documentElement;
  if (dark) root.classList.add('dark');
  else root.classList.remove('dark');
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [appTheme, setAppThemeState] = useState<AppTheme>(() => {
    return (localStorage.getItem('holomed-app-theme') as AppTheme) || 'system';
  });
  const [imagingTheme, setImagingThemeState] = useState<ImagingTheme>(() => {
    return (localStorage.getItem('holomed-imaging-theme') as ImagingTheme) || 'follow';
  });
  const [systemDark, setSystemDark] = useState<'light' | 'dark'>(getSystemPreference());

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches ? 'dark' : 'light');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const resolvedTheme: 'light' | 'dark' =
    appTheme === 'system' ? systemDark : appTheme;
  const resolvedImagingTheme: 'light' | 'dark' =
    imagingTheme === 'follow' ? resolvedTheme : imagingTheme;

  useEffect(() => {
    applyTheme(resolvedTheme === 'dark');
  }, [resolvedTheme]);

  const setAppTheme = (t: AppTheme) => {
    setAppThemeState(t);
    localStorage.setItem('holomed-app-theme', t);
  };
  const setImagingTheme = (t: ImagingTheme) => {
    setImagingThemeState(t);
    localStorage.setItem('holomed-imaging-theme', t);
  };

  return (
    <ThemeContext.Provider
      value={{ appTheme, imagingTheme, resolvedTheme, resolvedImagingTheme, setAppTheme, setImagingTheme }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
