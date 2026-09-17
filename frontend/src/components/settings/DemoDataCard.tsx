import { useEffect, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { errorMessage, reportsApi } from '@/lib/reports';

/** Opt-in synthetic demonstration data (three labelled blood test reports). */
export function DemoDataCard({ onChanged }: { onChanged: () => Promise<void> | void }) {
  const [loaded, setLoaded] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    reportsApi.demoStatus().then((s) => setLoaded(s.loaded)).catch(() => setLoaded(null));
  }, []);

  const run = async (action: 'load' | 'clear') => {
    setBusy(true);
    setMessage(null);
    try {
      if (action === 'load') {
        const res = await reportsApi.loadDemo();
        setMessage(`Loaded ${res.report_ids.length} synthetic blood test reports. The newest one is waiting for your review.`);
        setLoaded(true);
      } else {
        const res = await reportsApi.clearDemo();
        setMessage(`Removed ${res.removed} demo report(s) and their derived data.`);
        setLoaded(false);
      }
      await onChanged();
    } catch (err) {
      setMessage(errorMessage(err, 'The demo data action failed. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Demo Data" subtitle="For demonstrations and testing only" icon={<FlaskConical className="h-4.5 w-4.5" />} />
      <div className="space-y-3 p-5" data-testid="demo-data">
        <div className="rounded-lg border border-neutral-200 p-3 text-xs text-neutral-600 dark:border-neutral-800 dark:text-neutral-300">
          <p className="font-semibold">DEMONSTRATION DATA — synthetic, not real patient records</p>
          <p className="mt-1">
            Adds three generated blood test reports spread over two years. Each document is marked synthetic and goes through the
            normal upload pipeline. Values and laboratory flags are invented for demonstration.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {loaded === true && <StatusBadge variant="info">Demo data loaded</StatusBadge>}
          {loaded !== true ? (
            <Button size="sm" onClick={() => run('load')} disabled={busy} data-testid="demo-load">
              {busy ? 'Loading…' : 'Load Demo Data'}
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => run('clear')} disabled={busy} data-testid="demo-clear">
              {busy ? 'Removing…' : 'Remove Demo Data'}
            </Button>
          )}
        </div>
        {message && <p className="text-xs text-neutral-500" role="status">{message}</p>}
      </div>
    </Card>
  );
}
