import type {
  Patient,
  Report,
  MedicalMeasurement,
  ImagingStudy,
  Template,
  ConsentRecord,
  AuditEvent,
  StorageConnection,
  SourceReference,
  ReportSummary,
} from './types';

export const demoPatient: Patient = {
  id: 'pat_demo_001',
  fullName: 'Synthetic Demo Patient',
  dateOfBirth: '1979-04-12',
  gender: 'Female',
  mrn: 'DEMO-0001',
};

export const demoReports: Report[] = [
  {
    id: 'rep_001',
    patientId: 'pat_demo_001',
    type: 'Blood Test',
    title: 'Complete Blood Count & Metabolic Panel',
    source: 'Central Lab Diagnostics',
    laboratory: 'Central Lab Diagnostics',
    department: 'Hematology',
    doctor: 'Dr. A. Rivera',
    date: '2026-07-15',
    status: 'ready',
    artifacts: [
      { id: 'art_001a', reportId: 'rep_001', type: 'original_pdf', storageProvider: 'local', storageLocation: 'local://reports/rep_001.pdf', createdAt: '2026-07-15T10:00:00Z' },
      { id: 'art_001b', reportId: 'rep_001', type: 'extracted_markdown', storageProvider: 'local', storageLocation: 'local://reports/rep_001.md', createdAt: '2026-07-15T10:02:00Z' },
      { id: 'art_001c', reportId: 'rep_001', type: 'structured_data', storageProvider: 'local', storageLocation: 'local://reports/rep_001.json', createdAt: '2026-07-15T10:03:00Z' },
      { id: 'art_001d', reportId: 'rep_001', type: 'ai_summary', storageProvider: 'local', storageLocation: 'local://reports/rep_001_summary.json', createdAt: '2026-07-15T10:04:00Z' },
    ],
    summary: {
      id: 'sum_001',
      reportId: 'rep_001',
      mode: 'standard',
      createdAt: '2026-07-15T10:04:00Z',
      sections: [
        { key: 'executive', label: 'Executive Summary', content: 'Routine blood panel completed. Most values within normal range. Slightly elevated HbA1c suggests pre-diabetic range — lifestyle follow-up recommended.', visible: true },
        { key: 'findings', label: 'Important Findings', content: 'HbA1c at 5.9% (upper normal). LDL cholesterol borderline high at 135 mg/dL. All other markers normal.', visible: true },
        { key: 'abnormal', label: 'Reported Abnormal Values', content: 'HbA1c: 5.9% (flagged high-normal). LDL: 135 mg/dL (flagged borderline high).', visible: true },
        { key: 'normal', label: 'Normal Values', content: 'Hemoglobin: 13.8 g/dL. WBC: 6.2 K/uL. Platelets: 245 K/uL. Creatinine: 0.9 mg/dL. HDL: 58 mg/dL. Glucose (fasting): 95 mg/dL.', visible: true },
        { key: 'terms', label: 'Medical Terms', content: 'HbA1c: Glycated hemoglobin, reflects average blood sugar over ~3 months. LDL: Low-density lipoprotein ("bad" cholesterol). WBC: White blood cell count.', visible: true },
        { key: 'questions', label: 'Questions for Doctor', content: '1. Should I adjust my diet given the borderline HbA1c? 2. Is LDL of 135 a concern without family history? 3. When should I retest?', visible: true },
      ],
    },
  },
  {
    id: 'rep_002',
    patientId: 'pat_demo_001',
    type: 'Blood Test',
    title: 'Lipid Panel & HbA1c Follow-up',
    source: 'Central Lab Diagnostics',
    laboratory: 'Central Lab Diagnostics',
    department: 'Chemistry',
    doctor: 'Dr. A. Rivera',
    date: '2026-01-20',
    status: 'ready',
    artifacts: [
      { id: 'art_002a', reportId: 'rep_002', type: 'original_pdf', storageProvider: 'google_drive', storageLocation: 'gdrive://file_id_002', createdAt: '2026-01-20T09:00:00Z' },
      { id: 'art_002b', reportId: 'rep_002', type: 'extracted_markdown', storageProvider: 'local', storageLocation: 'local://reports/rep_002.md', createdAt: '2026-01-20T09:02:00Z' },
      { id: 'art_002c', reportId: 'rep_002', type: 'structured_data', storageProvider: 'local', storageLocation: 'local://reports/rep_002.json', createdAt: '2026-01-20T09:03:00Z' },
    ],
    summary: {
      id: 'sum_002',
      reportId: 'rep_002',
      mode: 'quick',
      createdAt: '2026-01-20T09:04:00Z',
      sections: [
        { key: 'executive', label: 'Executive Summary', content: 'Follow-up lipid panel. LDL improved from prior. HbA1c stable at 5.7%. No critical values.', visible: true },
        { key: 'findings', label: 'Important Findings', content: 'LDL decreased to 128 mg/dL from 142 mg/dL. HDL stable. Triglycerides normal.', visible: true },
        { key: 'abnormal', label: 'Reported Abnormal Values', content: 'LDL: 128 mg/dL (borderline high). All others within range.', visible: true },
        { key: 'normal', label: 'Normal Values', content: 'HDL: 55 mg/dL. Triglycerides: 120 mg/dL. Total cholesterol: 198 mg/dL. HbA1c: 5.7%.', visible: true },
        { key: 'terms', label: 'Medical Terms', content: 'Triglycerides: A type of fat in the blood. HDL: High-density lipoprotein ("good" cholesterol).', visible: true },
        { key: 'questions', label: 'Questions for Doctor', content: '1. Is the LDL trend positive enough? 2. Any need for medication?', visible: true },
      ],
    },
  },
  {
    id: 'rep_003',
    patientId: 'pat_demo_001',
    type: 'Imaging Report',
    title: 'CT Abdomen and Pelvis with Contrast',
    source: 'Riverside Medical Imaging',
    hospital: 'Riverside Medical Center',
    department: 'Radiology',
    doctor: 'Dr. M. Chen',
    date: '2026-05-03',
    status: 'ready',
    artifacts: [
      { id: 'art_003a', reportId: 'rep_003', type: 'original_pdf', storageProvider: 'local', storageLocation: 'local://reports/rep_003.pdf', createdAt: '2026-05-03T14:00:00Z' },
      { id: 'art_003b', reportId: 'rep_003', type: 'extracted_markdown', storageProvider: 'local', storageLocation: 'local://reports/rep_003.md', createdAt: '2026-05-03T14:02:00Z' },
      { id: 'art_003c', reportId: 'rep_003', type: 'structured_data', storageProvider: 'local', storageLocation: 'local://reports/rep_003.json', createdAt: '2026-05-03T14:03:00Z' },
      { id: 'art_003d', reportId: 'rep_003', type: 'ai_summary', storageProvider: 'local', storageLocation: 'local://reports/rep_003_summary.json', createdAt: '2026-05-03T14:04:00Z' },
    ],
    summary: {
      id: 'sum_003',
      reportId: 'rep_003',
      mode: 'clinical',
      createdAt: '2026-05-03T14:04:00Z',
      sections: [
        { key: 'executive', label: 'Executive Summary', content: 'CT of abdomen and pelvis with IV contrast. No acute intra-abdominal pathology. Small simple cyst in right kidney — benign appearance. Otherwise unremarkable.', visible: true },
        { key: 'findings', label: 'Important Findings', content: 'Simple cortical cyst (9 mm) in the right kidney. No evidence of obstruction, mass, or free fluid. Bowel loop unremarkable. No lymphadenopathy.', visible: true },
        { key: 'abnormal', label: 'Reported Abnormal Values', content: 'Right renal cyst (Bosniak I, 9 mm) — benign. No other abnormal findings.', visible: true },
        { key: 'normal', label: 'Normal Values', content: 'Liver, spleen, pancreas, gallbladder: normal. Left kidney: normal. Bladder: normal. No free air or fluid.', visible: true },
        { key: 'terms', label: 'Medical Terms', content: 'Bosniak I: A classification for simple kidney cysts with near-zero malignancy risk. Cortical cyst: A fluid-filled sac in the kidney cortex.', visible: true },
        { key: 'questions', label: 'Questions for Doctor', content: '1. Does the renal cyst need follow-up imaging? 2. At what interval? 3. Any symptoms I should watch for?', visible: true },
      ],
    },
  },
  {
    id: 'rep_004',
    patientId: 'pat_demo_001',
    type: 'Discharge Summary',
    title: 'Emergency Department Visit — Abdominal Pain',
    source: 'Riverside Medical Center',
    hospital: 'Riverside Medical Center',
    department: 'Emergency',
    doctor: 'Dr. K. Patel',
    date: '2026-04-28',
    status: 'ready',
    artifacts: [
      { id: 'art_004a', reportId: 'rep_004', type: 'original_pdf', storageProvider: 'local', storageLocation: 'local://reports/rep_004.pdf', createdAt: '2026-04-28T22:00:00Z' },
      { id: 'art_004b', reportId: 'rep_004', type: 'extracted_markdown', storageProvider: 'local', storageLocation: 'local://reports/rep_004.md', createdAt: '2026-04-28T22:02:00Z' },
    ],
    summary: {
      id: 'sum_004',
      reportId: 'rep_004',
      mode: 'standard',
      createdAt: '2026-04-28T22:04:00Z',
      sections: [
        { key: 'executive', label: 'Executive Summary', content: 'ED visit for acute abdominal pain. CT ordered and completed — no acute surgical cause. Discharged with analgesia and outpatient follow-up.', visible: true },
        { key: 'findings', label: 'Important Findings', content: 'Vital signs stable. CT showed no acute pathology. Pain attributed to dietary/gastrointestinal cause. Follow-up with GP recommended in 1 week.', visible: true },
        { key: 'abnormal', label: 'Reported Abnormal Values', content: 'No acute abnormal findings on imaging or labs.', visible: true },
        { key: 'normal', label: 'Normal Values', content: 'Vitals: HR 78, BP 118/76, Temp 36.8°C. Labs: WBC 7.1, CRP 4.2.', visible: true },
        { key: 'terms', label: 'Medical Terms', content: 'CRP: C-reactive protein, an inflammation marker. Analgesia: Pain relief medication.', visible: true },
        { key: 'questions', label: 'Questions for Doctor', content: '1. What dietary changes are recommended? 2. When to return to ED vs see GP?', visible: true },
      ],
    },
  },
  {
    id: 'rep_005',
    patientId: 'pat_demo_001',
    type: 'Blood Test',
    title: 'Annual Physical Panel',
    source: 'Central Lab Diagnostics',
    laboratory: 'Central Lab Diagnostics',
    department: 'General',
    doctor: 'Dr. A. Rivera',
    date: '2025-07-10',
    status: 'ready',
    artifacts: [
      { id: 'art_005a', reportId: 'rep_005', type: 'original_pdf', storageProvider: 'local', storageLocation: 'local://reports/rep_005.pdf', createdAt: '2025-07-10T08:00:00Z' },
      { id: 'art_005b', reportId: 'rep_005', type: 'extracted_markdown', storageProvider: 'local', storageLocation: 'local://reports/rep_005.md', createdAt: '2025-07-10T08:02:00Z' },
      { id: 'art_005c', reportId: 'rep_005', type: 'structured_data', storageProvider: 'local', storageLocation: 'local://reports/rep_005.json', createdAt: '2025-07-10T08:03:00Z' },
    ],
    summary: {
      id: 'sum_005',
      reportId: 'rep_005',
      mode: 'standard',
      createdAt: '2025-07-10T08:04:00Z',
      sections: [
        { key: 'executive', label: 'Executive Summary', content: 'Annual physical lab panel. Overall results good. LDL slightly elevated. HbA1c at 5.7% — pre-diabetic threshold. Lifestyle recommendations apply.', visible: true },
        { key: 'findings', label: 'Important Findings', content: 'LDL 142 mg/dL (borderline high). HbA1c 5.7%. All other values normal.', visible: true },
        { key: 'abnormal', label: 'Reported Abnormal Values', content: 'LDL: 142 mg/dL (borderline high). HbA1c: 5.7% (upper normal).', visible: true },
        { key: 'normal', label: 'Normal Values', content: 'Hemoglobin: 13.5 g/dL. WBC: 5.8 K/uL. HDL: 52 mg/dL. Creatinine: 0.8 mg/dL. Glucose: 92 mg/dL.', visible: true },
        { key: 'terms', label: 'Medical Terms', content: 'HbA1c: Glycated hemoglobin. LDL: Low-density lipoprotein.', visible: true },
        { key: 'questions', label: 'Questions for Doctor', content: '1. Should I see a dietitian? 2. Exercise recommendations?', visible: true },
      ],
    },
  },
  {
    id: 'rep_006',
    patientId: 'pat_demo_001',
    type: 'Consultation',
    title: 'Cardiology Consultation',
    source: 'Heartwell Clinic',
    hospital: 'Heartwell Clinic',
    department: 'Cardiology',
    doctor: 'Dr. S. Okonkwo',
    date: '2025-11-15',
    status: 'processing',
    artifacts: [
      { id: 'art_006a', reportId: 'rep_006', type: 'original_pdf', storageProvider: 'local', storageLocation: 'local://reports/rep_006.pdf', createdAt: '2025-11-15T11:00:00Z' },
    ],
  },
];

