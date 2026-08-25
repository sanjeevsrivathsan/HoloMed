/**
 * App.tsx — root workspace component.
 *
 * Integration status per feature:
 *   ✅ Authentication    — real backend (AuthContext)
 *   ✅ Imaging studies   — fetched from GET /api/v1/dicomweb/studies (QIDO-RS)
 *   🔶 Reports          — demo data (no backend Report CRUD endpoint yet)
 *   🔶 Measurements     — demo data (no backend Measurements endpoint yet)
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
import { Reports, type UploadStage } from '@/pages/Reports';
import { HealthSearch } from '@/pages/HealthSearch';
import { HealthTimeline } from '@/pages/HealthTimeline';
import { Imaging } from '@/pages/Imaging';
import { Templates } from '@/pages/Templates';
import { ClinicalView } from '@/pages/ClinicalView';
import { PrivacyCenter } from '@/pages/PrivacyCenter';
import { StorageDelivery } from '@/pages/StorageDelivery';
import { Settings } from '@/pages/Settings';
import {
  demoPatient, demoReports, demoMeasurements,
  demoTemplates, demoConsents, demoAuditEvents,
  demoStorageConnections, demoSourceReferences,
} from '@/lib/demo-data';
import { api, ApiError, type StudyMeta, type PatientResponse } from '@/lib/api';
import type { ImagingStudy, Template, Report, ReportStatus } from '@/lib/types';

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
  const [uploadStage, setUploadStage] = useState<UploadStage | null>(null);

  // ── Templates (local state — no backend yet) ─────────────────────────────
  const [templates, setTemplates] = useState<Template[]>(demoTemplates);

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
      const reportsData = await api.get<any[]>('/api/v1/reports');
      const mappedReports: Report[] = reportsData.map((r) => ({
        id: String(r.id),
        patientId: String(r.patient_id),
        type: r.type,
        title: r.title,
        source: r.source,
        hospital: r.hospital,
        laboratory: r.laboratory,
        department: r.department,
        doctor: r.doctor,
        date: r.report_date,
        status: r.status as ReportStatus,
        artifacts: [], // Server doesn't return artifacts yet
      }));
      setReports(mappedReports);
      if (!selectedReportId && mappedReports.length > 0) {
        setSelectedReportId(mappedReports[0].id);
      }

      // Fetch patients to get display name
      const patients = await api.get<PatientResponse[]>('/api/v1/medical-data/patients');
      if (patients.length > 0) {
        setPatientDisplayName(patients[0].display_name);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      console.warn('[App] Could not load backend data:', err);
      setStudies([]);
      setReports([]);
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

  // ── Report upload (real API) ─────────
  const handleUpload = useCallback(async (file: File, _storage: string) => {
    setUploadStage('uploading');
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', file.name.replace(/\.[^/.]+$/, ""));
    formData.append('type', 'Other');
    
    try {
      const response = await fetch('/api/v1/reports', {
        method: 'POST',
        body: formData,
        // No headers needed, fetch will automatically set multipart/form-data boundary
      });
      
      if (!response.ok) {
        throw new Error('Upload failed');
      }
      
      setUploadStage('ready');
      await fetchBackendData();
      
      setTimeout(() => setUploadStage(null), 2000);
    } catch (err) {
      console.error('[App] Upload failed:', err);
      setUploadStage('failed');
      setTimeout(() => setUploadStage(null), 3000);
    }
  }, [fetchBackendData]);

  // ── Template save (local state — no backend yet) ─────────────────────────
  const handleSaveTemplate = useCallback((template: Template) => {
    setTemplates((prev) => {
      const existing = prev.findIndex((t) => t.id === template.id);
      if (existing >= 0) {
        const updated = [...prev];
        updated[existing] = template;
        return updated;
      }
      return [...prev, template];
    });
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
  // Patient display name: prioritize backend patient, then auth user displayName, then demo fallback
  const finalPatientName = patientDisplayName || (user ? user.displayName : demoPatient.fullName);

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
              ollamaAvailable={false}
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
          ollamaAvailable={false}
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
              measurements={demoMeasurements}
              auditEvents={demoAuditEvents}
              patientName={finalPatientName}
              onNavigate={handleNavigate}
              onOpenReport={handleOpenReport}
            />
          )}
          {currentPage === 'reports' && (
            <Reports
              reports={reports}
              selectedReportId={selectedReportId}
              onSelectReport={setSelectedReportId}
              onUpload={handleUpload}
              uploadStage={uploadStage}
              onNavigateClinical={handleNavigateClinical}
            />
          )}
          {currentPage === 'search' && (
            <HealthSearch
              reports={reports}
              measurements={demoMeasurements}
              sourceReferences={demoSourceReferences}
              onSelectReport={handleOpenReport}
            />
          )}
          {currentPage === 'timeline' && (
            <HealthTimeline
              measurements={demoMeasurements}
              reports={reports}
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
              measurements={demoMeasurements}
              studies={studies}
              onOpenImaging={() => handleNavigate('imaging')}
            />
          )}
          {currentPage === 'privacy' && (
            <PrivacyCenter
              consents={demoConsents}
              auditEvents={demoAuditEvents}
              storageConnections={demoStorageConnections}
            />
          )}
          {currentPage === 'storage' && (
            <StorageDelivery
              storageConnections={demoStorageConnections}
            />
          )}
          {currentPage === 'settings' && <Settings />}
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
