/** Patient workspace helpers (pure; no React, no network). */

export interface PatientSummary {
  id: string;             // immutable patient uid
  patient_code: string;   // human-facing Patient ID, unique per account
  name: string;
  age: number | null;
  sex: string | null;
  phone: string | null;
  created_at: string | null;
  updated_at: string | null;
  study_count: number;
  report_count: number;
  analysis_count: number;
}

export interface NewPatientInput {
  name: string;
  patient_code: string;
  /** Whole years as typed (validated to an integer 0–130). */
  age?: string;
  sex?: string;
  phone?: string;
}

// Mirrors backend/dependencies/patient.py.
const CODE_PATTERN = /^[A-Z0-9][A-Z0-9._-]{1,31}$/;
export const MAX_PATIENT_NAME = 120;

export function normalizePatientCode(code: string): string {
  return code.trim().toUpperCase();
}

export function normalizePatientName(name: string): string {
  return name.split(/\s+/).filter(Boolean).join(' ');
}

export const MAX_AGE = 130;

/** Age as an integer, or null when empty. Throws nothing: invalid input returns NaN. */
export function parseAge(age: string | undefined): number | null {
  const text = (age ?? '').trim();
  if (!text) return null;
  return /^\d{1,3}$/.test(text) ? Number(text) : Number.NaN;
}

// Mirrors backend validate_phone: optional leading +, digits with spaces ( ) . -, 6–15 digits, ≤ 24 chars.
const PHONE_PATTERN = /^\+?[0-9][0-9 ().-]*$/;

export function normalizePhone(phone: string | undefined): string {
  return (phone ?? '').split(/\s+/).filter(Boolean).join(' ');
}

export function isValidPhone(phone: string): boolean {
  const digits = phone.replace(/\D/g, '').length;
  return phone.length <= 24 && PHONE_PATTERN.test(phone) && digits >= 6 && digits <= 15;
}

export const SEX_LABELS: Record<string, string> = {
  female: 'Female', male: 'Male', other: 'Other', unknown: 'Unknown',
};

/** Compact detail lines for the patient panel (never shown in the top bar). */
export function patientDetails(p: Pick<PatientSummary, 'age' | 'sex' | 'phone'>): { label: string; value: string }[] {
  return [
    { label: 'Age', value: p.age === null || p.age === undefined ? 'Not specified' : `${p.age} years` },
    { label: 'Sex', value: p.sex ? SEX_LABELS[p.sex] ?? p.sex : 'Not specified' },
    { label: 'Phone', value: p.phone || 'Not specified' },
  ];
}

/** Field errors for the New Patient form; empty when the input is valid. */
export function validateNewPatient(input: NewPatientInput, existingCodes: string[]): Partial<Record<keyof NewPatientInput, string>> {
  const errors: Partial<Record<keyof NewPatientInput, string>> = {};
  const name = normalizePatientName(input.name);
  if (!name) errors.name = 'Patient name is required.';
  else if (name.length > MAX_PATIENT_NAME) errors.name = `Patient name must be at most ${MAX_PATIENT_NAME} characters.`;
  const code = normalizePatientCode(input.patient_code);
  if (!code) errors.patient_code = 'Patient ID is required.';
  else if (!CODE_PATTERN.test(code)) errors.patient_code = "Use 2–32 letters, digits, '.', '_' or '-'.";
  else if (existingCodes.map(normalizePatientCode).includes(code)) errors.patient_code = `Patient ID ${code} already exists.`;
  const age = parseAge(input.age);
  if (age !== null && (Number.isNaN(age) || age > MAX_AGE)) errors.age = `Enter whole years from 0 to ${MAX_AGE}.`;
  const phone = normalizePhone(input.phone);
  if (phone && !isValidPhone(phone)) errors.phone = 'Enter a valid phone number, e.g. +91 98765 43210.';
  return errors;
}

/** Next suggested HML-000001-style code not already used. */
export function suggestPatientCode(existingCodes: string[]): string {
  const used = new Set(existingCodes.map(normalizePatientCode));
  const numbers = [...used].map((c) => /^HML-(\d+)$/.exec(c)).filter(Boolean).map((m) => Number(m![1]));
  let n = Math.max(0, ...numbers) + 1;
  while (used.has(`HML-${String(n).padStart(6, '0')}`)) n += 1;
  return `HML-${String(n).padStart(6, '0')}`;
}

export function patientLabel(p: Pick<PatientSummary, 'patient_code' | 'name'>): string {
  return `${p.patient_code} — ${p.name}`;
}

export function filterPatients<T extends Pick<PatientSummary, 'patient_code' | 'name'>>(patients: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return patients;
  return patients.filter((p) => p.patient_code.toLowerCase().includes(q) || p.name.toLowerCase().includes(q));
}

/** The remembered active patient if it still exists, otherwise the first patient. */
export function pickActivePatient(patients: Pick<PatientSummary, 'id'>[], rememberedId: string | null): string | null {
  if (rememberedId && patients.some((p) => p.id === rememberedId)) return rememberedId;
  return patients[0]?.id ?? null;
}

export function activePatientStorageKey(userId: string | number): string {
  return `holomed.activePatient.${userId}`;
}

export interface OhifStudyRef {
  studyInstanceUid: string;
  seriesInstanceUid?: string | null;
}

/**
 * OHIF launch URL for one patient's study. The `holomed` data source (dicomwebproxy) loads its
 * DICOMweb roots from the patient's ohif-config, so OHIF can only query that patient's studies;
 * studyInstanceUIDs/SeriesInstanceUIDs select the study and series to display.
 */
export function ohifViewerUrl(ohifBase: string, patientId: string, study: OhifStudyRef): string {
  const base = ohifBase.replace(/\/?$/, '/');
  const params = new URLSearchParams();
  params.set('url', `/api/v1/patients/${encodeURIComponent(patientId)}/dicomweb/ohif-config`);
  // The dicomwebproxy source reads `studyInstanceUIDs` (it ignores `StudyInstanceUIDs`).
  params.set('studyInstanceUIDs', study.studyInstanceUid);
  if (study.seriesInstanceUid) params.set('SeriesInstanceUIDs', study.seriesInstanceUid);
  return `${base}viewer/holomed?${params.toString()}`;
}
