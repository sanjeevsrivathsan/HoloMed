import { Bell, ChevronDown, User, LogOut, Stethoscope, Shield, Menu } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { ThemeToggle } from './ThemeControls';
import type { PageKey } from './Sidebar';
import { useAuth } from '@/context/AuthContext';
import { PatientSelector } from './PatientSelector';
import type { Role } from '@/lib/types';

const pageTitles: Record<PageKey, string> = {
  dashboard: 'Dashboard',
  reports: 'Reports',
  search: 'Health Search',
  timeline: 'Health Timeline',
  imaging: 'Imaging',
  templates: 'Templates',
  clinical: 'Clinical View',
  privacy: 'Privacy Center',
  storage: 'Storage & Delivery',
  settings: 'Settings',
};

interface TopbarProps {
  currentPage: PageKey;
  onMobileMenu: () => void;
}

export function Topbar({ currentPage, onMobileMenu }: TopbarProps) {
  const { user, signOut, role, switchRole } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const notifRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false);
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const roles: { value: Role; label: string; icon: typeof User }[] = [
    { value: 'patient', label: 'Patient', icon: User },
    { value: 'clinician', label: 'Clinician', icon: Stethoscope },
    { value: 'administrator', label: 'Administrator', icon: Shield },
  ];

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-neutral-200 bg-white/80 px-4 backdrop-blur-md dark:border-neutral-800 dark:bg-neutral-900/80">
      <div className="flex items-center gap-3">
        <button
          onClick={onMobileMenu}
          className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800 lg:hidden"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
          {pageTitles[currentPage]}
        </h1>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        <div className="hidden sm:flex items-center gap-2">
          <PatientSelector />
        </div>

        <ThemeToggle />

        <div className="relative" ref={notifRef}>
          <button
            onClick={() => setNotifOpen((v) => !v)}
            className="relative rounded-lg p-2 text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
            aria-label="Notifications"
          >
            <Bell className="h-4.5 w-4.5" />
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-teal-500 ring-2 ring-white dark:ring-neutral-900" />
          </button>
          {notifOpen && (
            <div className="absolute right-0 top-full mt-2 w-72 rounded-xl border border-neutral-200 bg-white p-2 shadow-xl dark:border-neutral-800 dark:bg-neutral-900 animate-fade-in">
              <p className="px-2 py-1.5 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Notifications</p>
              <div className="space-y-1">
                <div className="rounded-lg p-2.5 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                  <p className="text-xs font-medium text-neutral-700 dark:text-neutral-300">New report ready</p>
                  <p className="text-xs text-neutral-400">Complete Blood Count — processed</p>
                </div>
                <div className="rounded-lg p-2.5 hover:bg-neutral-50 dark:hover:bg-neutral-800">
                  <p className="text-xs font-medium text-neutral-700 dark:text-neutral-300">Consent expiring</p>
                  <p className="text-xs text-neutral-400">Cardiology consent expires in 3 months</p>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="relative" ref={profileRef}>
          <button
            onClick={() => setProfileOpen((v) => !v)}
            className="flex items-center gap-2 rounded-lg p-1 hover:bg-neutral-100 dark:hover:bg-neutral-800"
            aria-label="User profile"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-100 text-sm font-semibold text-teal-700 dark:bg-teal-900 dark:text-teal-300">
              {user?.displayName?.charAt(0) || 'D'}
            </div>
            <ChevronDown className="hidden sm:block h-4 w-4 text-neutral-400" />
          </button>
          {profileOpen && (
            <div className="absolute right-0 top-full mt-2 w-64 rounded-xl border border-neutral-200 bg-white p-2 shadow-xl dark:border-neutral-800 dark:bg-neutral-900 animate-fade-in">
              <div className="border-b border-neutral-100 px-2 py-2 dark:border-neutral-800">
                <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{user?.displayName}</p>
                <p className="text-xs text-neutral-400">{user?.email}</p>
              </div>
              <div className="py-1.5">
                <p className="px-2 py-1 text-xs font-medium text-neutral-400">Active Role</p>
                <div className="mt-1 space-y-0.5">
                  {roles.map(({ value, label, icon: Icon }) => (
                    <button
                      key={value}
                      onClick={() => switchRole(value)}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs ${
                        role === value
                          ? 'bg-teal-50 text-teal-700 dark:bg-teal-950 dark:text-teal-300'
                          : 'text-neutral-600 hover:bg-neutral-50 dark:text-neutral-400 dark:hover:bg-neutral-800'
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="border-t border-neutral-100 pt-1.5 dark:border-neutral-800">
                <button
                  onClick={signOut}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-error-600 hover:bg-error-50 dark:hover:bg-error-700/10"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
