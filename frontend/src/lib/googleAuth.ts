/**
 * Starting Google sign-in.
 *
 * The flow runs in the **current tab**: HoloMed → Google account chooser → the backend callback →
 * back to the app. No popup, no new tab, no iframe — the authenticated workspace therefore appears
 * in the same window, using the full viewport, like any other HoloMed navigation.
 *
 * `location.replace` is used on purpose: the sign-in screen is not worth a history entry of its own,
 * so after signing in the Back button does not land the user on the page they just left behind.
 * Ordinary SPA navigation elsewhere still uses pushState.
 */

/** The part of `window.location` this module needs (injected in tests). */
export interface Navigator {
  replace(url: string): void;
}

export type GoogleAuthPath = '/api/v1/auth/google' | '/api/v1/auth/google/link';

/** Navigate this tab to the backend endpoint that starts the Google flow. */
export function startGoogleAuth(path: GoogleAuthPath, navigator: Navigator = window.location): void {
  navigator.replace(path);
}
