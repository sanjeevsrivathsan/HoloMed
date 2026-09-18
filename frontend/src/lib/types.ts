export type Role = 'patient' | 'clinician' | 'administrator';

export type AppTheme = 'system' | 'light' | 'dark';
export type ImagingTheme = 'follow' | 'dark' | 'light';

/** Stored report lifecycle (backend). 'ready' and 'completed' are legacy values. */
export type ReportStatus =
  | 'uploaded'
  | 'processing'
  | 'extracted'
  | 'needs_review'
  | 'partially_confirmed'
  | 'confirmed'
  | 'completed'
  | 'failed'
  | 'ready';

/** Document processing, independent of review. */
export type ProcessingStatus = 'processing' | 'processed' | 'failed';
/** User review of the report date and extracted values. */
export type ReviewStatus = 'needs_review' | 'partially_confirmed' | 'confirmed';
/** Where the report date came from. */
export type DateSource = 'upload_default' | 'user_entered' | 'extracted' | 'user_override';
export type ReportType =
  | 'Blood Test'
  | 'Imaging Report'
  | 'Discharge Summary'
  | 'Clinical Note'
  | 'Prescription'
  | 'Pathology'
  | 'Consultation'
  | 'Operative Report'
  | 'Other';

export type StorageProvider = 'local' | 'google_drive' | 'onedrive' | 'dropbox' | 'hospital' | 'messaging';
export type StorageConnectionStatus = 'connected' | 'not_connected' | 'coming_soon';

export type SummaryMode = 'quick' | 'standard' | 'detailed' | 'clinical' | 'custom';

export type MeasurementFlag = 'normal' | 'high' | 'low' | 'abnormal' | 'unknown';

export type Modality = 'CT' | 'MRI' | 'X-Ray' | 'Ultrasound' | 'Mammography' | 'PET';

export interface UserProfile {
  id: string;
  email: string;
  displayName: string;
  role: Role;
  avatarUrl?: string;
  /** Whether a Google identity is linked to this account (from /api/v1/auth/me). */
  googleLinked?: boolean;
}

export interface Patient {
  id: string;
  fullName: string;
  dateOfBirth: string;
  gender: string;
  mrn: string;
}

export interface ReportArtifact {
  id: string;
  reportId: string;
  type: 'original_pdf' | 'extracted_markdown' | 'structured_data' | 'ai_summary' | 'template_export';
  storageProvider: StorageProvider;
  storageLocation: string;
  createdAt: string;
}

export interface MedicalMeasurement {
  id: string;
  reportId: string;
  patientId: string;
  testName: string;
  value: number;
  unit: string;
  referenceRange?: string;
  flag: MeasurementFlag;
  reportDate: string;
  hospital?: string;
  laboratory?: string;
  department?: string;
  comments?: string;
  sourceLocation?: string;
}

export interface ReportSummarySection {
  key: string;
  label: string;
  content: string;
  visible: boolean;
  /** "ai" = written by the language model; "data" = copied from confirmed report data. */
  source?: 'ai' | 'data';
}

export interface ReportSummary {
  id: string;
  reportId: string;
  mode: SummaryMode;
  sections: ReportSummarySection[];
  createdAt: string;
  /** Mandatory notice returned by the backend with every AI summary. */
  safetyMessage?: string;
  /** "language-model" or "structured-data" (no model used). */
  generator?: string | null;
}

export interface Report {
  id: string;
  patientId: string;
  type: ReportType;
  title: string;
  source: string;
  hospital?: string;
  laboratory?: string;
  department?: string;
  doctor?: string;
  date: string;
  status: ReportStatus;
  artifacts: ReportArtifact[];
  summary?: ReportSummary;
  originalFilename?: string;
  mimeType?: string;
  fileSize?: number;
  uploadedAt?: string;
  extractionStatus?: string | null;
  /** Extracted values not rejected during review. */
  candidateCount?: number;
  /** Confirmed canonical measurements linked to this report. */
  measurementCount?: number;
  processingStatus?: ProcessingStatus;
  reviewStatus?: ReviewStatus | null;
  dateConfirmed?: boolean;
  dateSource?: DateSource | null;
  /** Date suggested from the document (ISO), kept after a user override. */
  detectedDate?: string | null;
  pendingCount?: number;
  ignoredCount?: number;
}

export interface ImagingSeries {
  id: string;
  modality: string | null;
  description: string | null;
  instanceCount: number;
  rows: number | null;
  columns: number | null;
}

export interface ImagingStudy {
  id: string;
  patientId: string;
  accessionNumber: string;
  modality: Modality;
  description: string;
  studyDate: string;
  bodyPart: string;
  seriesCount: number;
  deidentified: boolean;
  reportText?: string;
  status: 'available' | 'pending' | 'integration_required';
  /** First series / instance (what OHIF opens and what AI screening analyzes). */
  seriesInstanceUid?: string | null;
  sopInstanceUid?: string | null;
  instanceCount?: number;
  /** Every series of the study in storage order; the first is the default one OHIF opens. */
  series?: ImagingSeries[];
  rows?: number | null;
  columns?: number | null;
  uploadedAt?: string | null;
  latestAnalysis?: {
    id: string;
    primaryPathology: string;
    primaryScore: number;
    createdAt: string;
  } | null;
}

export interface TemplateSection {
  id: string;
  label: string;
  order: number;
  visible: boolean;
  grouped?: string;
}

export interface Template {
  id: string;
  name: string;
  category: 'Patient' | 'Clinical' | 'Hospital' | 'Laboratory' | 'Custom';
  description: string;
  sections: TemplateSection[];
  updatedAt: string;
}

export interface ConsentRecord {
  id: string;
  patientId: string;
  recipient: string;
  purpose: string;
  scope: 'Reports' | 'Imaging' | 'Reports & Imaging';
  issuedDate: string;
  expiryDate: string;
  revoked: boolean;
}

export interface AuditEvent {
  id: string;
  patientId: string;
  eventType: string;
  description: string;
  timestamp: string;
  actor: string;
}

export interface StorageConnection {
  provider: StorageProvider;
  label: string;
  status: StorageConnectionStatus;
  isPrimary?: boolean;
  description: string;
}

export interface StorageDestination {
  artifactType: ReportArtifact['type'];
  primaryStorage: StorageProvider;
  deliveryDestinations: StorageProvider[];
}

export interface SourceReference {
  id: string;
  reportId: string;
  label: string;
  location: string;
  type: 'document' | 'measurement' | 'image';
}

export interface OllamaConfig {
  baseUrl: string;
  model: string;
  available: boolean;
}

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  variant: 'info' | 'success' | 'warning' | 'error';
}
