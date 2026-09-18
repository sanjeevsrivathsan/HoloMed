/** Patient workspace helpers (pure; no React, no network). */

export interface PatientSummary {
  id: string;             // immutable patient uid
  patient_code: string;   // human-facing Patient ID, unique per account
  name: string;
  date_of_birth: string | null;
  sex: string | null;
  created_at: string | null;
  updated_at: string | null;
  study_count: number;
  report_count: number;
  analysis_count: number;
}

export interface NewPatientInput {
  name: string;
  patient_code: string;
  date_of_birth?: string;
  sex?: string;
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
  if (input.date_of_birth && !/^\d{4}-\d{2}-\d{2}$/.test(input.date_of_birth)) errors.date_of_birth = 'Use YYYY-MM-DD.';
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
