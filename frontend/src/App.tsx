import { useState, useCallback } from 'react';
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
  demoPatient, demoReports, demoMeasurements, demoImagingStudies,
  demoTemplates, demoConsents, demoAuditEvents, demoStorageConnections,
  demoSourceReferences,
} from '@/lib/demo-data';
import type { Template } from '@/lib/types';

function Workspace() {
  const { isAuthenticated } = useAuth();
  const [currentPage, setCurrentPage] = useState<PageKey>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(demoReports[0]?.id || null);
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(demoImagingStudies[0]?.id || null);
  const [clinicalReportId, setClinicalReportId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<Template[]>(demoTemplates);
  const [uploadStage, setUploadStage] = useState<UploadStage | null>(null);

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

  const handleUpload = useCallback((_file: File, _storage: string) => {
    setUploadStage('uploading');
    const stages: UploadStage[] = ['uploading', 'extracting', 'ocr', 'structured', 'ready'];
    let idx = 0;
    const interval = setInterval(() => {
      idx++;
      if (idx < stages.length) {
        setUploadStage(stages[idx]);
      } else {
        setUploadStage('ready');
        clearInterval(interval);
        setTimeout(() => setUploadStage(null), 2000);
      }
    }, 1200);
  }, []);

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

  if (!isAuthenticated) {
    return <AuthScreen />;
  }

  const clinicalReport = demoReports.find((r) => r.id === clinicalReportId) || null;

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
          patientName={demoPatient.fullName}
        />
        <main className="flex-1 p-4 sm:p-6">
          {currentPage === 'dashboard' && (
            <Dashboard
              reports={demoReports}
              studies={demoImagingStudies}
              measurements={demoMeasurements}
              auditEvents={demoAuditEvents}
              patientName={demoPatient.fullName}
              onNavigate={handleNavigate}
              onOpenReport={handleOpenReport}
            />
          )}
          {currentPage === 'reports' && (
            <Reports
              reports={demoReports}
              selectedReportId={selectedReportId}
              onSelectReport={setSelectedReportId}
              onUpload={handleUpload}
              uploadStage={uploadStage}
              onNavigateClinical={handleNavigateClinical}
            />
          )}
          {currentPage === 'search' && (
            <HealthSearch
              reports={demoReports}
              measurements={demoMeasurements}
              sourceReferences={demoSourceReferences}
              onSelectReport={handleOpenReport}
            />
          )}
          {currentPage === 'timeline' && (
            <HealthTimeline
              measurements={demoMeasurements}
              reports={demoReports}
            />
          )}
          {currentPage === 'imaging' && (
            <Imaging
              studies={demoImagingStudies}
              selectedStudyId={selectedStudyId}
              onSelectStudy={setSelectedStudyId}
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
              studies={demoImagingStudies}
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
