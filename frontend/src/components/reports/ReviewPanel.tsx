import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, Check, CheckCheck, Pencil, RotateCcw, X } from 'lucide-react';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import {
  errorMessage, extractionMethodLabels, flagLabels, flagVariant, reportsApi,
  type CandidateUpdate, type ExtractedCandidate, type ReportExtraction,
} from '@/lib/reports';
import type { MeasurementFlag, Report } from '@/lib/types';

interface ReviewPanelProps {
  report: Report;
  extraction: ReportExtraction;
  onExtractionChange: (next: ReportExtraction) => void;
  onConfirmed: (created: number) => Promise<void> | void;
}

const confidenceVariant = { high: 'success', medium: 'info', low: 'warning' } as const;
const FLAGS: MeasurementFlag[] = ['unknown', 'high', 'low', 'abnormal', 'normal'];

export function ReviewPanel({ report, extraction, onExtractionChange, onConfirmed }: ReviewPanelProps) {
  const [reportDate, setReportDate] = useState(extraction.document_date ?? '');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setReportDate(extraction.document_date ?? '');
  }, [extraction.report_id, extraction.document_date]);

  const open = useMemo(() => extraction.candidates.filter((c) => c.review_status !== 'confirmed'), [extraction]);
  const accepted = open.filter((c) => c.review_status === 'accepted').length;
  const pending = open.filter((c) => c.review_status === 'pending').length;

  const replace = (updated: ExtractedCandidate) =>
    onExtractionChange({ ...extraction, candidates: extraction.candidates.map((c) => (c.id === updated.id ? updated : c)) });

  const update = async (c: ExtractedCandidate, body: CandidateUpdate) => {
    setError(null);
    try {
      replace(await reportsApi.updateCandidate(report.id, c.id, body));
      return true;
    } catch (err) {
      setError(errorMessage(err, 'The change could not be saved.'));
      return false;
    }
  };

  const acceptAll = async () => {
    setSaving(true);
    let next = extraction;
    try {
      for (const c of open.filter((x) => x.review_status === 'pending' && x.value !== null)) {
        const u = await reportsApi.updateCandidate(report.id, c.id, { review_status: 'accepted' });
        next = { ...next, candidates: next.candidates.map((x) => (x.id === u.id ? u : x)) };
      }
      onExtractionChange(next);
    } catch (err) {
      onExtractionChange(next);
      setError(errorMessage(err, 'Some values could not be accepted.'));
    } finally {
      setSaving(false);
    }
  };

  const confirm = async () => {
    if (!reportDate) {
      setError('Enter the report date before confirming.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await reportsApi.confirm(report.id, reportDate);
      await onConfirmed(res.measurements_created);
    } catch (err) {
      setError(errorMessage(err, 'The review could not be confirmed.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="review-panel">
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-700/30 dark:bg-amber-900/10 dark:text-amber-300">
        <p className="font-semibold">Check each value against the original document.</p>
        <p className="mt-0.5">
          Values below were extracted automatically ({extractionMethodLabels[extraction.method]}). Only values you accept are saved to
          your health record. Reference ranges and flags are shown only when printed in the report.
        </p>
      </div>

      {extraction.warnings.length > 0 && (
        <ul className="space-y-1" data-testid="extraction-warnings">
          {extraction.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5 text-xs text-warning-700 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}
            </li>
          ))}
        </ul>
      )}

      {open.length === 0 ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          No laboratory values were recognised in this document. You can still confirm it as reviewed; its text remains available.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="review-table">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500 dark:border-neutral-800">
                <th className="px-2 py-2 font-medium">Test</th>
                <th className="px-2 py-2 text-right font-medium">Value</th>
                <th className="px-2 py-2 font-medium">Printed range</th>
                <th className="px-2 py-2 font-medium">Printed flag</th>
                <th className="px-2 py-2 font-medium">Source</th>
                <th className="px-2 py-2 font-medium">Decision</th>
              </tr>
            </thead>
            <tbody>
              {open.map((c) =>
                editingId === c.id ? (
                  <EditRow key={c.id} candidate={c} onCancel={() => setEditingId(null)}
                    onSave={async (body) => { if (await update(c, body)) setEditingId(null); }} />
                ) : (
                  <tr key={c.id} data-testid="review-row"
                    className={`border-b border-neutral-100 align-top dark:border-neutral-800/50 ${c.review_status === 'rejected' ? 'opacity-50' : ''}`}>
                    <td className="px-2 py-2">
                      <p className="text-xs font-medium text-neutral-900 dark:text-neutral-100">{c.test_name}</p>
                      <div className="mt-0.5 flex flex-wrap gap-1 whitespace-nowrap">
                        <StatusBadge variant={c.edited ? 'info' : 'neutral'}>{c.edited ? 'Edited by you' : 'Auto-extracted'}</StatusBadge>
                        <StatusBadge variant={confidenceVariant[c.confidence]}>{c.confidence} confidence</StatusBadge>
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right text-xs font-semibold text-neutral-900 dark:text-neutral-100">
                      {c.value === null ? <span className="text-error-600">missing</span> : c.value_text || c.value} {c.unit}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-xs text-neutral-500">{c.reference_range ?? 'Not printed'}</td>
                    <td className="whitespace-nowrap px-2 py-2"><StatusBadge variant={flagVariant(c.flag)}>{flagLabels[c.flag]}</StatusBadge></td>
                    <td className="px-2 py-2 text-xs text-neutral-400">
                      {c.page ? `Page ${c.page}` : ''}
                      <p className="max-w-[14rem] truncate font-mono text-[11px]" title={c.line_text}>{c.line_text}</p>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-1">
                        {c.review_status === 'pending' && (
                          <>
                            <IconButton label={`Accept ${c.test_name}`} onClick={() => update(c, { review_status: 'accepted' })} disabled={c.value === null}><Check className="h-3.5 w-3.5" /></IconButton>
                            <IconButton label={`Reject ${c.test_name}`} onClick={() => update(c, { review_status: 'rejected' })}><X className="h-3.5 w-3.5" /></IconButton>
                          </>
                        )}
                        {c.review_status !== 'pending' && (
                          <>
                            <StatusBadge variant={c.review_status === 'accepted' ? 'success' : 'neutral'}>
                              {c.review_status === 'accepted' ? 'Accepted' : 'Rejected'}
                            </StatusBadge>
                            <IconButton label={`Undo decision for ${c.test_name}`} onClick={() => update(c, { review_status: 'pending' })}><RotateCcw className="h-3.5 w-3.5" /></IconButton>
                          </>
                        )}
                        <IconButton label={`Edit ${c.test_name}`} onClick={() => setEditingId(c.id)}><Pencil className="h-3.5 w-3.5" /></IconButton>
                      </div>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800 sm:flex-row sm:items-end sm:justify-between">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Report / collection date</span>
          <input type="date" value={reportDate} onChange={(e) => setReportDate(e.target.value)} className="input" data-testid="review-date" />
          {!extraction.document_date && <span className="mt-1 block text-xs text-warning-700">Not found in the document — please enter it.</span>}
        </label>
        <div className="flex flex-wrap gap-2">
          {pending > 0 && (
            <Button variant="outline" size="sm" onClick={acceptAll} disabled={saving}>
              <CheckCheck className="h-3.5 w-3.5" /> Accept all remaining
            </Button>
          )}
          <Button size="sm" onClick={confirm} disabled={saving} data-testid="review-confirm">
            {saving ? 'Saving…' : open.length === 0 ? 'Confirm review' : `Confirm ${accepted} value${accepted === 1 ? '' : 's'}`}
          </Button>
        </div>
      </div>
      {pending > 0 && (
        <p className="text-xs text-neutral-400">{pending} value(s) not yet accepted will not be saved when you confirm.</p>
      )}
      {error && <p className="text-xs text-error-600" role="alert">{error}</p>}
    </div>
  );
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}
      className="rounded p-1 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800 disabled:opacity-40 dark:hover:bg-neutral-800 dark:hover:text-neutral-200">
      {children}
    </button>
  );
}

function EditRow({ candidate, onSave, onCancel }: {
  candidate: ExtractedCandidate;
  onSave: (body: CandidateUpdate) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(candidate.test_name);
  const [value, setValue] = useState(candidate.value === null ? '' : String(candidate.value));
  const [unit, setUnit] = useState(candidate.unit);
  const [range, setRange] = useState(candidate.reference_range ?? '');
  const [flag, setFlag] = useState<MeasurementFlag>(candidate.flag);
  const parsed = value.trim() === '' ? null : Number(value);
  const invalid = !name.trim() || (parsed !== null && !Number.isFinite(parsed));

  return (
    <tr className="border-b border-neutral-100 bg-neutral-50 align-top dark:border-neutral-800/50 dark:bg-neutral-800/30" data-testid="review-edit-row">
      <td className="px-2 py-2"><input aria-label="Test name" className="input py-1 text-xs" value={name} onChange={(e) => setName(e.target.value)} /></td>
      <td className="px-2 py-2">
        <div className="flex gap-1">
          <input aria-label="Value" inputMode="decimal" className="input w-20 py-1 text-xs" value={value} onChange={(e) => setValue(e.target.value)} />
          <input aria-label="Unit" className="input w-20 py-1 text-xs" value={unit} onChange={(e) => setUnit(e.target.value)} />
        </div>
      </td>
      <td className="px-2 py-2"><input aria-label="Printed reference range" className="input py-1 text-xs" value={range} onChange={(e) => setRange(e.target.value)} /></td>
      <td className="px-2 py-2">
        <select aria-label="Printed flag" className="input py-1 text-xs" value={flag} onChange={(e) => setFlag(e.target.value as MeasurementFlag)}>
          {FLAGS.map((f) => <option key={f} value={f}>{flagLabels[f]}</option>)}
        </select>
      </td>
      <td className="px-2 py-2 text-xs text-neutral-400">Enter values exactly as printed.</td>
      <td className="px-2 py-2">
        <div className="flex gap-1">
          <Button size="sm" disabled={invalid}
            onClick={() => onSave({ test_name: name.trim(), value: parsed, unit: unit.trim(), reference_range: range.trim() || null, flag, review_status: parsed === null ? 'pending' : 'accepted' })}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </td>
    </tr>
  );
}
