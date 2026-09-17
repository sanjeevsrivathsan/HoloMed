import { useCallback, useEffect, useState } from 'react';
import { Cpu, Lock, RefreshCw } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { api } from '@/lib/api';
import { getVisionStatus, providerLabel, type VisionStatus } from '@/lib/vision';

interface TextAiStatus {
  provider: 'ollama' | 'omniroute' | 'unknown';
  model: string | null;
  status: 'connected' | 'not_running' | 'model_missing' | 'configured' | 'not_configured';
}

const visionStateLabel: Record<VisionStatus['status'], [string, 'success' | 'info' | 'warning' | 'neutral']> = {
  ready: ['Ready', 'success'],
  standby: ['Standby — model loads on first scan', 'info'],
  loading: ['Loading', 'info'],
  unavailable: ['Not available', 'warning'],
};

const textStateLabel: Record<TextAiStatus['status'], [string, 'success' | 'info' | 'warning' | 'neutral']> = {
  connected: ['Connected', 'success'],
  configured: ['Configured', 'info'],
  not_running: ['Not running', 'warning'],
  model_missing: ['Model not installed', 'warning'],
  not_configured: ['Not configured', 'neutral'],
};

const textProviderLabel = (p: TextAiStatus['provider']) =>
  p === 'ollama' ? 'Ollama (local)' : p === 'omniroute' ? 'Hosted gateway' : 'Unknown';

/** Read-only status of the vision and text AI services. No URLs, keys or tokens are shown. */
export function AiServicesCard() {
  const [vision, setVision] = useState<VisionStatus | null>(null);
  const [visionFailed, setVisionFailed] = useState(false);
  const [text, setText] = useState<TextAiStatus | null>(null);
  const [textFailed, setTextFailed] = useState(false);
  const [checking, setChecking] = useState(false);

  const refresh = useCallback(async () => {
    setChecking(true);
    const [v, t] = await Promise.allSettled([getVisionStatus(), api.get<TextAiStatus>('/api/v1/ai/status')]);
    setVision(v.status === 'fulfilled' ? v.value : null);
    setVisionFailed(v.status === 'rejected');
    setText(t.status === 'fulfilled' ? t.value : null);
    setTextFailed(t.status === 'rejected');
    setChecking(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const [vLabel, vVariant] = vision ? visionStateLabel[vision.status] : visionFailed ? ['Status unavailable', 'neutral' as const] : ['Checking…', 'neutral' as const];
  const [tLabel, tVariant] = text ? textStateLabel[text.status] : textFailed ? ['Status unavailable', 'neutral' as const] : ['Checking…', 'neutral' as const];

  return (
    <Card>
      <CardHeader
        title="AI Services"
        subtitle="Where AI runs for this workspace"
        icon={<Cpu className="h-4.5 w-4.5" />}
        action={
          <Button variant="outline" size="sm" onClick={refresh} disabled={checking}>
            <RefreshCw className={`h-3.5 w-3.5 ${checking ? 'animate-spin' : ''}`} />
            {checking ? 'Checking…' : 'Check again'}
          </Button>
        }
      />
      <div className="space-y-3 p-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800" data-testid="settings-vision-ai">
            <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-200">Vision AI</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Chest X-ray screening model</p>
            <dl className="mt-2 space-y-1 text-xs">
              <div className="flex justify-between gap-2"><dt className="text-neutral-500">Provider</dt><dd className="text-neutral-900 dark:text-neutral-100">{vision ? providerLabel(vision) : '—'}</dd></div>
              <div className="flex items-center justify-between gap-2"><dt className="text-neutral-500">Status</dt><dd><StatusBadge variant={vVariant}>{vLabel}</StatusBadge></dd></div>
            </dl>
          </div>
          <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800" data-testid="settings-text-ai">
            <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-200">Text AI</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">Report summaries and screening explanations</p>
            <dl className="mt-2 space-y-1 text-xs">
              <div className="flex justify-between gap-2"><dt className="text-neutral-500">Provider</dt><dd className="text-neutral-900 dark:text-neutral-100">{text ? textProviderLabel(text.provider) : '—'}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-neutral-500">Model</dt><dd className="font-mono text-neutral-900 dark:text-neutral-100">{text?.model ?? '—'}</dd></div>
              <div className="flex items-center justify-between gap-2"><dt className="text-neutral-500">Status</dt><dd><StatusBadge variant={tVariant}>{tLabel}</StatusBadge></dd></div>
            </dl>
            {text?.status === 'not_running' && (
              <p className="mt-2 text-xs text-neutral-500">Start Ollama on the server to enable AI summaries. Everything else keeps working.</p>
            )}
            {text?.status === 'model_missing' && (
              <p className="mt-2 text-xs text-neutral-500">Ollama is running, but the configured model is not installed.</p>
            )}
          </div>
        </div>
        <div className="flex items-start gap-2 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/50">
          <Lock className="h-4 w-4 shrink-0 text-neutral-400" />
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            AI configuration and any credentials are managed on the server and never sent to the browser.
          </p>
        </div>
      </div>
    </Card>
  );
}
