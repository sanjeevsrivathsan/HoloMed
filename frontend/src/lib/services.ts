import type {
  OllamaConfig,
  Report,
  ReportSummary,
  StorageConnection,
  ImagingStudy,
  SummaryMode,
} from './types';

export interface OllamaService {
  healthCheck(): Promise<{ available: boolean; model?: string; error?: string }>;
  summarizeReport(reportId: string, mode: SummaryMode, sections?: string[]): Promise<ReportSummary>;
  askQuestion(reportId: string, question: string): Promise<{ answer: string }>;
}

export interface PdfPipelineService {
  convertToMarkdown(reportId: string): Promise<{ markdown: string; usedOcr: boolean }>;
  extractStructuredData(reportId: string): Promise<Record<string, unknown>>;
}

export interface GoogleDriveService {
  authenticate(): Promise<{ connected: boolean; error?: string }>;
  upload(reportId: string, file: Blob): Promise<{ fileId: string }>;
  download(fileId: string): Promise<Blob>;
  list(): Promise<{ id: string; name: string; modifiedTime: string }[]>;
  delete(fileId: string): Promise<void>;
}

export interface OhifViewerService {
  launch(studyId: string): Promise<{ url: string }>;
  embed(studyId: string): Promise<{ embedUrl: string }>;
}

// --- Demo implementations (replaceable with FastAPI/local backend later) ---
export function getOllamaConfig(): OllamaConfig {
  return {
    baseUrl: 'http://localhost:11434',
    model: 'llama3.1:8b',
    available: false,
  };
}

export function getStorageConnections(): StorageConnection[] {
  return [
    { provider: 'local', label: 'Local Storage', status: 'connected', isPrimary: true, description: 'Files stored on this device' },
    { provider: 'google_drive', label: 'Google Drive', status: 'not_connected', description: 'OAuth integration — server credentials required' },
    { provider: 'onedrive', label: 'OneDrive', status: 'coming_soon', description: 'Cloud storage integration' },
    { provider: 'dropbox', label: 'Dropbox', status: 'coming_soon', description: 'Cloud storage integration' },
    { provider: 'hospital', label: 'Hospital Storage', status: 'coming_soon', description: 'Direct hospital PACS integration' },
    { provider: 'messaging', label: 'Secure Messaging', status: 'coming_soon', description: 'Delivery to healthcare providers' },
  ];
}

export function getReportById(reports: Report[], id: string): Report | undefined {
  return reports.find((r) => r.id === id);
}

export function getStudyById(studies: ImagingStudy[], id: string): ImagingStudy | undefined {
  return studies.find((s) => s.id === id);
}