export const demoMeasurements: MedicalMeasurement[] = [
  // HbA1c trend
  { id: 'm_001', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'HbA1c', value: 5.7, unit: '%', referenceRange: '< 5.7', flag: 'normal', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics', sourceLocation: 'local://reports/rep_005.json' },
  { id: 'm_002', reportId: 'rep_002', patientId: 'pat_demo_001', testName: 'HbA1c', value: 5.7, unit: '%', referenceRange: '< 5.7', flag: 'normal', reportDate: '2026-01-20', laboratory: 'Central Lab Diagnostics', sourceLocation: 'local://reports/rep_002.json' },
  { id: 'm_003', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'HbA1c', value: 5.9, unit: '%', referenceRange: '< 5.7', flag: 'high', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics', sourceLocation: 'local://reports/rep_001.json' },
  // LDL trend
  { id: 'm_004', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'LDL', value: 142, unit: 'mg/dL', referenceRange: '< 130', flag: 'high', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics', sourceLocation: 'local://reports/rep_005.json' },
  { id: 'm_005', reportId: 'rep_002', patientId: 'pat_demo_001', testName: 'LDL', value: 128, unit: 'mg/dL', referenceRange: '< 130', flag: 'normal', reportDate: '2026-01-20', laboratory: 'Central Lab Diagnostics', sourceLocation: 'local://reports/rep_002.json' },
  { id: 'm_006', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'LDL', value: 135, unit: 'mg/dL', referenceRange: '< 130', flag: 'high', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics', sourceLocation: 'local://reports/rep_001.json' },
  // HDL
  { id: 'm_007', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'HDL', value: 52, unit: 'mg/dL', referenceRange: '> 40', flag: 'normal', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics' },
  { id: 'm_008', reportId: 'rep_002', patientId: 'pat_demo_001', testName: 'HDL', value: 55, unit: 'mg/dL', referenceRange: '> 40', flag: 'normal', reportDate: '2026-01-20', laboratory: 'Central Lab Diagnostics' },
  { id: 'm_009', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'HDL', value: 58, unit: 'mg/dL', referenceRange: '> 40', flag: 'normal', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics' },
  // Hemoglobin
  { id: 'm_010', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'Hemoglobin', value: 13.5, unit: 'g/dL', referenceRange: '12.0–15.5', flag: 'normal', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics' },
  { id: 'm_011', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'Hemoglobin', value: 13.8, unit: 'g/dL', referenceRange: '12.0–15.5', flag: 'normal', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics' },
  // WBC
  { id: 'm_012', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'WBC', value: 5.8, unit: 'K/uL', referenceRange: '4.0–10.0', flag: 'normal', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics' },
  { id: 'm_013', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'WBC', value: 6.2, unit: 'K/uL', referenceRange: '4.0–10.0', flag: 'normal', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics' },
  // Glucose
  { id: 'm_014', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'Glucose (fasting)', value: 92, unit: 'mg/dL', referenceRange: '70–99', flag: 'normal', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics' },
  { id: 'm_015', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'Glucose (fasting)', value: 95, unit: 'mg/dL', referenceRange: '70–99', flag: 'normal', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics' },
  // Creatinine
  { id: 'm_016', reportId: 'rep_005', patientId: 'pat_demo_001', testName: 'Creatinine', value: 0.8, unit: 'mg/dL', referenceRange: '0.6–1.1', flag: 'normal', reportDate: '2025-07-10', laboratory: 'Central Lab Diagnostics' },
  { id: 'm_017', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'Creatinine', value: 0.9, unit: 'mg/dL', referenceRange: '0.6–1.1', flag: 'normal', reportDate: '2026-07-15', laboratory: 'Central Lab Diagnostics' },
  // Blood Pressure (systolic)
  { id: 'm_018', reportId: 'rep_004', patientId: 'pat_demo_001', testName: 'Blood Pressure (systolic)', value: 118, unit: 'mmHg', referenceRange: '90–120', flag: 'normal', reportDate: '2026-04-28', hospital: 'Riverside Medical Center' },
  { id: 'm_019', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'Blood Pressure (systolic)', value: 122, unit: 'mmHg', referenceRange: '90–120', flag: 'normal', reportDate: '2026-07-15', hospital: 'Riverside Medical Center' },
  // Blood Pressure (diastolic)
  { id: 'm_020', reportId: 'rep_004', patientId: 'pat_demo_001', testName: 'Blood Pressure (diastolic)', value: 76, unit: 'mmHg', referenceRange: '60–80', flag: 'normal', reportDate: '2026-04-28', hospital: 'Riverside Medical Center' },
  { id: 'm_021', reportId: 'rep_001', patientId: 'pat_demo_001', testName: 'Blood Pressure (diastolic)', value: 78, unit: 'mmHg', referenceRange: '60–80', flag: 'normal', reportDate: '2026-07-15', hospital: 'Riverside Medical Center' },
];

export const demoImagingStudies: ImagingStudy[] = [
  {
    id: 'study_001',
    patientId: 'pat_demo_001',
    accessionNumber: 'ACC-2026-0503-CT01',
    modality: 'CT',
    description: 'CT Abdomen and Pelvis with IV Contrast',
    studyDate: '2026-05-03',
    bodyPart: 'Abdomen/Pelvis',
    seriesCount: 4,
    deidentified: true,
    status: 'integration_required',
    reportText: 'FINDINGS: The liver, spleen, pancreas, and gallbladder are unremarkable. A small (9 mm) simple cortical cyst is present in the right kidney (Bosniak I). No evidence of hydronephrosis or obstruction. The left kidney is normal. The bladder is unremarkable. No free air or free fluid. No lymphadenopathy. IMPRESSION: 1. Small simple right renal cyst (Bosniak I), benign appearance. 2. No acute intra-abdominal pathology.',
  },
];

export const demoTemplates: Template[] = [
  {
    id: 'tpl_001',
    name: 'Standard Lab Report Summary',
    category: 'Laboratory',
    description: 'A general-purpose template for summarizing blood test and laboratory reports.',
    updatedAt: '2026-06-01',
    sections: [
      { id: 's1', label: 'Executive Summary', order: 1, visible: true, grouped: 'Summary' },
      { id: 's2', label: 'Important Findings', order: 2, visible: true, grouped: 'Summary' },
      { id: 's3', label: 'Reported Abnormal Values', order: 3, visible: true, grouped: 'Values' },
      { id: 's4', label: 'Normal Values', order: 4, visible: true, grouped: 'Values' },
      { id: 's5', label: 'Medical Terms', order: 5, visible: true, grouped: 'Reference' },
      { id: 's6', label: 'Questions for Doctor', order: 6, visible: true, grouped: 'Reference' },
    ],
  },
  {
    id: 'tpl_002',
    name: 'Imaging Report Summary',
    category: 'Clinical',
    description: 'Template for radiology and imaging report summaries.',
    updatedAt: '2026-06-15',
    sections: [
      { id: 's1', label: 'Executive Summary', order: 1, visible: true, grouped: 'Summary' },
      { id: 's2', label: 'Important Findings', order: 2, visible: true, grouped: 'Summary' },
      { id: 's3', label: 'Reported Abnormal Values', order: 3, visible: true, grouped: 'Values' },
      { id: 's4', label: 'Normal Values', order: 4, visible: true, grouped: 'Values' },
      { id: 's5', label: 'Medical Terms', order: 5, visible: true, grouped: 'Reference' },
      { id: 's6', label: 'Questions for Doctor', order: 6, visible: true, grouped: 'Reference' },
    ],
  },
  {
    id: 'tpl_003',
    name: 'Patient-Friendly Overview',
    category: 'Patient',
    description: 'Simplified summary for patient understanding with minimal jargon.',
    updatedAt: '2026-05-20',
    sections: [
      { id: 's1', label: 'Executive Summary', order: 1, visible: true, grouped: 'Overview' },
      { id: 's2', label: 'Important Findings', order: 2, visible: true, grouped: 'Overview' },
      { id: 's3', label: 'Medical Terms', order: 3, visible: true, grouped: 'Reference' },
      { id: 's4', label: 'Questions for Doctor', order: 4, visible: true, grouped: 'Reference' },
    ],
  },
  {
    id: 'tpl_004',
    name: 'Hospital Discharge Summary',
    category: 'Hospital',
    description: 'Template for structuring hospital discharge and ED visit summaries.',
    updatedAt: '2026-04-10',
    sections: [
      { id: 's1', label: 'Executive Summary', order: 1, visible: true, grouped: 'Summary' },
      { id: 's2', label: 'Important Findings', order: 2, visible: true, grouped: 'Summary' },
      { id: 's3', label: 'Normal Values', order: 3, visible: true, grouped: 'Values' },
      { id: 's4', label: 'Questions for Doctor', order: 4, visible: true, grouped: 'Follow-up' },
    ],
  },
];

export const demoConsents: ConsentRecord[] = [
  {
    id: 'consent_001',
    patientId: 'pat_demo_001',
    recipient: 'Dr. A. Rivera (Primary Care)',
    purpose: 'Ongoing care coordination',
    scope: 'Reports & Imaging',
    issuedDate: '2026-01-15',
    expiryDate: '2027-01-15',
    revoked: false,
  },
  {
    id: 'consent_002',
    patientId: 'pat_demo_001',
    recipient: 'Heartwell Clinic — Cardiology',
    purpose: 'Specialist consultation review',
    scope: 'Reports',
    issuedDate: '2025-11-10',
    expiryDate: '2026-05-10',
    revoked: false,
  },
  {
    id: 'consent_003',
    patientId: 'pat_demo_001',
    recipient: 'Insurance Review Board',
    purpose: 'Claim documentation (expired)',
    scope: 'Reports',
    issuedDate: '2025-03-01',
    expiryDate: '2025-09-01',
    revoked: true,
  },
];

export const demoAuditEvents: AuditEvent[] = [
  { id: 'aud_001', patientId: 'pat_demo_001', eventType: 'Report Viewed', description: 'Viewed report "Complete Blood Count & Metabolic Panel"', timestamp: '2026-08-19T09:14:00Z', actor: 'patient' },
  { id: 'aud_002', patientId: 'pat_demo_001', eventType: 'Summary Generated', description: 'AI summary generated (Standard mode) for report rep_001', timestamp: '2026-07-15T10:04:00Z', actor: 'system' },
  { id: 'aud_003', patientId: 'pat_demo_001', eventType: 'Consent Issued', description: 'Access consent issued to Dr. A. Rivera (Primary Care)', timestamp: '2026-01-15T12:00:00Z', actor: 'patient' },
  { id: 'aud_004', patientId: 'pat_demo_001', eventType: 'Report Uploaded', description: 'Uploaded report "CT Abdomen and Pelvis with Contrast"', timestamp: '2026-05-03T14:00:00Z', actor: 'patient' },
  { id: 'aud_005', patientId: 'pat_demo_001', eventType: 'Imaging Study Opened', description: 'Opened imaging study ACC-2026-0503-CT01', timestamp: '2026-08-18T16:30:00Z', actor: 'patient' },
  { id: 'aud_006', patientId: 'pat_demo_001', eventType: 'Consent Revoked', description: 'Revoked consent for Insurance Review Board', timestamp: '2025-09-02T08:00:00Z', actor: 'patient' },
  { id: 'aud_007', patientId: 'pat_demo_001', eventType: 'Storage Connected', description: 'Local storage configured as primary', timestamp: '2026-01-10T10:00:00Z', actor: 'patient' },
];

export const demoStorageConnections: StorageConnection[] = [
  { provider: 'local', label: 'Local Storage', status: 'connected', isPrimary: true, description: 'Files stored on this device' },
  { provider: 'google_drive', label: 'Google Drive', status: 'not_connected', description: 'OAuth integration — server credentials required' },
  { provider: 'onedrive', label: 'OneDrive', status: 'coming_soon', description: 'Cloud storage integration' },
  { provider: 'dropbox', label: 'Dropbox', status: 'coming_soon', description: 'Cloud storage integration' },
  { provider: 'hospital', label: 'Hospital Storage', status: 'coming_soon', description: 'Direct hospital PACS integration' },
  { provider: 'messaging', label: 'Secure Messaging', status: 'coming_soon', description: 'Delivery to healthcare providers' },
];

export const demoSourceReferences: SourceReference[] = [
  { id: 'src_001', reportId: 'rep_001', label: 'CBC Panel — Page 1', location: 'local://reports/rep_001.pdf#page=1', type: 'document' },
  { id: 'src_002', reportId: 'rep_001', label: 'HbA1c Measurement', location: 'local://reports/rep_001.json#hba1c', type: 'measurement' },
  { id: 'src_003', reportId: 'rep_003', label: 'CT Report — Page 1', location: 'local://reports/rep_003.pdf#page=1', type: 'document' },
  { id: 'src_004', reportId: 'rep_003', label: 'CT Study — Series 1', location: 'study://study_001/series/1', type: 'image' },
];

export const demoOllamaConfig = {
  baseUrl: 'http://localhost:11434',
  model: 'llama3.1:8b',
  available: false,
};

export const demoUser = {
  id: 'usr_demo_001',
  email: 'demo@holomed.ai',
  displayName: 'Demo Patient',
  role: 'patient' as const,
};

export const summaryModeLabels: Record<string, string> = {
  quick: 'Quick',
  standard: 'Standard',
  detailed: 'Detailed',
  clinical: 'Clinical',
  custom: 'Custom',
};

export const reportStatusLabels: Record<string, string> = {
  ready: 'Ready',
  processing: 'Processing',
  extracting: 'Extracting',
  ocr: 'OCR Fallback',
  failed: 'Failed',
  uploading: 'Uploading',
};
