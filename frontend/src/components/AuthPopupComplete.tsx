import { useEffect, useState } from 'react';
import { completeGoogleAuthPopup } from '@/lib/googleAuthPopup';
import { authResultFrom } from '@/lib/routing';

/** Minimal page shown inside the Google sign-in popup while it hands the result back and closes. */
export function AuthPopupComplete() {
  const [failed] = useState(() => authResultFrom(window.location.search).error !== null);
  useEffect(() => { completeGoogleAuthPopup(); }, []);
  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-50 p-6 text-center dark:bg-neutral-950" data-testid="auth-popup-complete">
      <div>
        <p className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          {failed ? 'Google sign-in did not complete.' : 'Google sign-in finished.'}
        </p>
        <p className="mt-1 text-xs text-neutral-500">You can close this window and return to HoloMed.</p>
      </div>
    </main>
  );
}
