/**
 * Chest X-ray AI screening workspace.
 *
 * Upload → validate → POST /api/v1/vision/screen → 18 model scores + Grad-CAM.
 * Selecting a finding re-requests the same endpoint with `target` so the
 * explanation always comes from the backend for that model output.
 *
 * Wording rule: scores are "model scores" (non-diagnostic model outputs), never
 * probabilities or diagnoses. Grad-CAM is a visual explanation, not evidence.
 */

import { useEffect, useRef, useState, type DragEvent } from 'react';
import {
  AlertTriangle, Cpu, FileImage, Layers, Loader2, RefreshCw, ScanLine, ShieldCheck,
  Sparkles, Stethoscope, Timer, Upload, X,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { SafetyNotice } from '@/components/SafetyNotice';
import { useAuth } from '@/context/AuthContext';
import { AiExplanationPanel, type ExplanationState } from '@/components/vision/AiExplanationPanel';
import {
  ACCEPT_ATTR, describeExplanationError, describeScreeningError, explainFinding, imageDataUrl,
  screenChestXray, validateUpload,
  type DetectedFormat, type ScreeningError, type ScreeningRun, type VisionExplanation,
} from '@/lib/vision';

const SCREENING_SAFETY_TEXT =
  'AI-generated information — not a diagnosis. Consult a qualified healthcare professional.';

type ViewMode = 'original' | 'heatmap' | 'overlay';

interface SelectedFile {
  file: File;
  format: DetectedFormat;
  previewUrl: string | null; // object URL for PNG/JPEG only; revoked on change
}

const FORMAT_LABEL: Record<DetectedFormat, string> = { png: 'PNG', jpeg: 'JPEG', dicom: 'DICOM' };

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function ms(v: number): string {
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ms`;
}

function displayName(pathology: string): string {
  return pathology.replace(/_/g, ' ');
}

export function ChestXrayScreening() {
  const { signOut } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<SelectedFile | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ScreeningError | null>(null);
  const [run, setRun] = useState<ScreeningRun | null>(null);

  // Explanations per model output, fetched on demand for the current file.
  const [explanations, setExplanations] = useState<Record<string, { explanation: VisionExplanation; run: ScreeningRun }>>({});
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null);
  const [explaining, setExplaining] = useState<string | null>(null);
  // Language-model explanations per model output (loaded after the vision result).
  const [aiExplanations, setAiExplanations] = useState<Record<string, ExplanationState>>({});
  const requestSeq = useRef(0);

  const [view, setView] = useState<ViewMode>('overlay');
  const [opacity, setOpacity] = useState(0.45);

  // Revoke preview URLs when the file changes or the component unmounts.
  useEffect(() => () => {
    if (selected?.previewUrl) URL.revokeObjectURL(selected.previewUrl);
  }, [selected]);

  const resetResults = () => {
    requestSeq.current += 1;
    setRun(null);
    setError(null);
    setExplanations({});
    setAiExplanations({});
    setSelectedTarget(null);
    setExplaining(null);
    setRunning(false);
  };

  // Text explanation for one model output of one screening result. Never blocks
  // the vision result; failures only affect this panel.
  const requestAiExplanation = async (target: string, resultId: string | null) => {
    if (!resultId) {
      setAiExplanations((prev) => ({ ...prev, [target]: { status: 'error', ...describeExplanationError(null) } }));
      return;
    }
    const seq = requestSeq.current;
    setAiExplanations((prev) => ({ ...prev, [target]: { status: 'loading' } }));
    try {
      const data = await explainFinding(resultId, target);
      if (seq !== requestSeq.current) return;
      if (data.target_pathology !== target) throw new Error('explanation target mismatch');
      setAiExplanations((prev) => ({ ...prev, [target]: { status: 'ready', data } }));
    } catch (err) {
      if (seq !== requestSeq.current) return;
      const { message, retryable } = describeExplanationError(err);
      setAiExplanations((prev) => ({ ...prev, [target]: { status: 'error', message, retryable } }));
    }
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    resetResults();
    setSelected(null);
    const result = await validateUpload(file);
    if ('error' in result) {
      setValidationError(result.error);
      return;
    }
    setValidationError(null);
    setSelected({
      file,
      format: result.format,
      previewUrl: result.format === 'dicom' ? null : URL.createObjectURL(file),
    });
  };

  const clearFile = () => {
    resetResults();
    setSelected(null);
    setValidationError(null);
  };

  const runScreening = async () => {
    if (!selected) return;
    const seq = ++requestSeq.current;
    setRunning(true);
    setError(null);
    setRun(null);
    setExplanations({});
    setAiExplanations({});
    try {
      const result = await screenChestXray(selected.file);
      if (seq !== requestSeq.current) return;
      const target = result.response.explanation.target_pathology;
      setRun(result);
      setExplanations({ [target]: { explanation: result.response.explanation, run: result } });
      setSelectedTarget(target);
      setView('overlay');
      void requestAiExplanation(target, result.response.result_id);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(describeScreeningError(err));
    } finally {
      if (seq === requestSeq.current) setRunning(false);
    }
  };

  const selectFinding = async (pathology: string) => {
    if (!selected || !run || explaining) return;
    setSelectedTarget(pathology);
    if (explanations[pathology]) return;
    const seq = requestSeq.current;
    setExplaining(pathology);
    setError(null);
    try {
      const result = await screenChestXray(selected.file, pathology);
      if (seq !== requestSeq.current) return;
      setExplanations((prev) => ({ ...prev, [pathology]: { explanation: result.response.explanation, run: result } }));
      void requestAiExplanation(pathology, result.response.result_id);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(describeScreeningError(err));
      setSelectedTarget(run.response.explanation.target_pathology);
    } finally {
      if (seq === requestSeq.current) setExplaining(null);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    void handleFile(e.dataTransfer.files?.[0]);
  };

  const response = run?.response ?? null;
  const current = selectedTarget ? explanations[selectedTarget] : undefined;
  const explanation = current?.explanation ?? null;
  const shownRun = current?.run ?? run;
  const primary = response?.primary_finding ?? null;
  const nonSquare = response ? response.input.width !== response.input.height : false;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* ── Viewer ─────────────────────────────────────────────────────── */}
        <Card className="xl:col-span-7 flex flex-col overflow-hidden self-start xl:sticky xl:top-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 text-teal-600 dark:bg-teal-950 dark:text-teal-400">
                <Layers className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Visual Explanation</h3>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">
                  {explanation ? `Grad-CAM · ${displayName(explanation.target_pathology)}` : 'Original · Grad-CAM · Overlay'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1 rounded-lg bg-neutral-100 p-1 dark:bg-neutral-800" role="tablist" aria-label="Image view">
              {(['original', 'heatmap', 'overlay'] as ViewMode[]).map((mode) => (
                <button
                  key={mode}
                  role="tab"
                  aria-selected={view === mode}
                  disabled={!explanation}
                  onClick={() => setView(mode)}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                    view === mode && explanation
                      ? 'bg-white text-teal-700 shadow-sm dark:bg-neutral-950 dark:text-teal-300'
                      : 'text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100'
                  }`}
                >
                  {mode === 'original' ? 'Original' : mode === 'heatmap' ? 'Grad-CAM' : 'Overlay'}
                </button>
              ))}
            </div>
          </div>

          <div className="relative flex items-center justify-center bg-neutral-950 p-3" style={{ minHeight: 420 }}>
            {explanation ? (
              <div className="relative aspect-square w-full max-w-[560px]" data-testid="explanation-viewer">
                <img
                  src={imageDataUrl(explanation.original)}
                  alt="Chest X-ray region analyzed by the model"
                  className="absolute inset-0 h-full w-full select-none object-contain"
                  draggable={false}
                />
                <img
                  src={imageDataUrl(explanation.heatmap)}
                  alt={`Grad-CAM visual explanation for ${displayName(explanation.target_pathology)}`}
                  className="absolute inset-0 h-full w-full select-none object-contain transition-opacity"
                  style={{ opacity: view === 'original' ? 0 : view === 'heatmap' ? 1 : opacity }}
                  draggable={false}
                />
                <div className="pointer-events-none absolute left-2 top-2 rounded-md bg-black/70 px-2 py-1 text-[11px] font-medium text-white">
                  {view === 'original' ? 'Original' : view === 'heatmap' ? 'Grad-CAM' : `Overlay · ${Math.round(opacity * 100)}%`}
                </div>
                <div className="pointer-events-none absolute bottom-2 left-2 rounded-md bg-black/70 px-2 py-1 text-[11px] text-neutral-200">
                  Target: {displayName(explanation.target_pathology)} · model score {explanation.target_score.toFixed(4)}
                </div>
                {explaining && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                    <div className="flex items-center gap-2 rounded-lg bg-black/80 px-3 py-2 text-xs text-white">
                      <Loader2 className="h-4 w-4 animate-spin" /> Generating explanation for {displayName(explaining)}…
                    </div>
                  </div>
                )}
              </div>
            ) : selected?.previewUrl ? (
              <div className="relative w-full max-w-[560px]">
                <img src={selected.previewUrl} alt="Selected chest X-ray" className="mx-auto max-h-[520px] w-auto object-contain" />
                <div className="pointer-events-none absolute left-2 top-2 rounded-md bg-black/70 px-2 py-1 text-[11px] font-medium text-white">
                  Selected image · not yet screened
                </div>
              </div>
            ) : selected ? (
              <div className="flex flex-col items-center gap-2 p-8 text-center">
                <FileImage className="h-10 w-10 text-neutral-500" />
                <p className="text-sm font-semibold text-neutral-200">DICOM file selected</p>
                <p className="max-w-xs text-xs text-neutral-400">
                  The radiograph is decoded on the HoloMed backend and shown here after screening.
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 p-8 text-center">
                <ScanLine className="h-10 w-10 text-neutral-600" />
                <p className="text-sm font-semibold text-neutral-300">No image selected</p>
                <p className="max-w-xs text-xs text-neutral-500">Select a chest X-ray to begin AI screening.</p>
              </div>
            )}
            {running && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                <div className="flex flex-col items-center gap-2 rounded-xl bg-black/80 px-5 py-4 text-center text-white">
                  <Loader2 className="h-6 w-6 animate-spin text-teal-400" />
                  <p className="text-sm font-medium">Running AI screening…</p>
                  <p className="max-w-[16rem] text-[11px] text-neutral-400">
                    The first request after the server starts also loads the model and can take a few seconds.
                  </p>
                </div>
              </div>
            )}
          </div>

          <div className="space-y-2 border-t border-neutral-200 px-4 py-3 dark:border-neutral-800">
            <div className="flex flex-wrap items-center gap-3">
              <label htmlFor="overlay-opacity" className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
                Overlay opacity
              </label>
              <input
                id="overlay-opacity"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={opacity}
                disabled={!explanation || view !== 'overlay'}
                onChange={(e) => setOpacity(Number(e.target.value))}
                className="h-1.5 w-40 cursor-pointer accent-teal-600 disabled:cursor-not-allowed disabled:opacity-40"
              />
              <span className="w-10 text-xs tabular-nums text-neutral-500 dark:text-neutral-400">{Math.round(opacity * 100)}%</span>
            </div>
            <p className="text-xs text-neutral-600 dark:text-neutral-400">
              <span className="font-medium text-neutral-800 dark:text-neutral-200">Visual explanation of the selected model output.</span>{' '}
              Highlighted regions most influenced this model score (Grad-CAM, layer{' '}
              <code className="font-mono text-[11px]">{explanation?.target_layer ?? 'features.denseblock4'}</code>).
              This visualization does not establish the presence or absence of disease.
            </p>
            {nonSquare && (
              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                The model analyzes the centered square region of the image; the view above shows that region.
              </p>
            )}
          </div>
        </Card>

        {/* ── Controls & results ─────────────────────────────────────────── */}
        <div className="xl:col-span-5 space-y-4">
          <Card>
            <CardHeader
              title="Chest X-Ray AI Screening"
              subtitle="PNG, JPEG, or DICOM (CR/DX) · up to 50 MB"
              icon={<Sparkles className="h-4 w-4" />}
            />
            <div className="space-y-3 px-4 pb-4 sm:px-5 sm:pb-5">
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT_ATTR}
                className="hidden"
                data-testid="cxr-file-input"
                onChange={(e) => {
                  void handleFile(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
              {!selected ? (
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => inputRef.current?.click()}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors ${
                    dragOver
                      ? 'border-teal-500 bg-teal-50 dark:bg-teal-950/30'
                      : 'border-neutral-300 hover:border-teal-400 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <Upload className="h-6 w-6 text-teal-600 dark:text-teal-400" />
                  <p className="text-sm font-medium text-neutral-800 dark:text-neutral-200">Select or drop a chest X-ray</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">Use de-identified images only.</p>
                </div>
              ) : (
                <div className="flex items-center gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <FileImage className="h-5 w-5 shrink-0 text-teal-600 dark:text-teal-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100" title={selected.file.name}>
                      {selected.file.name}
                    </p>
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">
                      {FORMAT_LABEL[selected.format]} · {formatBytes(selected.file.size)}
                    </p>
                  </div>
                  <StatusBadge variant="success" icon={<ShieldCheck className="h-3 w-3" />}>Validated</StatusBadge>
                  <button
                    onClick={clearFile}
                    disabled={running}
                    className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 disabled:opacity-40 dark:hover:bg-neutral-800"
                    title="Remove file"
                    aria-label="Remove file"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              )}

              {validationError && (
                <div className="flex gap-2 rounded-lg border border-error-100 bg-error-50 p-3 text-xs text-error-700 dark:border-error-700/30 dark:bg-error-700/10 dark:text-error-400" role="alert">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{validationError}</span>
                </div>
              )}

              <div className="flex gap-2">
                <Button className="flex-1 justify-center" onClick={runScreening} disabled={!selected || running}>
                  {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  {running ? 'Running AI Screening…' : run ? 'Run AI Screening Again' : 'Run AI Screening'}
                </Button>
                {selected && (
                  <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={running} title="Choose another image">
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                )}
              </div>

              {error && (
                <div className="flex gap-2 rounded-lg border border-error-100 bg-error-50 p-3 dark:border-error-700/30 dark:bg-error-700/10" role="alert">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-error-600 dark:text-error-400" />
                  <div className="min-w-0 flex-1 text-xs">
                    <p className="font-semibold text-error-700 dark:text-error-400">{error.title}</p>
                    <p className="mt-0.5 text-error-700/90 dark:text-error-400/90">{error.message}</p>
                    {error.kind === 'auth' && (
                      <Button size="sm" variant="outline" className="mt-2" onClick={signOut}>Sign in again</Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>

          {response && primary && (
            <Card>
              <CardHeader
                title="AI Screening Results"
                subtitle="Source: vision model (TorchXRayVision) · 18 chest X-ray targets"
                icon={<Stethoscope className="h-4 w-4" />}
                action={<StatusBadge variant="warning">Requires Clinical Review</StatusBadge>}
              />
              <div className="space-y-4 px-4 pb-4 sm:px-5 sm:pb-5">
                <div className="grid grid-cols-2 gap-3 rounded-lg border border-teal-200 bg-teal-50/60 p-3 dark:border-teal-700/30 dark:bg-teal-950/20">
                  <div>
                    <p className="text-[11px] font-medium uppercase tracking-wide text-teal-700 dark:text-teal-400">Primary Model Finding</p>
                    <p className="mt-0.5 text-lg font-semibold text-neutral-900 dark:text-neutral-100" data-testid="primary-finding">
                      {displayName(primary.pathology)}
                    </p>
                    <p className="text-[11px] text-neutral-500 dark:text-neutral-400">Highest-scoring model output</p>
                  </div>
                  <div className="text-right">
                    <p className="text-[11px] font-medium uppercase tracking-wide text-teal-700 dark:text-teal-400">Model Score</p>
                    <p className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-neutral-900 dark:text-neutral-100" data-testid="primary-score">
                      {primary.score.toFixed(4)}
                    </p>
                    <p className="text-[11px] text-neutral-500 dark:text-neutral-400">Non-diagnostic model output</p>
                  </div>
                </div>
                <p className="flex items-start gap-1.5 text-[11px] font-medium text-amber-700 dark:text-amber-400" role="note">
                  <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
                  <span>{SCREENING_SAFETY_TEXT} Requires clinical review.</span>
                </p>

                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-300">All Model Findings</p>
                    <p className="text-[11px] text-neutral-500 dark:text-neutral-400">Select a finding to view its explanation</p>
                  </div>
                  <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800" data-testid="findings-list">
                    {response.findings.map((f) => {
                      const isSelected = f.pathology === selectedTarget;
                      const isLoading = f.pathology === explaining;
                      return (
                        <li key={f.pathology}>
                          <button
                            onClick={() => void selectFinding(f.pathology)}
                            disabled={!!explaining}
                            aria-pressed={isSelected}
                            className={`flex w-full items-center gap-3 px-3 py-1.5 text-left transition-colors disabled:cursor-wait ${
                              isSelected ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                            }`}
                          >
                            <span className={`w-52 shrink-0 truncate text-xs ${isSelected ? 'font-semibold text-teal-700 dark:text-teal-300' : 'text-neutral-700 dark:text-neutral-300'}`}>
                              {displayName(f.pathology)}
                            </span>
                            <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
                              <span
                                className={`absolute inset-y-0 left-0 rounded-full ${isSelected ? 'bg-teal-600' : 'bg-neutral-400 dark:bg-neutral-500'}`}
                                style={{ width: `${Math.max(0, Math.min(1, f.score)) * 100}%` }}
                              />
                            </span>
                            <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-neutral-800 dark:text-neutral-200">
                              {f.score.toFixed(4)}
                            </span>
                            <span className="w-4 shrink-0">
                              {isLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-600" />}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-neutral-500 dark:text-neutral-400">
                    Model scores range from 0 to 1 and are not calibrated probabilities of disease.
                  </p>
                </div>
              </div>
            </Card>
          )}

          {response && selectedTarget && explanations[selectedTarget] && (
            <AiExplanationPanel
              target={selectedTarget}
              state={aiExplanations[selectedTarget]}
              onRetry={() => void requestAiExplanation(
                selectedTarget, explanations[selectedTarget].run.response.result_id)}
            />
          )}

          {response && shownRun && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-1">
              <Card>
                <CardHeader title="Model Information" icon={<Cpu className="h-4 w-4" />} />
                <dl className="space-y-1.5 px-4 pb-4 text-xs sm:px-5 sm:pb-5" data-testid="model-info">
                  <InfoRow label="Model" value={response.model.name} />
                  <InfoRow label="Weights" value={response.model.weights} mono />
                  <InfoRow
                    label="Weights SHA-256"
                    value={`${response.model.weight_sha256.slice(0, 12)}…${response.model.weight_sha256.slice(-6)}`}
                    title={response.model.weight_sha256}
                    mono
                  />
                  <InfoRow label="Output" value={`${response.model.targets} chest X-ray pathology targets`} />
                  <InfoRow label="Explanation" value={`${explanation?.method ?? 'Grad-CAM'} · ${explanation?.target_layer ?? ''}`} />
                  <InfoRow label="Model score" value="Non-diagnostic model output" />
                  <InfoRow label="Input" value={`${FORMAT_LABEL[response.input.format]} · ${response.input.width}×${response.input.height}${response.input.modality ? ` · ${response.input.modality}` : ''}`} />
                  <InfoRow label="Analyzed" value={new Date(shownRun.response.inferred_at).toLocaleString()} />
                </dl>
              </Card>
              <Card>
                <CardHeader title="Processing Time" icon={<Timer className="h-4 w-4" />} />
                <dl className="space-y-1.5 px-4 pb-4 text-xs sm:px-5 sm:pb-5" data-testid="timing">
                  <InfoRow label="Preprocessing" value={ms(shownRun.response.timing.preprocessing_ms)} mono />
                  <InfoRow label="Inference" value={ms(shownRun.response.timing.inference_ms)} mono />
                  <InfoRow label="Explanation (Grad-CAM)" value={ms(shownRun.response.timing.gradcam_ms)} mono />
                  <InfoRow label="Image rendering" value={ms(shownRun.response.timing.rendering_ms)} mono />
                  <InfoRow label="Server total" value={ms(shownRun.response.timing.total_ms)} mono strong />
                  <InfoRow label="Round trip (browser)" value={ms(shownRun.roundTripMs)} mono />
                  <p className="pt-1 text-[11px] text-neutral-500 dark:text-neutral-400">
                    Measured for this request on the HoloMed server ({response.model.device.split(' (')[0]}).
                  </p>
                </dl>
              </Card>
            </div>
          )}
        </div>
      </div>

      {/* ── Safety & human review (always visible) ───────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SafetyNotice message={SCREENING_SAFETY_TEXT} className="p-4">
          <p className="mt-1 text-xs font-semibold text-amber-800 dark:text-amber-300">Requires clinical review.</p>
        </SafetyNotice>
        <div className="flex gap-3 rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900" role="note">
          <Stethoscope className="h-5 w-5 shrink-0 text-teal-600 dark:text-teal-400" />
          <div className="text-xs text-neutral-600 dark:text-neutral-400">
            <p className="font-semibold text-neutral-800 dark:text-neutral-200">Human review</p>
            <p className="mt-1">
              Screening outputs are decision-support information for a qualified clinician, who interprets them together
              with the full image and clinical context. The model has not been clinically validated by HoloMed.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value, mono = false, strong = false, title }: {
  label: string; value: string; mono?: boolean; strong?: boolean; title?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-neutral-500 dark:text-neutral-400">{label}</dt>
      <dd
        title={title}
        className={`min-w-0 break-words text-right ${mono ? 'font-mono tabular-nums' : ''} ${strong ? 'font-semibold text-neutral-900 dark:text-neutral-100' : 'text-neutral-800 dark:text-neutral-200'}`}
      >
        {value}
      </dd>
    </div>
  );
}
