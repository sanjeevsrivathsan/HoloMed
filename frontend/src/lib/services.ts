import type {
  OllamaConfig,
  Report,
  ReportSummary,
  StorageConnection,
  ImagingStudy,
  SummaryMode,
  ReportSummarySection,
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

export const demoOllamaService: OllamaService = {
  async healthCheck() {
    return { available: false, error: 'Ollama not running on localhost:11434' };
  },
  async summarizeReport(reportId, mode, sections) {
    await new Promise((r) => setTimeout(r, 1200));
    const allSections: ReportSummarySection[] = [
      { key: 'executive', label: 'Executive Summary', content: 'Demo summary generated. This is a placeholder — connect Ollama to generate real summaries.', visible: true },
      { key: 'findings', label: 'Important Findings', content: 'No findings available in demo mode.', visible: true },
      { key: 'abnormal', label: 'Reported Abnormal Values', content: 'No abnormal values in demo mode.', visible: true },
      { key: 'normal', label: 'Normal Values', content: 'No normal values in demo mode.', visible: true },
      { key: 'terms', label: 'Medical Terms', content: 'No terms extracted in demo mode.', visible: true },
      { key: 'questions', label: 'Questions for Doctor', content: 'No questions generated in demo mode.', visible: true },
    ];
    const filtered = sections
      ? allSections.filter((s) => sections.includes(s.key))
      : allSections;
    return {
      id: `sum_${reportId}_${Date.now()}`,
      reportId,
      mode,
      sections: filtered,
      createdAt: new Date().toISOString(),
    };
  },
  async askQuestion(_reportId, _question) {
    await new Promise((r) => setTimeout(r, 800));
    return { answer: 'Demo mode: Ollama is not connected. This is a placeholder answer.' };
  },
};

export const demoPdfPipeline: PdfPipelineService = {
  async convertToMarkdown(_reportId) {
    await new Promise((r) => setTimeout(r, 1500));
    return {
      markdown: '## Demo Extracted Content\n\nThis is a placeholder for the MarkItDown extraction pipeline. Connect a FastAPI backend to process real PDFs.\n\n**Findings:**\n- No acute findings (demo)\n- Values within normal range (demo)',
      usedOcr: false,
    };
  },
  async extractStructuredData(_reportId) {
    await new Promise((r) => setTimeout(r, 1000));
    return { demo: true, message: 'Structured extraction requires backend pipeline.' };
  },
};

export const demoGoogleDrive: GoogleDriveService = {
  async authenticate() {
    return { connected: false, error: 'Google Drive OAuth requires server-side credentials.' };
  },
  async upload() {
    throw new Error('Google Drive not connected — OAuth integration required.');
  },
  async download() {
    throw new Error('Google Drive not connected — OAuth integration required.');
  },
  async list() {
    return [];
  },
  async delete() {
    throw new Error('Google Drive not connected — OAuth integration required.');
  },
};

export const demoOhifViewer: OhifViewerService = {
  async launch(studyId) {
    return { url: `/ohif/viewer?StudyInstanceUIDs=${studyId}` };
  },
  async embed(studyId) {
    return { embedUrl: `/ohif/embed?StudyInstanceUIDs=${studyId}` };
  },
};

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
