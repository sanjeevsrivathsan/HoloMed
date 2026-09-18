import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Check, ChevronDown, Plus, Search, User } from 'lucide-react';
import { Modal } from '@/components/Modal';
import { Button } from '@/components/Button';
import { usePatients } from '@/context/PatientContext';
import { ApiError } from '@/lib/api';
import {
  filterPatients, normalizePatientCode, normalizePatientName, patientLabel, suggestPatientCode, validateNewPatient,
  type NewPatientInput,
} from '@/lib/patients';

export function PatientSelector() {
  const { patients, activePatient, selectPatient, loading } = usePatients();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const shown = filterPatients(patients, query);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex max-w-[22rem] items-center gap-1.5 rounded-lg border border-neutral-200 px-2.5 py-1 text-left hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        aria-haspopup="listbox"
        aria-expanded={open}
        data-testid="patient-selector"
      >
        <User className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
        <span className="truncate text-xs font-medium text-neutral-600 dark:text-neutral-300" data-testid="active-patient">
          {activePatient ? `Patient: ${patientLabel(activePatient)}` : loading ? 'Loading patients…' : 'No patient selected'}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-80 rounded-xl border border-neutral-200 bg-white p-2 shadow-xl dark:border-neutral-800 dark:bg-neutral-900 animate-fade-in">
          <p className="px-2 py-1.5 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Patients</p>
          <div className="relative px-1 pb-2">
            <Search className="pointer-events-none absolute left-3.5 top-2.5 h-3.5 w-3.5 text-neutral-400" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search patients…"
              aria-label="Search patients"
              className="w-full rounded-lg border border-neutral-200 bg-white py-1.5 pl-8 pr-2 text-xs text-neutral-800 focus:border-teal-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100"
            />
          </div>
          <ul className="max-h-72 space-y-0.5 overflow-y-auto" role="listbox" aria-label="Patients">
            {shown.map((p) => {
              const current = p.id === activePatient?.id;
              return (
                <li key={p.id}>
                  <button
                    role="option"
                    aria-selected={current}
                    onClick={() => { selectPatient(p.id); setOpen(false); setQuery(''); }}
                    className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left ${
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
          <div className="mt-1 border-t border-neutral-100 pt-1.5 dark:border-neutral-800">
            <button
              onClick={() => { setCreating(true); setOpen(false); }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-medium text-teal-700 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-teal-950/40"
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

function NewPatientModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { patients, createPatient } = usePatients();
  const codes = patients.map((p) => p.patient_code);
  const empty: NewPatientInput = { name: '', patient_code: '', date_of_birth: '', sex: '' };
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
        date_of_birth: form.date_of_birth || undefined,
        sex: form.sex || undefined,
      });
      onClose();
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : 'The patient could not be created.');
    } finally {
      setSaving(false);
    }
  };

  const field = 'mt-1 w-full rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-sm text-neutral-900 focus:border-teal-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100';
  const label = 'block text-xs font-medium text-neutral-600 dark:text-neutral-400';
  const err = (k: keyof NewPatientInput) => errors[k] && <p className="mt-1 text-xs text-error-600" role="alert">{errors[k]}</p>;

  return (
    <Modal open={open} onClose={onClose} title="New Patient" description="Create a patient workspace. Imaging, reports and AI results are stored under this patient." size="sm">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <div>
          <label className={label} htmlFor="np-name">Patient Name *</label>
          <input id="np-name" className={field} value={form.name} maxLength={200}
            onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />
          {err('name')}
        </div>
        <div>
          <label className={label} htmlFor="np-code">Patient ID / Patient Code *</label>
          <input id="np-code" className={`${field} font-mono uppercase`} value={form.patient_code} maxLength={64}
            onChange={(e) => setForm({ ...form, patient_code: e.target.value })} />
          {err('patient_code')}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label} htmlFor="np-dob">Date of Birth</label>
            <input id="np-dob" type="date" className={field} value={form.date_of_birth}
              onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} />
            {err('date_of_birth')}
          </div>
          <div>
            <label className={label} htmlFor="np-sex">Sex</label>
            <select id="np-sex" className={field} value={form.sex} onChange={(e) => setForm({ ...form, sex: e.target.value })}>
              <option value="">Not specified</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>
        </div>
        {serverError && <p className="text-xs text-error-600" role="alert">{serverError}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button type="submit" disabled={saving}>{saving ? 'Creating…' : 'Create Patient'}</Button>
        </div>
      </form>
    </Modal>
  );
}
