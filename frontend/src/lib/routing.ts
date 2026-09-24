/**
 * URL ↔ workspace route mapping (History API; no router dependency).
 *
 *   /imaging            Imaging workspace (default: "/")
 *   /reports            Reports workspace
 *   /reports/:id        Reports workspace with a report selected
 *   /clinical/:id       Clinical View for a report
 *   /overview /search /timeline /templates /privacy /storage /settings
 *
 * Paths above are relative to the app's base path (Vite `base`, e.g. "/HoloMed/" on the GitHub
 * Pages project site). `appPathname` / `appUrl` convert between browser pathnames and app paths so
 * the app never navigates outside its base path.
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


/** Normalise a base path to "/" or "/segment/…/" (leading and trailing slash). */
function normaliseBase(base: string): string {
  const trimmed = base.replace(/^\/+|\/+$/g, '');
  return trimmed ? `/${trimmed}/` : '/';
}

/** Browser pathname → app path ("/HoloMed/imaging" → "/imaging" for base "/HoloMed/"). */
export function appPathname(pathname: string, base = '/'): string {
  const prefix = normaliseBase(base);
  if (prefix === '/') return pathname || '/';
  const bare = prefix.slice(0, -1);                        // "/HoloMed"
  if (pathname === bare || pathname === prefix) return '/';
  if (pathname.startsWith(prefix)) return pathname.slice(bare.length);
  return pathname;
}

/** App path → browser URL under the base path ("/imaging" → "/HoloMed/imaging"). */
export function appUrl(path: string, base = '/'): string {
  const prefix = normaliseBase(base);
  return prefix === '/' ? path : prefix.slice(0, -1) + path;
}

/** Route of a browser pathname under the base path. */
export function routeFromLocation(pathname: string, base = '/'): AppRoute {
  return parseRoute(appPathname(pathname, base));
}

/** Browser URL of a route under the base path. */
export function urlForRoute(route: AppRoute, base = '/'): string {
  return appUrl(formatRoute(route), base);
}

// ── Route restoration across the Google sign-in redirect ─────────────────────
// Google sign-in leaves the app (backend → Google → backend callback) and the backend always
// returns to GOOGLE_POST_LOGIN_URL (the app root). The requested workspace path is remembered in
// sessionStorage (this tab only; an app path, never a token) and restored on return.

export const POST_LOGIN_PATH_KEY = 'holomed.postLoginPath';

type PathStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** Remember the app path to return to after an off-site sign-in. */
export function rememberPostLoginPath(appPath: string, store: PathStore): void {
  try {
    store.setItem(POST_LOGIN_PATH_KEY, formatRoute(parseRoute(appPath)));
  } catch {
    // storage unavailable (private mode, blocked) — the default route is used instead
  }
}

/**
 * The app path to open on this page load: a remembered post-login path (read once, then removed)
 * when the browser landed on the app root, otherwise the current path. Deep links always win.
 * Only known workspace paths are returned (parseRoute/formatRoute), never arbitrary URLs.
 */
export function takeEntryPath(currentAppPath: string, store: PathStore | null): string {
  let remembered: string | null = null;
  try {
    remembered = store?.getItem(POST_LOGIN_PATH_KEY) ?? null;
    store?.removeItem(POST_LOGIN_PATH_KEY);
  } catch {
    remembered = null;
  }
  const atRoot = currentAppPath === '/' || currentAppPath === '';
  return atRoot && remembered ? formatRoute(parseRoute(remembered)) : currentAppPath;
}
