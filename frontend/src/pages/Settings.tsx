import { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Monitor, Sun, Moon, ScanLine, Cpu, Bell, User, Lock, RefreshCw } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { useTheme } from '@/context/ThemeContext';
import { useAuth } from '@/context/AuthContext';
import type { AppTheme, ImagingTheme } from '@/lib/types';
import { api } from '@/lib/api';

export function Settings() {
  const { appTheme, setAppTheme, imagingTheme, setImagingTheme } = useTheme();
  const { user, role, switchRole } = useAuth();
  const [notifEmail, setNotifEmail] = useState(true);
  const [notifPush, setNotifPush] = useState(false);
  const [notifSummary, setNotifSummary] = useState(true);
  
  const [ollamaConfig, setOllamaConfig] = useState<{baseUrl: string, model: string, available: boolean} | null>(null);
  const [testingOllama, setTestingOllama] = useState(false);

  useEffect(() => {
    fetchOllamaConfig();
  }, []);

  const fetchOllamaConfig = async () => {
    setTestingOllama(true);
    try {
      const config = await api.get<{baseUrl: string, model: string, available: boolean}>('/api/v1/ai/ollama/config');
      setOllamaConfig(config);
    } catch (err) {
      console.error('Failed to fetch Ollama config', err);
      setOllamaConfig({ baseUrl: 'Error', model: 'Error', available: false });
    } finally {
      setTestingOllama(false);
    }
  };

  const appThemeOptions: { value: AppTheme; label: string; icon: typeof Sun }[] = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
  ];

  const imagingThemeOptions: { value: ImagingTheme; label: string; icon: typeof Sun }[] = [
    { value: 'follow', label: 'Follow Application', icon: Monitor },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'light', label: 'Light', icon: Sun },
  ];

  return (
    <div className="space-y-6">
      {/* App Theme */}
      <Card>
        <CardHeader title="App Theme" subtitle="Choose how the application looks" icon={<Monitor className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="grid grid-cols-3 gap-2 max-w-md">
            {appThemeOptions.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                onClick={() => setAppTheme(value)}
                className={`flex flex-col items-center gap-2 rounded-lg border-2 p-4 transition-colors ${
                  appTheme === value
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20'
                    : 'border-neutral-200 hover:border-neutral-300 dark:border-neutral-700'
                }`}
              >
                <Icon className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
                <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">{label}</span>
              </button>
            ))}
          </div>
        </div>
      </Card>

      {/* Imaging Theme */}
      <Card>
        <CardHeader title="Imaging Theme" subtitle="Imaging workspace defaults to dark and has an independent setting" icon={<ScanLine className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="grid grid-cols-3 gap-2 max-w-md">
            {imagingThemeOptions.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                onClick={() => setImagingTheme(value)}
                className={`flex flex-col items-center gap-2 rounded-lg border-2 p-4 transition-colors ${
                  imagingTheme === value
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20'
                    : 'border-neutral-200 hover:border-neutral-300 dark:border-neutral-700'
                }`}
              >
                <Icon className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
                <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">{label}</span>
              </button>
            ))}
          </div>
        </div>
      </Card>

      {/* Local Ollama Configuration */}
      <Card>
        <CardHeader title="Local AI · Ollama" subtitle="Local runtime configuration — no secrets exposed" icon={<Cpu className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div>
                <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Base URL</p>
                <p className="text-sm text-neutral-900 dark:text-neutral-100 font-mono">
                  {ollamaConfig ? ollamaConfig.baseUrl : 'Loading...'}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div>
                <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Configured Model</p>
                <p className="text-sm text-neutral-900 dark:text-neutral-100 font-mono">
                  {ollamaConfig ? ollamaConfig.model : 'Loading...'}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div>
                <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Status</p>
                <div className="mt-1">
                  {!ollamaConfig ? (
                    <StatusBadge variant="neutral">Checking...</StatusBadge>
                  ) : (
                    <StatusBadge variant={ollamaConfig.available ? 'success' : 'error'} pulse={ollamaConfig.available}>
                      {ollamaConfig.available ? 'Running' : 'Not running or model missing'}
                    </StatusBadge>
                  )}
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={fetchOllamaConfig} disabled={testingOllama}>
                {testingOllama ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : null}
                {testingOllama ? 'Testing...' : 'Test Connection'}
              </Button>
            </div>
            <div className="flex items-start gap-2 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/50">
              <Lock className="h-4 w-4 shrink-0 text-neutral-400" />
              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                API keys and secrets are never exposed in the browser. Configuration is managed server-side.
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* Notification Preferences */}
      <Card>
        <CardHeader title="Notification Preferences" icon={<Bell className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="space-y-3">
            <label className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div>
                <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">Email notifications</p>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">Receive updates when reports are processed</p>
              </div>
              <input type="checkbox" checked={notifEmail} onChange={(e) => setNotifEmail(e.target.checked)} className="h-4 w-4 rounded border-neutral-300 text-teal-600 focus:ring-teal-500" />
            </label>
            <label className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div>
                <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">Push notifications</p>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">Browser push for urgent findings</p>
              </div>
              <input type="checkbox" checked={notifPush} onChange={(e) => setNotifPush(e.target.checked)} className="h-4 w-4 rounded border-neutral-300 text-teal-600 focus:ring-teal-500" />
            </label>
            <label className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div>
                <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">AI summary ready</p>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">Notify when a new summary is generated</p>
              </div>
              <input type="checkbox" checked={notifSummary} onChange={(e) => setNotifSummary(e.target.checked)} className="h-4 w-4 rounded border-neutral-300 text-teal-600 focus:ring-teal-500" />
            </label>
          </div>
        </div>
      </Card>

      {/* Profile Controls */}
      <Card>
        <CardHeader title="Profile" icon={<User className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="space-y-3">
            <div className="flex items-center gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-teal-100 text-sm font-semibold text-teal-700 dark:bg-teal-900 dark:text-teal-300">
                {user?.displayName?.charAt(0) || 'D'}
              </div>
              <div>
                <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{user?.displayName}</p>
                <p className="text-xs text-neutral-400">{user?.email}</p>
              </div>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400">Active Role</p>
              <div className="flex flex-wrap gap-2">
                {(['patient', 'clinician', 'administrator'] as const).map((r) => (
                  <button
                    key={r}
                    onClick={() => switchRole(r)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                      role === r
                        ? 'bg-teal-600 text-white'
                        : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700'
                    }`}
                  >
                    {r.charAt(0).toUpperCase() + r.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
