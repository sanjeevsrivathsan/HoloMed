import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Check, ChevronDown, Plus, Search, User } from 'lucide-react';
import { Modal } from '@/components/Modal';
import { Button } from '@/components/Button';
import { usePatients } from '@/context/PatientContext';
import { ApiError } from '@/lib/api';
import {
  filterPatients, normalizePatientCode, normalizePatientName, normalizePhone, patientDetails,
  suggestPatientCode, validateNewPatient, type NewPatientInput,
} from '@/lib/patients';

export function PatientSelector() {
  const { patients, activePatient, selectPatient, loading } = usePatients();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const shown = filterPatients(patients, query);
  const close = (focusTrigger = true) => {
    setOpen(false);
    setQuery('');
    if (focusTrigger) triggerRef.current?.focus();
  };
  const options = () => [...(listRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])];

  // ↑/↓ move between search and options; Escape closes and returns focus to the trigger.
  const onPanelKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = options();
    if (items.length === 0) return;
    e.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (at === -1) { (e.key === 'ArrowDown' ? items[0] : items[items.length - 1]).focus(); return; }
    const next = at + (e.key === 'ArrowDown' ? 1 : -1);
    if (next < 0) searchRef.current?.focus();
    else items[Math.min(next, items.length - 1)].focus();
  };

  return (
    <div className="relative" ref={ref}>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true); } }}
        className="flex max-w-[16rem] items-center gap-2 rounded-lg border border-neutral-200 px-2.5 py-1 text-left hover:bg-neutral-50 focus-visible:ring-2 focus-visible:ring-teal-500 dark:border-neutral-700 dark:hover:bg-neutral-800"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={activePatient ? `Patient ${activePatient.patient_code}, ${activePatient.name}. Change patient` : 'Select patient'}
        data-testid="patient-selector"
      >
        <User className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
        <span className="min-w-0 leading-tight" data-testid="active-patient">
          {activePatient ? (
            <>
              <span className="block font-mono text-[11px] font-semibold text-neutral-700 dark:text-neutral-200">{activePatient.patient_code}</span>
              <span className="block truncate text-xs text-neutral-500 dark:text-neutral-400">{activePatient.name}</span>
            </>
          ) : (
            <span className="text-xs text-neutral-500">{loading ? 'Loading patients…' : 'No patient selected'}</span>
          )}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full z-30 mt-2 flex max-h-[min(36rem,calc(100dvh-5rem))] w-80 flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-xl dark:border-neutral-700 dark:bg-neutral-900 animate-fade-in"
          onKeyDown={onPanelKeyDown}
          data-testid="patient-panel"
        >
          <div className="shrink-0 border-b border-neutral-100 p-2 dark:border-neutral-800">
            <p className="px-2 py-1 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Patients</p>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-neutral-400" />
              <input
                ref={searchRef}
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search patients…"
                aria-label="Search patients"
                className="w-full rounded-lg border border-neutral-200 bg-white py-1.5 pl-8 pr-2 text-xs text-neutral-800 placeholder:text-neutral-400 focus:border-teal-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100"
              />
            </div>
            {activePatient && (
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-lg bg-neutral-50 px-2.5 py-2 text-[11px] dark:bg-neutral-800/60" data-testid="active-patient-details">
                {patientDetails(activePatient).map(({ label, value }) => (
                  <div key={label} className="contents">
                    <dt className="text-neutral-400">{label}</dt>
                    <dd className="truncate text-neutral-700 dark:text-neutral-200">{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <ul ref={listRef} className="min-h-0 flex-1 space-y-0.5 overflow-y-auto overscroll-contain p-2" role="listbox" aria-label="Patients" data-testid="patient-list">
            {shown.map((p) => {
              const current = p.id === activePatient?.id;
              return (
                <li key={p.id}>
                  <button
                    role="option"
                    aria-selected={current}
                    onClick={() => { selectPatient(p.id); close(); }}
                    className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                      current ? 'bg-teal-50 dark:bg-teal-950/40' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800'
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block font-mono text-[11px] font-semibold text-neutral-800 dark:text-neutral-200">{p.patient_code}</span>
                      <span className="block truncate text-xs text-neutral-600 dark:text-neutral-400">{p.name}</span>
                      <span className="block text-[10px] text-neutral-400">
                        {p.study_count} imaging · {p.report_count} reports
                      </span>
                    </span>
                    {current && <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-teal-600" />}
                  </button>
                </li>
              );
            })}
            {shown.length === 0 && <li className="px-2 py-2 text-xs text-neutral-400">No matching patients</li>}
          </ul>
          <div className="shrink-0 border-t border-neutral-100 p-2 dark:border-neutral-800">
            <button
              onClick={() => { close(false); setCreating(true); }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-medium text-teal-700 hover:bg-teal-50 focus-visible:ring-2 focus-visible:ring-teal-500 dark:text-teal-300 dark:hover:bg-teal-950/40"
            >
              <Plus className="h-3.5 w-3.5" /> New Patient
            </button>
          </div>
        </div>
      )}

      <NewPatientModal open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

const FORM_ID = 'new-patient-form';

function NewPatientModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { patients, createPatient } = usePatients();
  const codes = patients.map((p) => p.patient_code);
  const empty: NewPatientInput = { name: '', patient_code: '', age: '', sex: '', phone: '' };
  const [form, setForm] = useState<NewPatientInput>(empty);
  const [errors, setErrors] = useState<Partial<Record<keyof NewPatientInput, string>>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({ ...empty, patient_code: suggestPatientCode(codes) });
      setErrors({});
      setServerError(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Editing a field clears that field's error; everything is re-validated on submit.
  const update = (key: keyof NewPatientInput, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((errs) => {
      if (!errs[key]) return errs;
      const next = { ...errs };
      delete next[key];
      return next;
    });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found = validateNewPatient(form, codes);
    setErrors(found);
    if (Object.keys(found).length) return;
    setSaving(true);
    setServerError(null);
    try {
      await createPatient({
        name: normalizePatientName(form.name),
        patient_code: normalizePatientCode(form.patient_code),
        age: form.age,
        sex: form.sex || undefined,
        phone: normalizePhone(form.phone) || undefined,
      });
      onClose();
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : 'The patient could not be created.');
    } finally {
      setSaving(false);
    }
  };

  const control = 'rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-teal-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100';
  const field = `mt-1 w-full ${control}`;
  const label = 'block text-xs font-medium text-neutral-600 dark:text-neutral-300';
  const hint = (k: keyof NewPatientInput) => errors[k]
    ? <p id={`np-${k}-error`} className="mt-1 text-xs text-error-600 dark:text-error-400" role="alert">{errors[k]}</p>
    : null;
  const described = (k: keyof NewPatientInput) => (errors[k] ? `np-${k}-error` : undefined);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create Patient"
      description="Add a patient workspace. Imaging, reports and AI results are stored under this patient."
      size="sm"
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button type="submit" form={FORM_ID} disabled={saving}>{saving ? 'Creating…' : 'Create Patient'}</Button>
        </>
      }
    >
      <form id={FORM_ID} onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <label className={label} htmlFor="np-name">Patient Name <span aria-hidden="true">*</span></label>
          <input id="np-name" className={field} value={form.name} maxLength={200} required aria-required="true"
            aria-invalid={!!errors.name} aria-describedby={described('name')} autoComplete="off"
            onChange={(e) => update('name', e.target.value)} data-autofocus />
          {hint('name')}
        </div>
        <div>
          <label className={label} htmlFor="np-code">Patient ID / Patient Code <span aria-hidden="true">*</span></label>
          <input id="np-code" className={`${field} font-mono uppercase`} value={form.patient_code} maxLength={64} required
            aria-required="true" aria-invalid={!!errors.patient_code} aria-describedby={described('patient_code')} autoComplete="off"
            onChange={(e) => update('patient_code', e.target.value)} />
          {hint('patient_code')}
        </div>
        <div>
          <label className={label} htmlFor="np-age">Age</label>
          <div className="mt-1 flex items-center gap-2">
            <input id="np-age" type="number" inputMode="numeric" min={0} max={130} step={1}
              className={`w-24 ${control}`} value={form.age}
              aria-invalid={!!errors.age} aria-describedby={described('age') ?? 'np-age-unit'}
              onChange={(e) => update('age', e.target.value)} />
            <span id="np-age-unit" className="text-sm text-neutral-500 dark:text-neutral-400">years</span>
          </div>
          {hint('age')}
        </div>
        <div>
          <label className={label} htmlFor="np-sex">Sex</label>
          <select id="np-sex" className={field} value={form.sex} onChange={(e) => update('sex', e.target.value)}>
            <option value="">Not specified</option>
            <option value="female">Female</option>
            <option value="male">Male</option>
            <option value="other">Other</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>
        <div>
          <label className={label} htmlFor="np-phone">Phone Number</label>
          <input id="np-phone" type="tel" inputMode="tel" autoComplete="tel" className={field} value={form.phone} maxLength={40}
            placeholder="+91 98765 43210" aria-invalid={!!errors.phone} aria-describedby={described('phone')}
            onChange={(e) => update('phone', e.target.value)} />
          {hint('phone')}
        </div>
        {serverError && <p className="text-xs text-error-600 dark:text-error-400" role="alert">{serverError}</p>}
        {/* Enter in any field submits via this hidden button (the visible one is in the footer). */}
        <button type="submit" className="hidden" tabIndex={-1} aria-hidden="true" />
      </form>
    </Modal>
  );
}
