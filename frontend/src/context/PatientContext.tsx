/**
 * Active patient for the whole workspace.
 *
 * Patients live in the backend (GET/POST /api/v1/patients); this context only remembers which one
 * is active (per signed-in user, in localStorage) and puts it on every API request, so every page
 * loads that patient's data. The backend checks ownership of the patient on each request.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, setActivePatientId } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import {
  activePatientStorageKey, parseAge, pickActivePatient, type NewPatientInput, type PatientSummary,
} from '@/lib/patients';

interface PatientContextValue {
  patients: PatientSummary[];
  activePatient: PatientSummary | null;
  loading: boolean;
  error: string | null;
  selectPatient: (id: string) => void;
  createPatient: (input: NewPatientInput) => Promise<PatientSummary>;
  refreshPatients: () => Promise<void>;
}

const PatientContext = createContext<PatientContextValue | null>(null);

function readRemembered(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function remember(key: string, id: string): void {
  try { window.localStorage.setItem(key, id); } catch { /* storage unavailable: selection lasts for this tab only */ }
}

export function PatientProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storageKey = user ? activePatientStorageKey(user.id) : null;

  const activate = useCallback((id: string | null) => {
    setActivePatientId(id);   // before any re-render triggers patient-scoped requests
    setActiveId(id);
    if (id && storageKey) remember(storageKey, id);
  }, [storageKey]);

  const load = useCallback(async () => {
    if (!storageKey) return;
    setLoading(true);
    try {
      let list = await api.get<PatientSummary[]>('/api/v1/patients');
      if (list.length === 0) {
        await api.post<PatientSummary>('/api/v1/patients', { name: 'Patient 1' });
        list = await api.get<PatientSummary[]>('/api/v1/patients');
      }
      setPatients(list);
      setError(null);
      setActiveId((current) => {
        const id = pickActivePatient(list, current ?? readRemembered(storageKey));
        setActivePatientId(id);
        if (id) remember(storageKey, id);
        return id;
      });
    } catch {
      setError('Patients could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [storageKey]);

  useEffect(() => {
    if (isAuthenticated) {
      void load();
    } else {
      setActivePatientId(null);
      setPatients([]);
      setActiveId(null);
    }
  }, [isAuthenticated, load]);

  const createPatient = useCallback(async (input: NewPatientInput) => {
    const created = await api.post<PatientSummary>('/api/v1/patients', {
      name: input.name,
      patient_code: input.patient_code,
      ...(parseAge(input.age) !== null ? { age: parseAge(input.age) } : {}),
      ...(input.sex ? { sex: input.sex } : {}),
      ...(input.phone ? { phone: input.phone } : {}),
    });
    setPatients((prev) => [...prev, created]);
    activate(created.id);
    return created;
  }, [activate]);

  const value = useMemo<PatientContextValue>(() => ({
    patients,
    activePatient: patients.find((p) => p.id === activeId) ?? null,
    loading,
    error,
    selectPatient: activate,
    createPatient,
    refreshPatients: load,
  }), [patients, activeId, loading, error, activate, createPatient, load]);

  return <PatientContext.Provider value={value}>{children}</PatientContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePatients(): PatientContextValue {
  const ctx = useContext(PatientContext);
  if (!ctx) throw new Error('usePatients must be used within PatientProvider');
  return ctx;
}
