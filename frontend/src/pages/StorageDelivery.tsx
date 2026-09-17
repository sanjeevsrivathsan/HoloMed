import { useState } from 'react';
import {
  HardDrive, Cloud, Mail, Check, Lock, ArrowRight, FileText, FileCode,
  Sparkles, LayoutTemplate, Plus,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import type { StorageConnection, StorageProvider, ReportArtifact } from '@/lib/types';

interface StorageDeliveryProps {
  storageConnections: StorageConnection[];
}

const artifactTypeLabels: Record<ReportArtifact['type'], string> = {
  original_pdf: 'Original PDF',
  extracted_markdown: 'Extracted Markdown',
  structured_data: 'Structured Data',
  ai_summary: 'AI Summary',
  template_export: 'Template Export',
};

const artifactTypeIcons: Record<ReportArtifact['type'], typeof FileText> = {
  original_pdf: FileText,
  extracted_markdown: FileCode,
  structured_data: FileCode,
  ai_summary: Sparkles,
  template_export: LayoutTemplate,
};

export function StorageDelivery({ storageConnections }: StorageDeliveryProps) {
  const [destinations, setDestinations] = useState<Record<string, { primary: StorageProvider; delivery: StorageProvider[] }>>({
    original_pdf: { primary: 'local', delivery: [] },
    extracted_markdown: { primary: 'local', delivery: [] },
    structured_data: { primary: 'local', delivery: [] },
    ai_summary: { primary: 'local', delivery: [] },
    template_export: { primary: 'local', delivery: [] },
  });

  const connectedProviders = storageConnections.filter((s) => s.status === 'connected');
  const comingSoonProviders = storageConnections.filter((s) => s.status === 'coming_soon');
  const notConnectedProviders = storageConnections.filter((s) => s.status === 'not_connected');

  const setPrimary = (artifact: string, provider: StorageProvider) => {
    setDestinations((prev) => ({ ...prev, [artifact]: { ...prev[artifact], primary: provider } }));
  };

  const toggleDelivery = (artifact: string, provider: StorageProvider) => {
    setDestinations((prev) => {
      const current = prev[artifact];
      const has = current.delivery.includes(provider);
      return {
        ...prev,
        [artifact]: {
          ...current,
          delivery: has ? current.delivery.filter((p) => p !== provider) : [...current.delivery, provider],
        },
      };
    });
  };

  const providerIcon = (provider: StorageProvider) => {
    if (provider === 'local') return HardDrive;
    if (provider === 'messaging') return Mail;
    return Cloud;
  };

  return (
    <div className="space-y-6">
      {/* Provider Cards */}
      <Card>
        <CardHeader title="Storage Providers" subtitle="Choose your primary storage and delivery destinations" icon={<HardDrive className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {/* Connected */}
            {connectedProviders.map((conn) => {
              const Icon = providerIcon(conn.provider);
              return (
                <div key={conn.provider} className="rounded-xl border-2 border-teal-500 bg-teal-50/30 p-4 dark:bg-teal-950/10">
                  <div className="flex items-center justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400">
                      <Icon className="h-5 w-5" />
                    </div>
                    <StatusBadge variant="success">Connected</StatusBadge>
                  </div>
                  <p className="mt-3 text-sm font-semibold text-neutral-900 dark:text-neutral-100">{conn.label}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{conn.description}</p>
                  {conn.isPrimary && <StatusBadge variant="info" className="mt-2">Primary</StatusBadge>}
                </div>
              );
            })}

            {/* Not Connected */}
            {notConnectedProviders.map((conn) => {
              const Icon = providerIcon(conn.provider);
              return (
                <div key={conn.provider} className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
                  <div className="flex items-center justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-neutral-100 text-neutral-400 dark:bg-neutral-800">
                      <Icon className="h-5 w-5" />
                    </div>
                    <StatusBadge variant="warning">Not connected</StatusBadge>
                  </div>
                  <p className="mt-3 text-sm font-semibold text-neutral-900 dark:text-neutral-100">{conn.label}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{conn.description}</p>
                  <Button variant="outline" size="sm" className="mt-3 w-full" disabled>
                    <Lock className="h-3.5 w-3.5" /> Integration Required
                  </Button>
                </div>
              );
            })}

            {/* Coming Soon */}
            {comingSoonProviders.map((conn) => {
              const Icon = providerIcon(conn.provider);
              return (
                <div key={conn.provider} className="rounded-xl border border-dashed border-neutral-300 p-4 opacity-60 dark:border-neutral-700">
                  <div className="flex items-center justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-neutral-100 text-neutral-300 dark:bg-neutral-800">
                      <Icon className="h-5 w-5" />
                    </div>
                    <StatusBadge variant="neutral">Coming later</StatusBadge>
                  </div>
                  <p className="mt-3 text-sm font-semibold text-neutral-700 dark:text-neutral-300">{conn.label}</p>
                  <p className="text-xs text-neutral-400">{conn.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      {/* Artifact Destinations */}
      <Card>
        <CardHeader title="Artifact Storage & Delivery" subtitle="Choose primary storage and optional delivery per artifact type" icon={<ArrowRight className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="space-y-4">
            {(Object.keys(artifactTypeLabels) as ReportArtifact['type'][]).map((artifactType) => {
              const Icon = artifactTypeIcons[artifactType];
              const dest = destinations[artifactType];
              return (
                <div key={artifactType} className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                    <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{artifactTypeLabels[artifactType]}</p>
                  </div>

                  <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {/* Primary Storage */}
                    <div>
                      <p className="mb-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400">Primary Storage</p>
                      <div className="flex flex-wrap gap-1.5">
                        {storageConnections.filter((s) => s.status === 'connected').map((conn) => (
                          <button
                            key={conn.provider}
                            onClick={() => setPrimary(artifactType, conn.provider)}
                            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                              dest.primary === conn.provider
                                ? 'bg-teal-600 text-white'
                                : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700'
                            }`}
                          >
                            {dest.primary === conn.provider && <Check className="h-3 w-3" />}
                            {conn.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Delivery Destinations */}
                    <div>
                      <p className="mb-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400">Delivery Destinations (optional)</p>
                      <div className="flex flex-wrap gap-1.5">
                        {storageConnections.filter((s) => s.status === 'connected' || s.status === 'not_connected').map((conn) => (
                          <button
                            key={conn.provider}
                            onClick={() => toggleDelivery(artifactType, conn.provider)}
                            disabled={conn.status === 'not_connected'}
                            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                              dest.delivery.includes(conn.provider)
                                ? 'bg-teal-600 text-white'
                                : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700'
                            }`}
                          >
                            {dest.delivery.includes(conn.provider) && <Check className="h-3 w-3" />}
                            {conn.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex items-start gap-2 rounded-lg bg-blue-50 p-3 dark:bg-blue-900/10">
            <Mail className="h-4 w-4 shrink-0 text-blue-600" />
            <p className="text-xs text-blue-700 dark:text-blue-400">
              Email is a delivery destination only — it sends a copy. It is never used as primary record storage.
            </p>
          </div>
        </div>
      </Card>

      {/* Google Drive OAuth Notice */}
      <Card>
        <CardHeader title="Google Drive Integration" icon={<Cloud className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="flex items-start gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
            <Lock className="h-5 w-5 shrink-0 text-neutral-400" />
            <div>
              <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">OAuth Integration Placeholder</p>
              <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                Google Drive connection requires server-side OAuth credentials. The connection status is shown without exposing any credentials.
                When configured, file IDs are stored server-side — never in the browser.
              </p>
              <div className="mt-3 flex items-center gap-2">
                <StatusBadge variant="warning">Not connected</StatusBadge>
                <Button variant="outline" size="sm" disabled>
                  <Plus className="h-3.5 w-3.5" /> Connect Drive
                </Button>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
