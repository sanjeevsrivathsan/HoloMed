// DICOM modalities that carry no pixel data (waveforms, structured documents, presentation objects).
// OHIF has no image display set for them, so its viewport stays black.
const NON_IMAGE_MODALITIES = new Set([
  'ECG', 'EPS', 'HD', 'RESP', 'AU', 'SR', 'KO', 'PR', 'DOC', 'REG', 'PLAN', 'RTPLAN', 'RTRECORD', 'FID',
]);

export function hasViewableImages(modality: string | null | undefined): boolean {
  return !NON_IMAGE_MODALITIES.has((modality ?? '').trim().toUpperCase());
}

interface StudyRef {
  id: string;
  modality: string;
}

/**
 * Study to open in the viewer: the requested one if still present, otherwise the most recent
 * study with images (studies arrive oldest first), otherwise the most recent study of any kind.
 */
export function pickViewerStudy(studies: StudyRef[], preferredId: string | null): string | null {
  if (preferredId && studies.some((s) => s.id === preferredId)) return preferredId;
  for (let i = studies.length - 1; i >= 0; i--) {
    if (hasViewableImages(studies[i].modality)) return studies[i].id;
  }
  return studies.length ? studies[studies.length - 1].id : null;
}
