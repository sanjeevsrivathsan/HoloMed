import { useState } from 'react';
import {
  ShieldCheck, FileText, History, Download, XCircle, CheckCircle2, AlertCircle, Lock,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { Modal } from '@/components/Modal';
import { DemoDataBadge } from '@/components/DemoDataBadge';
import { EmptyState } from '@/components/States';
import type { ConsentRecord, AuditEvent, StorageConnection } from '@/lib/types';

interface PrivacyCenterProps {
  consents: ConsentRecord[];
  auditEvents: AuditEvent[];
  storageConnections: StorageConnection[];
}

export function PrivacyCenter({ consents, auditEvents, storageConnections }: PrivacyCenterProps) {
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftType, setDraftType] = useState<'access' | 'deletion' | 'portability'>('access');
  const [draftText, setDraftText] = useState('');

  const activeConsents = consents.filter((c) => !c.revoked);
  const revokedConsents = consents.filter((c) => c.revoked);
  const connectedStorage = storageConnections.filter((s) => s.status === 'connected');

  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const draftTemplates: Record<string, string> = {
    access: 'I, [Patient Name], request access to all personal health data held by HoloMed AI, including medical reports, imaging studies, AI-generated summaries, and audit records associated with my account.',
    deletion: 'I, [Patient Name], request deletion of my personal health data from HoloMed AI, including all reports, measurements, imaging metadata, and AI summaries. I understand this action is irreversible.',
    portability: 'I, [Patient Name], request a portable export of all my personal health data in a structured, machine-readable format, including all reports, measurements, and AI-generated summaries.',
  };

  const generateDraft = () => {
    setDraftText(draftTemplates[draftType]);
  };

  return (
    <div className="space-y-6">
      {/* Storage Connection Status */}
      <Card>
        <CardHeader title="Storage Connection Status" subtitle="Where your data is stored" icon={<Lock className="h-4.5 w-4.5" />} action={<DemoDataBadge />} />
        <div className="p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {storageConnections.map((conn) => (
              <div key={conn.provider} className="flex items-center gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                  conn.status === 'connected' ? 'bg-success-100 text-success-600 dark:bg-success-700/20 dark:text-success-400'
                  : conn.status === 'not_connected' ? 'bg-neutral-100 text-neutral-400 dark:bg-neutral-800'
                  : 'bg-neutral-50 text-neutral-300 dark:bg-neutral-800/50'
                }`}>
                  <Lock className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{conn.label}</p>
                  <p className="text-xs text-neutral-400">{conn.description}</p>
                </div>
                <StatusBadge variant={conn.status === 'connected' ? 'success' : conn.status === 'not_connected' ? 'warning' : 'neutral'}>
                  {conn.status === 'connected' ? 'Connected' : conn.status === 'not_connected' ? 'Not connected' : 'Coming later'}
                </StatusBadge>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* Consent Records */}
      <Card>
        <CardHeader title="Consent & Access Records" subtitle="Who has access to your health data" icon={<ShieldCheck className="h-4.5 w-4.5" />} />
        <div className="overflow-x-auto">
          {consents.length === 0 ? (
            <EmptyState title="No consent records" description="You have not issued any access consents." />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-800">
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Recipient</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Purpose</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Scope</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Issued</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Expiry</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Status</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-neutral-500">Action</th>
                </tr>
              </thead>
              <tbody>
                {consents.map((consent) => (
                  <tr key={consent.id} className="border-b border-neutral-100 dark:border-neutral-800/50">
                    <td className="px-3 py-2.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">{consent.recipient}</td>
                    <td className="px-3 py-2.5 text-xs text-neutral-500 dark:text-neutral-400">{consent.purpose}</td>
                    <td className="px-3 py-2.5"><StatusBadge variant="info">{consent.scope}</StatusBadge></td>
                    <td className="px-3 py-2.5 text-xs text-neutral-400">{formatDate(consent.issuedDate)}</td>
                    <td className="px-3 py-2.5 text-xs text-neutral-400">{formatDate(consent.expiryDate)}</td>
                    <td className="px-3 py-2.5">
                      <StatusBadge variant={consent.revoked ? 'error' : 'success'}>
                        {consent.revoked ? 'Revoked' : 'Active'}
                      </StatusBadge>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {!consent.revoked && (
                        <button className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-error-600 hover:bg-error-50 dark:hover:bg-error-700/10">
                          <XCircle className="h-3.5 w-3.5" />
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* Audit Trail */}
      <Card>
        <CardHeader title="Audit Trail" subtitle="Privacy-safe event log — no report content, tokens, or identifiers logged" icon={<History className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="space-y-2">
            {auditEvents.map((event) => (
              <div key={event.id} className="flex items-start gap-3 rounded-lg border border-neutral-100 px-3 py-2.5 dark:border-neutral-800/50">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-neutral-100 dark:bg-neutral-800">
                  <History className="h-3.5 w-3.5 text-neutral-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-neutral-700 dark:text-neutral-300">{event.description}</p>
                  <p className="text-xs text-neutral-400">
                    {event.eventType} · {event.actor} · {new Date(event.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* Data Rights Request */}
      <Card>
        <CardHeader title="Data Rights Requests" subtitle="Generate a draft request for your review — not automatic legal compliance" icon={<FileText className="h-4.5 w-4.5" />} />
        <div className="p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => { setDraftType('access'); setDraftOpen(true); }}>
                <Download className="h-3.5 w-3.5" /> Access Request
              </Button>
              <Button variant="outline" size="sm" onClick={() => { setDraftType('deletion'); setDraftOpen(true); }}>
                <XCircle className="h-3.5 w-3.5" /> Deletion Request
              </Button>
              <Button variant="outline" size="sm" onClick={() => { setDraftType('portability'); setDraftOpen(true); }}>
                <Download className="h-3.5 w-3.5" /> Data Portability
              </Button>
            </div>
          </div>
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 dark:bg-amber-900/10">
            <AlertCircle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-xs text-amber-700 dark:text-amber-400/90">
              Drafts are generated for your review and manual submission. HoloMed AI does not claim automatic legal compliance. Consult your jurisdiction's data protection authority for formal requests.
            </p>
          </div>
        </div>
      </Card>

      {/* Draft Modal */}
      <Modal
        open={draftOpen}
        onClose={() => setDraftOpen(false)}
        title="Data Rights Request Draft"
        description={`${draftType.charAt(0).toUpperCase() + draftType.slice(1)} request — for your review`}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDraftOpen(false)}>Close</Button>
            <Button onClick={generateDraft}>Generate Draft</Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-lg bg-blue-50 p-3 dark:bg-blue-900/10">
            <CheckCircle2 className="h-4 w-4 text-blue-600" />
            <p className="text-xs text-blue-700 dark:text-blue-400">This is a draft for your review. No request is sent automatically.</p>
          </div>
          {draftText && (
            <div className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
              <pre className="whitespace-pre-wrap text-sm text-neutral-700 dark:text-neutral-300">{draftText}</pre>
            </div>
          )}
          {!draftText && (
            <p className="text-sm text-neutral-400">Click "Generate Draft" to create a request template.</p>
          )}
        </div>
      </Modal>
    </div>
  );
}
