/**
 * Google sign-in outcome messages.
 *
 * The backend redirects back with `?auth_error=<code>` or `?auth_notice=<code>`
 * (short codes only — never tokens). These are read once, removed from the
 * address bar, and shown as friendly text.
 */

export interface AuthRedirectMessage {
  kind: 'error' | 'notice';
  code: string;
  message: string;
}

const RETRY = 'Google sign-in could not be completed. Please try again.';

const ERRORS: Record<string, string> = {
  google_not_configured: 'Google sign-in is not configured on this server. Use email and password instead.',
  google_cancelled: 'Google sign-in was cancelled.',
  google_failed: RETRY,
  missing_code: RETRY,
  token_exchange_failed: RETRY,
  invalid_state: 'Your Google sign-in attempt expired or could not be verified. Please try again.',
  invalid_id_token: 'Google sign-in could not be verified. Please try again.',
  id_token_expired: 'Your Google sign-in expired. Please try again.',
  email_unverified: 'Your Google account email is not verified. Verify it with Google, or sign in with email and password.',
  account_link_required:
    'An account with this email already exists. Sign in with your password, then link Google from Settings → Profile.',
  google_account_mismatch: 'This email is already linked to a different Google account.',
  google_account_in_use: 'This Google account is already linked to another HoloMed account.',
  email_mismatch: "The Google account's email does not match your HoloMed account email.",
  link_requires_login: 'Sign in to HoloMed first, then link your Google account from Settings → Profile.',
  account_disabled: 'This account is disabled.',
};

const NOTICES: Record<string, string> = {
  google_linked: 'Google account linked. You can now also sign in with Google.',
};

let consumed: { value: AuthRedirectMessage | null } | null = null;

/**
 * Read and remove auth_error / auth_notice from the current URL.
 * Idempotent per page load (React StrictMode runs state initializers twice).
 */
export function consumeAuthRedirectMessage(): AuthRedirectMessage | null {
  if (consumed) return consumed.value;
  consumed = { value: readAndStrip() };
  return consumed.value;
}

function readAndStrip(): AuthRedirectMessage | null {
  if (typeof window === 'undefined') return null;
  const url = new URL(window.location.href);
  const error = url.searchParams.get('auth_error');
  const notice = url.searchParams.get('auth_notice');
  if (!error && !notice) return null;
  url.searchParams.delete('auth_error');
  url.searchParams.delete('auth_notice');
  window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
  if (error) {
    return { kind: 'error', code: error, message: ERRORS[error] ?? RETRY };
  }
  const code = notice as string;
  return NOTICES[code] ? { kind: 'notice', code, message: NOTICES[code] } : null;
}

/** Message for a Google sign-in outcome code. */
export function authMessageFor(error: string | null, notice: string | null): AuthRedirectMessage | null {
  if (error) return { kind: 'error', code: error, message: ERRORS[error] ?? RETRY };
  if (notice && NOTICES[notice]) return { kind: 'notice', code: notice, message: NOTICES[notice] };
  return null;
}
