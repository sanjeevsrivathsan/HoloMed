/**
 * Starting Google sign-in.
 *
 * The flow runs in the current tab:
 * HoloMed → Google account chooser → backend callback →
 * back to the app.
 *
 * The backend URL is supplied through VITE_API_BASE_URL in production.
 * Local development can leave it empty and use the Vite proxy.
 *
 * `location.replace` is intentional: the sign-in screen itself does not
 * need its own browser history entry.
 */

/** The part of `window.location` this module needs (injected in tests). */
export interface Navigator {
  replace(url: string): void;
}

export type GoogleAuthPath =
  | '/api/v1/auth/google'
  | '/api/v1/auth/google/link';

// `import.meta.env` is Vite-only; it is undefined under `node --test`, where the base is ''.
const API_BASE =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? '';

/**
 * Navigate this tab to the backend endpoint that starts the Google flow.
 */
export function startGoogleAuth(
  path: GoogleAuthPath,
  navigator: Navigator = window.location,
): void {
  const target = `${API_BASE}${path}`;
  navigator.replace(target);
}
