/**
 * App.tsx — root workspace component.
 *
 * Integration status per feature:
 *   ✅ Authentication    — real backend (AuthContext)
 *   ✅ Patients          — PatientContext (GET/POST /api/v1/patients); every request carries the active patient
 *   ✅ Imaging studies   — GET /api/v1/patients/{id}/imaging (the active patient's stored DICOM)
 *   ✅ Reports          — /api/v1/reports (upload → extraction → review → summary)
 *   ✅ Measurements     — /api/v1/measurements (values confirmed during report review)
 *   🔶 Templates        — local state (no backend Template endpoint yet)
 *   🔶 Consents/Audit   — demo data (no backend Consent/read-audit endpoint yet)
 *   🔶 Storage          — demo data (no backend Storage management endpoint yet)
 *
 * Demo data is explicit and labelled — it is NOT being presented as real data.
 * Replace each section as the corresponding backend endpoint is implemented.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { ThemeProvider } from '@/context/ThemeContext';
import { ToastProvider } from '@/context/ToastContext';
import { AuthProvider, useAuth } from '@/context/AuthContext';
import { PatientProvider, usePatients } from '@/context/PatientContext';
import { AuthScreen } from '@/components/AuthScreen';
import { Sidebar, type PageKey } from '@/components/Sidebar';
import { Topbar } from '@/components/Topbar';
import { ToastContainer } from '@/components/Toast';
import { Dashboard } from '@/pages/Dashboard';
import { Reports } from '@/pages/Reports';
import { HealthSearch } from '@/pages/HealthSearch';
import { HealthTimeline } from '@/pages/HealthTimeline';
import { Imaging } from '@/pages/Imaging';
import { Templates } from '@/pages/Templates';
import { ClinicalView } from '@/pages/ClinicalView';
import { PrivacyCenter } from '@/pages/PrivacyCenter';
import { StorageDelivery } from '@/pages/StorageDelivery';
import { Settings } from '@/pages/Settings';

import { api, ApiError, type PatientImagingStudy } from '@/lib/api';
import { pickViewerStudy } from '@/lib/imagingStudies';
import type { ImagingStudy, Template, Report, ReportStatus, AuditEvent, MedicalMeasurement, ConsentRecord, StorageConnection, SourceReference } from '@/lib/types';
import { isProcessing, summaryFromBackend } from '@/lib/reports';
import { formatRoute, parseRoute, sameRoute, type AppRoute } from '@/lib/routing';

const POLL_INTERVAL_MS = 1500;

interface TemplateRow { id: number; name: string; category: string; description: string; sections: string | Template['sections']; updated_at: string }
interface ConsentRow { id: number; patient_id: number; recipient: string; purpose: string; scope: string; issued_date: string; expiry_date: string; revoked: boolean }
interface StorageRow { provider: string; label: string; status: string; is_primary?: boolean; description: string }

/** Backend timestamps are naive UTC. */
const utc = (value: string | null | undefined) =>
  value && !/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? `${value}Z` : value ?? undefined;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function reportFromBackend(r: any): Report {
  const id = String(r.id);
  const summary = summaryFromBackend(id, r.summary);
  return {
    id,
    patientId: String(r.patient_id),
    title: r.title,
    type: r.type,
    source: r.source,
    hospital: r.hospital ?? undefined,
    laboratory: r.laboratory ?? undefined,
    department: r.department ?? undefined,
    doctor: r.doctor ?? undefined,
    date: r.report_date,
    status: r.status as ReportStatus,
    artifacts: [],
    summary: summary && { ...summary, createdAt: utc(summary.createdAt) ?? summary.createdAt },
    originalFilename: r.original_filename,
    mimeType: r.mime_type,
    fileSize: r.file_size,
    uploadedAt: utc(r.uploaded_at),
    extractionStatus: r.extraction_status ?? null,
    candidateCount: r.candidate_count ?? 0,
    measurementCount: r.measurement_count ?? 0,
    processingStatus: r.processing_status,
    reviewStatus: r.review_status ?? null,
    dateConfirmed: r.date_confirmed,
    dateSource: r.date_source ?? null,
    detectedDate: r.detected_date ?? null,
    pendingCount: r.pending_count ?? 0,
    ignoredCount: r.ignored_count ?? 0,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function measurementFromBackend(m: any): MedicalMeasurement {
  return {
    id: String(m.id),
    reportId: m.report_id ? String(m.report_id) : '',
    patientId: String(m.patient_id),
    testName: m.test_name,
    value: m.value,
    unit: m.unit,
    referenceRange: m.reference_range ?? undefined,
    flag: m.flag,
    reportDate: m.report_date,
    hospital: m.hospital ?? undefined,
    laboratory: m.laboratory ?? undefined,
    department: m.department ?? undefined,
    comments: m.comments ?? undefined,
    sourceLocation: m.source_location ?? undefined,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function sourceReferenceFromBackend(sr: any): SourceReference {
  return {
    id: String(sr.id),
    reportId: String(sr.report_id),
    label: 'Original document',
    location: `Report #${sr.report_id} · stored unchanged`,
    type: sr.type,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function auditFromBackend(log: any): AuditEvent {
  return {
    id: String(log.id),
    patientId: String(log.user_id),
    eventType: log.action.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase()),
    description: log.details || 'No details provided',
    timestamp: utc(log.timestamp) ?? log.timestamp,
    actor: 'user',
  };
}

// ── Map a patient's stored study → frontend ImagingStudy shape ───────────────

function imagingFromBackend(patientId: string, s: PatientImagingStudy, index: number): ImagingStudy {
  const first = s.series[0];
  return {
    id: s.study_instance_uid,
    patientId,
    accessionNumber: `ACC-${index + 1}`,
    modality: (s.modality ?? 'Unknown') as ImagingStudy['modality'],
    description: s.description ?? s.modality ?? 'Imaging Study',
    studyDate: s.study_date ?? (s.uploaded_at ?? '').slice(0, 10),
    bodyPart: 'Unknown',
    seriesCount: s.series_count,
    deidentified: false,
    status: 'available',
    seriesInstanceUid: first?.series_instance_uid ?? null,
    sopInstanceUid: first?.first_sop_instance_uid ?? null,
    instanceCount: s.instance_count,
    series: s.series.map((se) => ({
      id: se.series_instance_uid, modality: se.modality, description: se.description,
      instanceCount: se.instance_count, rows: se.rows, columns: se.columns,
    })),
    rows: first?.rows ?? null,
    columns: first?.columns ?? null,
    uploadedAt: utc(s.uploaded_at) ?? null,
    latestAnalysis: s.latest_analysis && {
      id: s.latest_analysis.id,
      primaryPathology: s.latest_analysis.primary_pathology,
      primaryScore: s.latest_analysis.primary_score,
      createdAt: s.latest_analysis.created_at,
    },
  };
}

// ── Workspace (rendered after authentication) ─────────────────────────────────

function Workspace() {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const { activePatient, error: patientsError, refreshPatients } = usePatients();
  const patientId = activePatient?.id ?? null;

  // ── Page navigation ──────────────────────────────────────────────────────
  // Workspace route is mirrored in the URL (History API): Back/Forward, refresh and deep links work.
  const [initialRoute] = useState<AppRoute>(() => parseRoute(window.location.pathname));
  const [currentPage, setCurrentPage] = useState<PageKey>(initialRoute.page);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // ── Reports (now from backend) ─────────────────────────────────────────
  const [reports, setReports] = useState<Report[]>([]);
  const [, setReportsLoading] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(
    initialRoute.page === 'reports' ? initialRoute.reportId : null);
  const [clinicalReportId, setClinicalReportId] = useState<string | null>(
    initialRoute.page === 'clinical' ? initialRoute.reportId : null);

  // ── Audit Logs (from backend) ──────────────────────────────────────────
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);

  // ── Measurements (from backend) ──────────────────────────────────────────
  const [measurements, setMeasurements] = useState<MedicalMeasurement[]>([]);

  // ── Templates (from backend) ─────────────────────────────
  const [templates, setTemplates] = useState<Template[]>([]);

  // ── Consents & Storage Connections (from backend) ────────────────────────
  const [consents, setConsents] = useState<ConsentRecord[]>([]);
  const [storageConnections, setStorageConnections] = useState<StorageConnection[]>([]);
  const [sourceReferences, setSourceReferences] = useState<SourceReference[]>([]);

  // ── Imaging studies — fetched from backend QIDO-RS ───────────────────────
  const [studies, setStudies] = useState<ImagingStudy[]>([]);
  const [studiesLoading, setStudiesLoading] = useState(false);
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(null);
  // Imaging mode lives here so it survives navigating away from Imaging and back.
  const [imagingMode, setImagingMode] = useState<'screening' | 'viewer'>('screening');

  // The active patient's imaging studies; keeps the preferred (e.g. just-uploaded) study selected.
  const refreshImaging = useCallback(async (preferredStudyId?: string | null, fresh = false) => {
    if (!patientId) return;
    setStudiesLoading(true);
    try {
      const data = await api.get<PatientImagingStudy[]>(`/api/v1/patients/${patientId}/imaging`);
      const mapped = data.map((s, i) => imagingFromBackend(patientId, s, i));
      setStudies(mapped);
      setSelectedStudyId((current) => pickViewerStudy(mapped, preferredStudyId ?? (fresh ? null : current)));
    } finally {
      setStudiesLoading(false);
    }
  }, [patientId]);

  const fetchBackendData = useCallback(async (preferredStudyId?: string, fresh = false) => {
    if (!patientId) return;
    setReportsLoading(true);
    try {
      await refreshImaging(preferredStudyId, fresh);

      // Fetch reports
      const reportsData = await api.get<unknown[]>('/api/v1/reports');
      const mappedReports = reportsData.map(reportFromBackend);
      setReports(mappedReports);
      if ((fresh || !selectedReportId) && mappedReports.length > 0) {
        setSelectedReportId(mappedReports[0].id);
        if (parseRoute(window.location.pathname).page === 'reports') {
          window.history.replaceState({ holomed: true }, '', formatRoute({ page: 'reports', reportId: mappedReports[0].id }));
        }
      }

      // Fetch audit logs
      const auditData = await api.get<unknown[]>('/api/v1/audit');
      setAuditEvents(auditData.map(auditFromBackend));

      // Fetch measurements
      const measData = await api.get<unknown[]>('/api/v1/measurements');
      setMeasurements(measData.map(measurementFromBackend));

      // Fetch templates
      const tmplData = await api.get<TemplateRow[]>('/api/v1/templates');
      const mappedTmpls: Template[] = tmplData.map(t => ({
        id: String(t.id),
        name: t.name,
        category: t.category as Template['category'],
        description: t.description,
        sections: typeof t.sections === 'string' ? JSON.parse(t.sections) : t.sections,
        updatedAt: t.updated_at
      }));
      setTemplates(mappedTmpls);

      // Fetch Consents
      const consData = await api.get<ConsentRow[]>('/api/v1/consents');
      const mappedCons: ConsentRecord[] = consData.map(c => ({
        id: String(c.id),
        patientId: String(c.patient_id),
        recipient: c.recipient,
        purpose: c.purpose,
        scope: c.scope as ConsentRecord['scope'],
        issuedDate: c.issued_date,
        expiryDate: c.expiry_date,
        revoked: c.revoked
      }));
      setConsents(mappedCons);

      // Fetch Storage Connections
      const storageData = await api.get<StorageRow[]>('/api/v1/storage-connections');
      const mappedStorage: StorageConnection[] = storageData.map(s => ({
        provider: s.provider as StorageConnection['provider'],
        label: s.label,
        status: s.status as StorageConnection['status'],
        isPrimary: s.is_primary,
        description: s.description
      }));
      setStorageConnections(mappedStorage);

      // Fetch Source References
      const srData = await api.get<unknown[]>('/api/v1/search/source-references');
      setSourceReferences(srData.map(sourceReferenceFromBackend));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      console.warn('[App] Could not load backend data:', err);
      setStudies([]);
      setReports([]);
      setAuditEvents([]);
      setMeasurements([]);
      setTemplates([]);
      setConsents([]);
      setStorageConnections([]);
    } finally {
      setStudiesLoading(false);
      setReportsLoading(false);
    }
  }, [patientId, refreshImaging, selectedReportId]);

  // Load the active patient's data; switching patients first clears the previous patient's data.
  const loadedPatient = useRef<string | null>(null);
  useEffect(() => {
    if (!isAuthenticated || !patientId) return;
    const switching = loadedPatient.current !== null && loadedPatient.current !== patientId;
    loadedPatient.current = patientId;
    if (switching) {
      setStudies([]);
      setSelectedStudyId(null);
      setReports([]);
      setSelectedReportId(null);
      setClinicalReportId(null);
      setMeasurements([]);
      setSourceReferences([]);
      setAuditEvents([]);
      setConsents([]);
      const page = parseRoute(window.location.pathname).page;
      if (page === 'reports' || page === 'clinical') {
        window.history.replaceState({ holomed: true }, '', formatRoute({ page, reportId: null }));
      }
    }
    void fetchBackendData(undefined, switching);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, patientId]);

  // Lightweight refresh of report-derived data (reports, measurements, sources, activity).
  const refreshReports = useCallback(async () => {
    try {
      const [reportsData, measData, srData, auditData] = await Promise.all([
        api.get<unknown[]>('/api/v1/reports'),
        api.get<unknown[]>('/api/v1/measurements'),
        api.get<unknown[]>('/api/v1/search/source-references'),
        api.get<unknown[]>('/api/v1/audit'),
      ]);
      setReports(reportsData.map(reportFromBackend));
      setMeasurements(measData.map(measurementFromBackend));
      setSourceReferences(srData.map(sourceReferenceFromBackend));
      setAuditEvents(auditData.map(auditFromBackend));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      console.warn('[App] Could not refresh reports');
    }
  }, []);

  // Text AI availability for the sidebar indicator (no URLs or credentials).
  const [textAiAvailable, setTextAiAvailable] = useState(false);
  useEffect(() => {
    if (!isAuthenticated) return;
    api.get<{ status: string }>('/api/v1/ai/status')
      .then((s) => setTextAiAvailable(s.status === 'connected' || s.status === 'configured'))
      .catch(() => setTextAiAvailable(false));
  }, [isAuthenticated, currentPage]);

  // Poll while any document is still being processed.
  const anyProcessing = reports.some((r) => isProcessing(r.status));
  useEffect(() => {
    if (!isAuthenticated || !anyProcessing) return;
    const timer = window.setInterval(() => { void refreshReports(); }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isAuthenticated, anyProcessing, refreshReports]);

  // ── Navigation (History API) ─────────────────────────────────────────────
  const applyRoute = useCallback((route: AppRoute) => {
    setCurrentPage(route.page);
    if (route.page === 'reports' && route.reportId) setSelectedReportId(route.reportId);
    if (route.page === 'clinical') setClinicalReportId(route.reportId);
  }, []);

  const navigate = useCallback((route: AppRoute, options: { replace?: boolean } = {}) => {
    const current = parseRoute(window.location.pathname);
    const url = formatRoute(route);
    if (options.replace || sameRoute(current, route)) {
      window.history.replaceState({ holomed: true }, '', url + window.location.hash);
    } else {
      window.history.pushState({ holomed: true }, '', url);
    }
    applyRoute(route);
    setMobileSidebarOpen(false);
  }, [applyRoute]);

  // Normalise the entry URL once (e.g. "/" → "/imaging") without adding history.
  useEffect(() => {
    const url = formatRoute(initialRoute);
    if (window.location.pathname !== url) {
      window.history.replaceState({ holomed: true }, '', url + window.location.search + window.location.hash);
    }
  }, [initialRoute]);

  useEffect(() => {
    const onPopState = () => applyRoute(parseRoute(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [applyRoute]);

  const handleNavigate = useCallback((page: PageKey) => {
    navigate({
      page,
      reportId: page === 'reports' ? selectedReportId : page === 'clinical' ? clinicalReportId : null,
    });
  }, [navigate, selectedReportId, clinicalReportId]);

  const handleOpenReport = useCallback((reportId: string) => {
    navigate({ page: 'reports', reportId });
  }, [navigate]);

  const handleNavigateClinical = useCallback((reportId: string) => {
    navigate({ page: 'clinical', reportId });
  }, [navigate]);

  const handleSelectReport = useCallback((reportId: string) => {
    navigate({ page: 'reports', reportId });
  }, [navigate]);

  // ── Template save (calls API) ─────────────────────────
  const handleSaveTemplate = useCallback(async (template: Template) => {
    try {
      const payload = {
        name: template.name,
        category: template.category,
        description: template.description,
        sections: JSON.stringify(template.sections)
      };

      let savedTemplate;
      // If template ID doesn't look like a real DB ID (e.g. 'new-123' or missing), POST it
      if (!template.id || template.id.startsWith('new') || template.id.startsWith('tpl_')) {
        const res = await api.post<TemplateRow>('/api/v1/templates', payload);
        savedTemplate = { ...template, id: String(res.id), updatedAt: res.updated_at };
      } else {
        const res = await api.put<TemplateRow>(`/api/v1/templates/${template.id}`, payload);
        savedTemplate = { ...template, id: String(res.id), updatedAt: res.updated_at };
      }

      setTemplates((prev) => {
        const existing = prev.findIndex((t) => t.id === savedTemplate.id);
        if (existing >= 0) {
          const updated = [...prev];
          updated[existing] = savedTemplate;
          return updated;
        }
        return [...prev, savedTemplate];
      });
      // Optionally re-fetch entirely
      // await fetchBackendData();
    } catch (err) {
      console.error('[App] Failed to save template', err);
    }
  }, []);

  // ── Render: while auth session is being restored, show nothing (no flash) ─
  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-neutral-50 dark:bg-neutral-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <AuthScreen />;
  }

  // Every page is patient-scoped: wait for the active patient instead of rendering without one.
  if (!activePatient) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-neutral-50 dark:bg-neutral-950">
        {patientsError ? (
          <>
            <p className="text-sm text-neutral-600 dark:text-neutral-300">{patientsError}</p>
            <button onClick={() => void refreshPatients()} className="rounded-lg bg-teal-600 px-3 py-1.5 text-sm font-medium text-white">
              Try again
            </button>
          </>
        ) : (
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" aria-label="Loading patient" />
        )}
      </div>
    );
  }

  const clinicalReport = reports.find((r) => r.id === clinicalReportId) || null;
  const finalPatientName = activePatient?.name ?? 'Patient';

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950">
      {/* Mobile sidebar overlay */}
      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileSidebarOpen(false)} />
          <div className="absolute left-0 top-0 h-full">
            <Sidebar
              currentPage={currentPage}
              onNavigate={handleNavigate}
              collapsed={false}
              onToggleCollapse={() => setMobileSidebarOpen(false)}
              ollamaAvailable={textAiAvailable}
            />
          </div>
        </div>
      )}

      {/* Desktop sidebar */}
      <div className="hidden lg:block">
        <Sidebar
          currentPage={currentPage}
          onNavigate={handleNavigate}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          ollamaAvailable={textAiAvailable}
        />
      </div>

      <div className={`flex flex-col min-h-screen ${sidebarCollapsed ? 'lg:pl-16' : 'lg:pl-60'}`}>
        <Topbar
          currentPage={currentPage}
          onMobileMenu={() => setMobileSidebarOpen(true)}
        />
        <main className="flex-1 p-4 sm:p-6">
          {currentPage === 'dashboard' && (
            <Dashboard
              reports={reports}
              studies={studies}
              measurements={measurements}
              auditEvents={auditEvents}
              patientName={finalPatientName}
              onNavigate={handleNavigate}
              onOpenReport={handleOpenReport}
            />
          )}
          {currentPage === 'reports' && (
            <Reports
              reports={reports}
              measurements={measurements}
              selectedReportId={selectedReportId}
              onSelectReport={handleSelectReport}
              onRefresh={refreshReports}
              onNavigateClinical={handleNavigateClinical}
              onNavigateTimeline={() => handleNavigate('timeline')}
            />
          )}
          {currentPage === 'search' && (
            <HealthSearch
              reports={reports}
              measurements={measurements}
              sourceReferences={sourceReferences}
              onSelectReport={handleOpenReport}
            />
          )}
          {currentPage === 'timeline' && (
            <HealthTimeline
              measurements={measurements}
              reports={reports}
              onOpenReport={handleOpenReport}
            />
          )}
          {currentPage === 'imaging' && (
            <Imaging
              patient={activePatient}
              mode={imagingMode}
              onModeChange={setImagingMode}
              studies={studies}
              studiesLoading={studiesLoading}
              selectedStudyId={selectedStudyId}
              onSelectStudy={setSelectedStudyId}
              onStudyUploaded={(uid) => void refreshImaging(uid)}
              onStudiesImported={(uid) => refreshImaging(uid)}
            />
          )}
          {currentPage === 'templates' && (
            <Templates
              templates={templates}
              onSaveTemplate={handleSaveTemplate}
            />
          )}
          {currentPage === 'clinical' && (
            <ClinicalView
              report={clinicalReport}
              measurements={measurements}
              studies={studies}
              onOpenImaging={() => handleNavigate('imaging')}
              onOpenReport={handleOpenReport}
            />
          )}
          {currentPage === 'privacy' && (
            <PrivacyCenter
              consents={consents}
              auditEvents={auditEvents}
              storageConnections={storageConnections}
            />
          )}
          {currentPage === 'storage' && (
            <StorageDelivery
              storageConnections={storageConnections}
            />
          )}
          {currentPage === 'settings' && <Settings onDataChanged={refreshReports} />}
        </main>
      </div>

      <ToastContainer />
    </div>
  );
}

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <PatientProvider>
            <Workspace />
          </PatientProvider>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
