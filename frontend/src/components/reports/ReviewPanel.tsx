import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, CalendarCheck, CheckCheck } from 'lucide-react';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import {
  dateSourceLabels, errorMessage, extractionMethodLabels, flagLabels, flagVariant, formatDay,
  reportsApi, type CandidateUpdate, type ExtractedCandidate, type ReportExtraction,
} from '@/lib/reports';
import { dateOptions, needsExplicitChoice } from '@/lib/reportDates';
import type { MeasurementFlag, Report } from '@/lib/types';

interface ReviewPanelProps {
  report: Report;
  extraction: ReportExtraction;
  onExtractionChange: (next: ReportExtraction) => void;
  /** Report-level data changed (date, counts, status): refresh reports and measurements. */
  onChanged: () => Promise<void> | void;
}

const confidenceVariant = { high: 'success', medium: 'info', low: 'warning' } as const;
const FLAGS: MeasurementFlag[] = ['unknown', 'high', 'low', 'abnormal', 'normal'];

type CandidateState = 'candidate' | 'confirmed' | 'ignored';
const stateOf = (c: ExtractedCandidate): CandidateState =>
  c.measurement_id !== null || c.review_status === 'confirmed' ? 'confirmed'
    : c.review_status === 'rejected' ? 'ignored' : 'candidate';

