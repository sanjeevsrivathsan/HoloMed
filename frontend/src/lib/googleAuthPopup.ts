/**
 * Google sign-in in a popup window.
 *
 * Running the OAuth redirects (HoloMed → Google → callback) in a popup keeps Google's pages out of
 * the main window's history, so the browser Back button stays inside HoloMed after signing in.
 * The popup ends on `/?auth_popup=1&…`, which only *signals* the main window (BroadcastChannel and,
 * when the opener is still reachable, postMessage) and closes. The main window then re-checks the
 * session with GET /api/v1/auth/me — the signal itself carries no authority.
 * If the browser blocks the popup, the classic full-page redirect is used instead.
 */
import { authResultFrom } from './routing';

export const AUTH_CHANNEL = 'holomed-auth';
export const AUTH_MESSAGE_TYPE = 'holomed-google-auth';
const POPUP_NAME = 'holomed-google-auth';

export interface AuthPopupResult {
  type: typeof AUTH_MESSAGE_TYPE;
  error: string | null;
  notice: string | null;
}

export function isAuthPopupResultMessage(data: unknown): data is AuthPopupResult {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  const code = (v: unknown) => v === null || (typeof v === 'string' && /^[a-z_]{1,40}$/.test(v));
  return d.type === AUTH_MESSAGE_TYPE && code(d.error) && code(d.notice);
}

/** Open the Google flow in a popup; falls back to a full-page redirect if the popup is blocked. */
export function startGoogleAuth(path: '/api/v1/auth/google' | '/api/v1/auth/google/link'): 'popup' | 'redirect' {
  const width = 520;
  const height = 680;
  const left = Math.max(0, Math.round(window.screenX + (window.outerWidth - width) / 2));
  const top = Math.max(0, Math.round(window.screenY + (window.outerHeight - height) / 2));
  const popup = window.open(`${path}?popup=1`, POPUP_NAME,
    `popup=yes,width=${width},height=${height},left=${left},top=${top}`);
  if (!popup) {
    window.location.assign(path);
    return 'redirect';
  }
  popup.focus();
  return 'popup';
}

/** Subscribe to popup results (BroadcastChannel + same-origin postMessage). Returns an unsubscribe. */
export function onGoogleAuthResult(handler: (result: AuthPopupResult) => void): () => void {
  const deliver = (data: unknown) => { if (isAuthPopupResultMessage(data)) handler(data); };
  const onMessage = (event: MessageEvent) => {
    if (event.origin === window.location.origin) deliver(event.data);
  };
  window.addEventListener('message', onMessage);
  let channel: BroadcastChannel | null = null;
  if (typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel(AUTH_CHANNEL);
    channel.onmessage = (event) => deliver(event.data);
  }
  return () => {
    window.removeEventListener('message', onMessage);
    channel?.close();
  };
}

let completed = false;

/** Runs inside the popup on `/?auth_popup=1…`: report the outcome and close. */
export function completeGoogleAuthPopup(): void {
  if (completed) return;          // React StrictMode runs effects twice in development
  completed = true;
  const { error, notice } = authResultFrom(window.location.search);
  const message: AuthPopupResult = { type: AUTH_MESSAGE_TYPE, error, notice };
  try {
    if (typeof BroadcastChannel !== 'undefined') {
      const channel = new BroadcastChannel(AUTH_CHANNEL);
      channel.postMessage(message);
      channel.close();
    }
  } catch { /* ignore */ }
  try {
    window.opener?.postMessage(message, window.location.origin);
  } catch { /* opener may be unreachable after cross-origin navigation */ }
  window.history.replaceState(null, '', window.location.pathname);   // no codes left in the address bar
  window.setTimeout(() => window.close(), 150);
}
