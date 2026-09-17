import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { startGoogleAuth } from './googleAuth.ts';

test('sign-in navigates the current tab to the backend endpoint', () => {
  const calls: string[] = [];
  startGoogleAuth('/api/v1/auth/google', { replace: (url) => calls.push(url) });
  assert.deepEqual(calls, ['/api/v1/auth/google']);
});

test('linking uses the link endpoint, without query parameters', () => {
  const calls: string[] = [];
  startGoogleAuth('/api/v1/auth/google/link', { replace: (url) => calls.push(url) });
  assert.deepEqual(calls, ['/api/v1/auth/google/link']);
});

test('sign-in never opens a window, tab or popup', () => {
  // A stray window.open / assign would show the workspace in a popup-sized window (regression guard).
  const forbidden = ['window.open', 'open(', '_blank', '_new', 'width=', 'height=', 'assign(', 'iframe', 'BroadcastChannel'];
  const code = readFileSync(new URL('./googleAuth.ts', import.meta.url), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')       // comments describe the rule; only the code must obey it
    .replace(/\/\/.*$/gm, '');
  for (const token of forbidden) assert.equal(code.includes(token), false, token);

  const nav = { replace: () => {}, open: () => assert.fail('window.open must not be called') };
  startGoogleAuth('/api/v1/auth/google', nav);
});