export function ReviewPanel({ report, extraction, onExtractionChange, onChanged }: ReviewPanelProps) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const candidates = extraction.candidates;
  const counts = useMemo(() => {
    const c = { candidate: 0, confirmed: 0, ignored: 0 };
    candidates.forEach((x) => { c[stateOf(x)] += 1; });
    return c;
  }, [candidates]);
  const dateConfirmed = !!report.dateConfirmed;

  const replace = (updated: ExtractedCandidate) =>
    onExtractionChange({ ...extraction, candidates: candidates.map((c) => (c.id === updated.id ? updated : c)) });

  const run = async (key: string, fn: () => Promise<void>, fallback: string) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err, fallback));
    } finally {
      setBusy(null);
    }
  };

  const update = (c: ExtractedCandidate, body: CandidateUpdate) =>
    run(`update-${c.id}`, async () => {
      replace(await reportsApi.updateCandidate(report.id, c.id, body));
      await onChanged();
    }, 'The change could not be saved.');

  const confirmOne = (c: ExtractedCandidate) =>
    run(`confirm-${c.id}`, async () => {
      replace(await reportsApi.confirmCandidate(report.id, c.id));
      await onChanged();
    }, 'The value could not be confirmed.');

  const confirmRemaining = () =>
    run('confirm-all', async () => {
      const ids = candidates.filter((c) => stateOf(c) === 'candidate' && c.value !== null).map((c) => c.id);
      await reportsApi.confirmCandidates(report.id, ids);
      onExtractionChange(await reportsApi.extraction(report.id));
      await onChanged();
    }, 'The values could not be confirmed.');

  const missingValues = candidates.filter((c) => stateOf(c) === 'candidate' && c.value === null).length;

  return (
    <div className="space-y-4" data-testid="review-panel">
      <ReportDateCard report={report} extraction={extraction} onChanged={onChanged} />

      {extraction.warnings.length > 0 && (
        <ul className="space-y-1" data-testid="extraction-warnings">
          {extraction.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}
            </li>
          ))}
        </ul>
      )}

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800" aria-labelledby="detected-heading">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-200 px-3 py-2 dark:border-neutral-800">
          <div>
            <h3 id="detected-heading" className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Detected measurements</h3>
            <p className="text-xs text-neutral-500" data-testid="review-counts">
              {candidates.length - counts.ignored} detected · {counts.confirmed} confirmed · {counts.candidate} to review · {counts.ignored} ignored
              <span className="text-neutral-400"> · {extractionMethodLabels[extraction.method]}</span>
            </p>
          </div>
          {counts.candidate > 0 && (
            <Button size="sm" onClick={confirmRemaining} disabled={!dateConfirmed || busy !== null} data-testid="review-confirm-all">
              <CheckCheck className="h-3.5 w-3.5" />
              {busy === 'confirm-all' ? 'Confirming…' : `Confirm all remaining (${counts.candidate - missingValues})`}
            </Button>
          )}
        </div>

        <p className="px-3 pt-2 text-xs text-neutral-500">
          Check each value against the original document. Only values you confirm become part of your health record.
          Reference ranges and flags are shown exactly as printed.
          {!dateConfirmed && <strong className="text-amber-700 dark:text-amber-400"> Confirm the report date above before confirming values.</strong>}
        </p>

        {candidates.length === 0 ? (
          <p className="p-3 text-sm text-neutral-500 dark:text-neutral-400" data-testid="review-no-values">
            No laboratory values were recognised in this document. Its text remains available in the Extracted Text tab.
          </p>
        ) : (
          <div className="overflow-x-auto p-1">
            <table className="w-full text-sm" data-testid="review-table">
              <thead>
                <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500 dark:border-neutral-800">
                  <th className="px-2 py-2 font-medium">Test</th>
                  <th className="px-2 py-2 text-right font-medium">Value</th>
                  <th className="px-2 py-2 font-medium">Printed reference range</th>
                  <th className="px-2 py-2 font-medium">Printed flag</th>
                  <th className="px-2 py-2 font-medium">Source</th>
                  <th className="px-2 py-2 font-medium">Decision</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => {
                  const state = stateOf(c);
                  if (editingId === c.id) {
                    return <EditRow key={c.id} candidate={c} onCancel={() => setEditingId(null)}
                      onSave={async (body) => { await update(c, body); setEditingId(null); }} />;
                  }
                  return (
                    <tr key={c.id} data-testid="review-row" data-state={state}
                      className={`border-b border-neutral-100 align-top dark:border-neutral-800/50 ${state === 'ignored' ? 'opacity-50' : ''}`}>
                      <td className="px-2 py-2">
                        <p className="text-xs font-semibold text-neutral-900 dark:text-neutral-100">{c.test_name}</p>
                        {c.source_name !== c.test_name && (
                          <p className="text-[11px] text-neutral-500">Printed as “{c.source_name}”</p>
                        )}
                        <div className="mt-1 flex flex-wrap gap-1 whitespace-nowrap">
                          <StateBadge state={state} />
                          {c.edited && <StatusBadge variant="info">Edited by you</StatusBadge>}
                          {state === 'candidate' && <StatusBadge variant={confidenceVariant[c.confidence]}>{c.confidence} confidence</StatusBadge>}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-right text-xs font-semibold text-neutral-900 dark:text-neutral-100">
                        {c.value === null ? <span className="text-error-600">missing</span> : c.value_text || c.value} {c.unit}
                      </td>
                      <td className="max-w-[16rem] px-2 py-2 text-xs text-neutral-600 dark:text-neutral-400">{c.reference_range ?? 'Not printed'}</td>
                      <td className="whitespace-nowrap px-2 py-2"><StatusBadge variant={flagVariant(c.flag)}>{flagLabels[c.flag]}</StatusBadge></td>
                      <td className="px-2 py-2 text-xs text-neutral-400">
                        {c.page ? `Page ${c.page}` : '—'}
                        <p className="max-w-[12rem] truncate font-mono text-[11px]" title={c.line_text}>{c.line_text}</p>
                      </td>
                      <td className="px-2 py-2">
                        {state === 'candidate' && (
                          <div className="flex flex-wrap gap-1">
                            <SmallButton onClick={() => confirmOne(c)} disabled={!dateConfirmed || c.value === null || busy !== null}
                              label={`Confirm ${c.test_name}`} primary>Confirm</SmallButton>
                            <SmallButton onClick={() => setEditingId(c.id)} disabled={busy !== null} label={`Edit ${c.test_name}`}>Edit</SmallButton>
                            <SmallButton onClick={() => update(c, { review_status: 'rejected' })} disabled={busy !== null}
                              label={`Ignore ${c.test_name}`}>Ignore</SmallButton>
                          </div>
                        )}
                        {state === 'ignored' && (
                          <SmallButton onClick={() => update(c, { review_status: 'pending' })} disabled={busy !== null}
                            label={`Restore ${c.test_name}`}>Restore</SmallButton>
                        )}
                        {state === 'confirmed' && <span className="text-xs text-neutral-400">Saved to your record</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {missingValues > 0 && (
          <p className="px-3 pb-2 text-xs text-amber-700">{missingValues} value(s) have no number; edit or ignore them.</p>
        )}
      </section>
      {error && <p className="text-xs text-error-600" role="alert" data-testid="review-error">{error}</p>}
    </div>
  );
}

function StateBadge({ state }: { state: CandidateState }) {
  if (state === 'confirmed') return <StatusBadge variant="success">Confirmed</StatusBadge>;
  if (state === 'ignored') return <StatusBadge variant="neutral">Ignored</StatusBadge>;
  return <StatusBadge variant="warning">Extracted · not confirmed</StatusBadge>;
}

function SmallButton({ children, onClick, disabled, label, primary }: {
  children: ReactNode; onClick: () => void; disabled?: boolean; label: string; primary?: boolean;
}) {
  return (
    <button type="button" aria-label={label} onClick={onClick} disabled={disabled}
      className={`rounded-md px-2 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        primary ? 'bg-teal-600 text-white hover:bg-teal-700'
          : 'border border-neutral-300 text-neutral-700 hover:bg-neutral-50 dark:border-neutral-600 dark:text-neutral-200 dark:hover:bg-neutral-800'
      }`}>
      {children}
    </button>
  );
}

function ReportDateCard({ report, extraction, onChanged }: {
  report: Report; extraction: ReportExtraction; onChanged: () => Promise<void> | void;
}) {
  const options = useMemo(() => dateOptions(extraction.date_candidates ?? []), [extraction.date_candidates]);
  const suggested = extraction.document_date ?? (options.length === 1 && !options[0].ambiguous ? options[0].value : null);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string>('');
  const [custom, setCustom] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSelected(suggested ?? '');
    setCustom('');
    setEditing(false);
  }, [report.id, suggested]);

  const save = async (value: string) => {
    if (!value) { setError('Choose or enter a date.'); return; }
    setSaving(true);
    setError(null);
    try {
      await reportsApi.confirmDate(report.id, value);
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(errorMessage(err, 'The date could not be saved.'));
    } finally {
      setSaving(false);
    }
  };

  if (report.dateConfirmed && !editing) {
    return (
      <section className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-success-100 bg-success-50/60 px-3 py-2 dark:border-green-900/40 dark:bg-green-950/20"
        data-testid="report-date-confirmed">
        <div className="flex items-center gap-2">
          <CalendarCheck className="h-4 w-4 text-success-600" />
          <div>
            <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Report date: {formatDay(report.date)}</p>
            <p className="text-xs text-neutral-500">
              {dateSourceLabels[report.dateSource ?? ''] ?? 'Confirmed'}
              {report.dateSource === 'user_override' && report.detectedDate && ` · detected: ${formatDay(report.detectedDate)}`}
            </p>
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setEditing(true)} data-testid="date-edit">Change</Button>
      </section>
    );
  }

  const single = !needsExplicitChoice(options);
  const showChoices = options.length > 1 || (options.length === 1 && options[0].ambiguous);
  return (
    <section className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-700/30 dark:bg-amber-900/10" data-testid="report-date-card">
      <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">Report date — please confirm</p>
      {options.length === 0 && (
        <p className="text-xs text-amber-800 dark:text-amber-300">No date was found in the document. Enter the date the sample was collected or the report was issued.</p>
      )}
      {single && !editing && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-neutral-800 dark:text-neutral-200" data-testid="detected-date">
            Detected from report: <strong>{formatDay(options[0].value)}</strong>
            <span className="text-xs text-neutral-500"> ({options[0].printed.join('; ')})</span>
          </p>
          <Button size="sm" onClick={() => save(options[0].value)} disabled={saving} data-testid="date-use-detected">Use this date</Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(true)} data-testid="date-change">Change</Button>
        </div>
      )}
      {showChoices && (
        <fieldset className="space-y-1" data-testid="date-options">
          <legend className="text-xs text-amber-800 dark:text-amber-300">
            {options.some((o) => o.ambiguous)
              ? 'The document’s day/month order is unclear. Select the date that represents the report date:'
              : 'Several dates were detected. Select the date that represents the report date:'}
          </legend>
          {options.map((o) => (
            <label key={o.value} className="flex items-start gap-2 text-sm text-neutral-800 dark:text-neutral-200">
              <input type="radio" name={`report-date-${report.id}`} value={o.value} checked={selected === o.value}
                onChange={() => { setSelected(o.value); setCustom(''); }} className="mt-1" />
              <span>
                <strong>{formatDay(o.value)}</strong> · {o.labels.join(', ')}
                <span className="block text-xs text-neutral-500">Printed: {o.printed.join('; ')}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {(editing || !single) && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="mb-1 block text-xs text-neutral-600 dark:text-neutral-400">
              {options.length ? 'Or enter a different date' : 'Report date'}
            </span>
            <input type="date" value={custom} onChange={(e) => { setCustom(e.target.value); if (e.target.value) setSelected(''); }}
              className="input" data-testid="review-date" />
          </label>
          <Button size="sm" onClick={() => save(custom || selected)} disabled={saving || !(custom || selected)} data-testid="date-confirm">
            {saving ? 'Saving…' : 'Use this date'}
          </Button>
          {editing && <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>}
        </div>
      )}
      {error && <p className="text-xs text-error-600" role="alert">{error}</p>}
    </section>
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
  const invalid = !name.trim() || (parsed !== null && !Number.isFinite(parsed)) || range.length > 200;

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
      <td className="px-2 py-2 text-xs text-neutral-400">Enter values exactly as printed. Editing does not confirm.</td>
      <td className="px-2 py-2">
        <div className="flex gap-1">
          <Button size="sm" disabled={invalid}
            onClick={() => onSave({ test_name: name.trim(), value: parsed, unit: unit.trim(), reference_range: range.trim() || null, flag })}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </td>
    </tr>
  );
}
