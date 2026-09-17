import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { AuthPopupComplete } from './components/AuthPopupComplete.tsx';
import { isAuthPopupResult } from './lib/routing.ts';
import './index.css';

// The Google sign-in popup ends on "/?auth_popup=1…": report the outcome instead of loading the app.
const popupResult = isAuthPopupResult(window.location.search);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {popupResult ? <AuthPopupComplete /> : <App />}
  </StrictMode>
);
