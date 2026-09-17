/**
 * URL ↔ workspace route mapping (History API; no router dependency).
 *
 *   /imaging            Imaging workspace (default: "/")
 *   /reports            Reports workspace
 *   /reports/:id        Reports workspace with a report selected
 *   /clinical/:id       Clinical View for a report
 *   /overview /search /timeline /templates /privacy /storage /settings
 *
 * Kept free of path aliases so it runs under `node --test`.
 */

export type RoutePage =
  | 'imaging' | 'reports' | 'clinical' | 'dashboard' | 'search' | 'timeline'
  | 'templates' | 'privacy' | 'storage' | 'settings';

export interface AppRoute {
  page: RoutePage;
  reportId: string | null;
}

const PAGE_PATHS: Record<RoutePage, string> = {
  imaging: '/imaging',
  reports: '/reports',
  clinical: '/clinical',
  dashboard: '/overview',
  search: '/search',
  timeline: '/timeline',
  templates: '/templates',
  privacy: '/privacy',
  storage: '/storage',
  settings: '/settings',
};

const PATH_PAGES = Object.fromEntries(Object.entries(PAGE_PATHS).map(([page, path]) => [path.slice(1), page])) as
  Record<string, RoutePage>;

export const DEFAULT_ROUTE: AppRoute = { page: 'imaging', reportId: null };

/** Parse a pathname; unknown paths fall back to the default workspace. */
export function parseRoute(pathname: string): AppRoute {
  const parts = pathname.split('/').filter(Boolean).map(decodeURIComponent);
  if (parts.length === 0) return DEFAULT_ROUTE;
  const page = PATH_PAGES[parts[0].toLowerCase()];
  if (!page) return DEFAULT_ROUTE;
  const id = parts[1] && /^\d+$/.test(parts[1]) ? parts[1] : null;
  if (page === 'reports' || page === 'clinical') return { page, reportId: id };
  return { page, reportId: null };
}

export function formatRoute(route: AppRoute): string {
  const base = PAGE_PATHS[route.page];
  if ((route.page === 'reports' || route.page === 'clinical') && route.reportId) {
    return `${base}/${encodeURIComponent(route.reportId)}`;
  }
  return base;
}

export function sameRoute(a: AppRoute, b: AppRoute): boolean {
  return formatRoute(a) === formatRoute(b);
}

/**
 * Query parameters that belong to the Google sign-in hand-off, never part of an app route.
 * The popup result page is recognised by `auth_popup=1`.
 */
export function isAuthPopupResult(search: string): boolean {
  return new URLSearchParams(search).get('auth_popup') === '1';
}

export function authResultFrom(search: string): { error: string | null; notice: string | null } {
  const params = new URLSearchParams(search);
  const clean = (v: string | null) => (v && /^[a-z_]{1,40}$/.test(v) ? v : null);
  return { error: clean(params.get('auth_error')), notice: clean(params.get('auth_notice')) };
}
