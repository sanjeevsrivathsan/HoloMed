import { test } from 'node:test';
import assert from 'node:assert/strict';
import { authResultFrom, DEFAULT_ROUTE, formatRoute, isAuthPopupResult, parseRoute, sameRoute } from './routing.ts';

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

test('Google sign-in popup results are recognised and sanitised', () => {
  assert.equal(isAuthPopupResult('?auth_popup=1&auth_notice=google_linked'), true);
  assert.equal(isAuthPopupResult('?auth_error=google_cancelled'), false);
  assert.deepEqual(authResultFrom('?auth_popup=1&auth_error=google_cancelled'), { error: 'google_cancelled', notice: null });
  assert.deepEqual(authResultFrom('?auth_popup=1&auth_notice=<script>'), { error: null, notice: null });
});
