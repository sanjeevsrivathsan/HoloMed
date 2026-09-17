/**
 * App.tsx — root workspace component.
 *
 * Integration status per feature:
 *   ✅ Authentication    — real backend (AuthContext)
 *   ✅ Imaging studies   — fetched from GET /api/v1/dicomweb/studies (QIDO-RS)
 *   ✅ Reports          — /api/v1/reports (upload → extraction → review → summary)
 *   ✅ Measurements     — /api/v1/measurements (values confirmed during report review)
 *   🔶 Templates        — local state (no backend Template endpoint yet)
 *   🔶 Consents/Audit   — demo data (no backend Consent/read-audit endpoint yet)
 *   🔶 Storage          — demo data (no backend Storage management endpoint yet)
 *
 * Demo data is explicit and labelled — it is NOT being presented as real data.
 * Replace each section as the corresponding backend endpoint is implemented.
 */

import { useState, useCallback, useEffect } from 'react';
import { ThemeProvider } from '@/context/ThemeContext';
import { ToastProvider } from '@/context/ToastContext';
import { AuthProvider, useAuth } from '@/context/AuthContext';
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

import { api, ApiError, type StudyMeta, type PatientResponse } from '@/lib/api';
import type { ImagingStudy, Template, Report, ReportStatus, AuditEvent, MedicalMeasurement, ConsentRecord, StorageConnection, SourceReference } from '@/lib/types';
import { isProcessing, summaryFromBackend } from '@/lib/reports';

const POLL_INTERVAL_MS = 1500;

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

// ── Map QIDO StudyMeta → frontend ImagingStudy shape ─────────────────────────

function studyMetaToImaging(s: StudyMeta, index: number): ImagingStudy {
  return {
    id: s.StudyInstanceUID,
    patientId: '',                         // not returned by QIDO endpoint
    accessionNumber: `ACC-${index + 1}`,   // backend doesn't expose this yet
    modality: (s.Modality ?? 'Unknown') as ImagingStudy['modality'],
    description: s.Description ?? s.Modality ?? 'Imaging Study',
    studyDate: s.CreatedDate.split('T')[0],
    bodyPart: 'Unknown',                   // not returned by QIDO endpoint
    seriesCount: 0,                        // not returned by QIDO endpoint
    deidentified: false,
    status: 'available',
  };
}

// ── Workspace (rendered after authentication) ─────────────────────────────────

function Workspace() {
  const { isAuthenticated, loading: authLoading, user } = useAuth();

  // ── Page navigation ──────────────────────────────────────────────────────
  const [currentPage, setCurrentPage] = useState<PageKey>('imaging');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // ── Reports (now from backend) ─────────────────────────────────────────
  const [reports, setReports] = useState<Report[]>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [clinicalReportId, setClinicalReportId] = useState<string | null>(null);

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

  // ── Patient profile — fetched from backend ───────────────────────────────
  const [patientDisplayName, setPatientDisplayName] = useState<string | null>(null);

  const fetchBackendData = useCallback(async () => {
    setStudiesLoading(true);
    setReportsLoading(true);
    try {
      // Fetch studies
      const data = await api.get<StudyMeta[]>('/api/v1/dicomweb/studies');
      const mapped = data.map(studyMetaToImaging);
      setStudies(mapped);
      if (!selectedStudyId && mapped.length > 0) {
        setSelectedStudyId(mapped[0].id);
      }

      // Fetch reports
      const reportsData = await api.get<unknown[]>('/api/v1/reports');
      const mappedReports = reportsData.map(reportFromBackend);
      setReports(mappedReports);
      if (!selectedReportId && mappedReports.length > 0) {
        setSelectedReportId(mappedReports[0].id);
      }

      // Fetch patients to get display name
      const patients = await api.get<PatientResponse[]>('/api/v1/medical-data/patients');
      if (patients.length > 0) {
        setPatientDisplayName(patients[0].display_name);
      }

      // Fetch audit logs
      const auditData = await api.get<unknown[]>('/api/v1/audit');
      setAuditEvents(auditData.map(auditFromBackend));

      // Fetch measurements
      const measData = await api.get<unknown[]>('/api/v1/measurements');
      setMeasurements(measData.map(measurementFromBackend));

      // Fetch templates
      const tmplData = await api.get<any[]>('/api/v1/templates');
      const mappedTmpls: Template[] = tmplData.map(t => ({
        id: String(t.id),
        name: t.name,
        category: t.category as any,
        description: t.description,
        sections: typeof t.sections === 'string' ? JSON.parse(t.sections) : t.sections,
        updatedAt: t.updated_at
      }));
      setTemplates(mappedTmpls);

      // Fetch Consents
      const consData = await api.get<any[]>('/api/v1/consents');
      const mappedCons: ConsentRecord[] = consData.map(c => ({
        id: String(c.id),
        patientId: String(c.patient_id),
        recipient: c.recipient,
        purpose: c.purpose,
        scope: c.scope as any,
        issuedDate: c.issued_date,
        expiryDate: c.expiry_date,
        revoked: c.revoked
      }));
      setConsents(mappedCons);

      // Fetch Storage Connections
      const storageData = await api.get<any[]>('/api/v1/storage-connections');
      const mappedStorage: StorageConnection[] = storageData.map(s => ({
        provider: s.provider as any,
        label: s.label,
        status: s.status as any,
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
  }, [selectedStudyId, selectedReportId]);

  // Fetch data once the user is authenticated
  useEffect(() => {
    if (isAuthenticated) {
      void fetchBackendData();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

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

  // ── Navigation handlers ──────────────────────────────────────────────────
  const handleNavigate = useCallback((page: PageKey) => {
    setCurrentPage(page);
    setMobileSidebarOpen(false);
  }, []);

  const handleOpenReport = useCallback((reportId: string) => {
    setSelectedReportId(reportId);
    setCurrentPage('reports');
  }, []);

  const handleNavigateClinical = useCallback((reportId: string) => {
    setClinicalReportId(reportId);
    setCurrentPage('clinical');
  }, []);

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
        const res = await api.post<any>('/api/v1/templates', payload);
        savedTemplate = { ...template, id: String(res.id), updatedAt: res.updated_at };
      } else {
        const res = await api.put<any>(`/api/v1/templates/${template.id}`, payload);
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

  const clinicalReport = reports.find((r) => r.id === clinicalReportId) || null;
  // Patient display name: prioritize backend patient, then auth user displayName, then default fallback
  const finalPatientName = patientDisplayName || (user ? user.displayName : 'Patient');

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
          patientName={finalPatientName}
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
              onSelectReport={setSelectedReportId}
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
              studies={studies}
              studiesLoading={studiesLoading}
              selectedStudyId={selectedStudyId}
              onSelectStudy={setSelectedStudyId}
              onStudyUploaded={fetchBackendData}
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
          <Workspace />
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
