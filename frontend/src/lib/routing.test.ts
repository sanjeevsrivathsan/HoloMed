import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_ROUTE, POST_LOGIN_PATH_KEY, appPathname, formatRoute, parseRoute, rememberPostLoginPath, routeFromLocation,
  sameRoute, takeEntryPath, urlForRoute,
} from './routing.ts';

test('paths map to workspace routes and back', () => {
  const cases: [string, ReturnType<typeof parseRoute>][] = [
    ['/', DEFAULT_ROUTE],
    ['/imaging', { page: 'imaging', reportId: null }],
    ['/reports', { page: 'reports', reportId: null }],
    ['/reports/42', { page: 'reports', reportId: '42' }],
    ['/clinical/7', { page: 'clinical', reportId: '7' }],
    ['/overview', { page: 'dashboard', reportId: null }],
    ['/search', { page: 'search', reportId: null }],
    ['/timeline', { page: 'timeline', reportId: null }],
    ['/settings', { page: 'settings', reportId: null }],
  ];
  for (const [path, route] of cases) {
    assert.deepEqual(parseRoute(path), route, path);
  }
  assert.equal(formatRoute({ page: 'reports', reportId: '42' }), '/reports/42');
  assert.equal(formatRoute({ page: 'dashboard', reportId: null }), '/overview');
  assert.equal(formatRoute({ page: 'timeline', reportId: '9' }), '/timeline');   // ids only for report pages
});

test('unknown or malformed paths fall back safely', () => {
  assert.deepEqual(parseRoute('/nope'), DEFAULT_ROUTE);
  assert.deepEqual(parseRoute('/reports/abc'), { page: 'reports', reportId: null });
  assert.deepEqual(parseRoute('/reports/1/extra'), { page: 'reports', reportId: '1' });
  assert.deepEqual(parseRoute('/REPORTS/3'), { page: 'reports', reportId: '3' });
  assert.ok(sameRoute(parseRoute('/'), parseRoute('/imaging')));
});

test('routes live under the GitHub Pages base path', () => {
  const base = '/HoloMed/';
  assert.equal(appPathname('/HoloMed/', base), '/');
  assert.equal(appPathname('/HoloMed', base), '/');
  assert.equal(appPathname('/HoloMed/imaging', base), '/imaging');
  assert.equal(appPathname('/HoloMed/reports/42', base), '/reports/42');
  assert.deepEqual(routeFromLocation('/HoloMed/', base), DEFAULT_ROUTE);
  assert.deepEqual(routeFromLocation('/HoloMed/patients', base), DEFAULT_ROUTE);   // unknown → default
  assert.deepEqual(routeFromLocation('/HoloMed/reports/42', base), { page: 'reports', reportId: '42' });
  // Navigation never leaves the base path ("/HoloMed/" → "/HoloMed/imaging", not "/imaging").
  assert.equal(urlForRoute(DEFAULT_ROUTE, base), '/HoloMed/imaging');
  assert.equal(urlForRoute({ page: 'reports', reportId: '7' }, base), '/HoloMed/reports/7');
  assert.equal(urlForRoute({ page: 'dashboard', reportId: null }, 'HoloMed'), '/HoloMed/overview');
});

test('root base path (development) keeps plain paths', () => {
  assert.equal(appPathname('/imaging'), '/imaging');
  assert.equal(appPathname('/', '/'), '/');
  assert.equal(urlForRoute({ page: 'reports', reportId: null }, '/'), '/reports');
  assert.deepEqual(routeFromLocation('/clinical/3', '/'), { page: 'clinical', reportId: '3' });
});

function memoryStore() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => { data.set(k, v); },
    removeItem: (k: string) => { data.delete(k); },
  };
}

test('the requested workspace is restored after Google sign-in returns to the app root', () => {
  const store = memoryStore();
  rememberPostLoginPath('/reports/5', store);
  assert.equal(store.data.get(POST_LOGIN_PATH_KEY), '/reports/5');
  assert.equal(takeEntryPath('/', store), '/reports/5');
  assert.equal(store.data.has(POST_LOGIN_PATH_KEY), false);          // single use
  assert.equal(takeEntryPath('/', store), '/');
});

test('deep links win over a remembered path, and only workspace paths are remembered', () => {
  const store = memoryStore();
  rememberPostLoginPath('/settings', store);
  assert.equal(takeEntryPath('/imaging', store), '/imaging');
  assert.equal(store.data.has(POST_LOGIN_PATH_KEY), false);
  rememberPostLoginPath('//evil.example/x', store);                  // not a workspace path
  assert.equal(takeEntryPath('/', store), '/imaging');
  assert.equal(takeEntryPath('/', null), '/');
  const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); },
    removeItem: () => {} };
  rememberPostLoginPath('/reports', broken);
  assert.equal(takeEntryPath('/', broken), '/');
});
