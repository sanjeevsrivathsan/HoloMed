import { useState } from 'react';
import {
  ScanLine, Layers, ZoomIn, Hand, Sliders, Ruler, PenTool, Box, FileText,
  Sparkles, ShieldCheck, AlertCircle, ExternalLink,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { SafetyNotice } from '@/components/SafetyNotice';
import { DemoDataBadge } from '@/components/DemoDataBadge';
import { EmptyState } from '@/components/States';
import type { ImagingStudy } from '@/lib/types';

interface ImagingProps {
  studies: ImagingStudy[];
  selectedStudyId: string | null;
  onSelectStudy: (id: string) => void;
}

const toolbarTools = [
  { key: '2d', label: '2D', icon: Layers },
  { key: 'mpr', label: 'MPR', icon: Box },
  { key: '3d', label: '3D', icon: Box },
  { key: 'zoom', label: 'Zoom', icon: ZoomIn },
  { key: 'pan', label: 'Pan', icon: Hand },
  { key: 'window', label: 'Window/Level', icon: Sliders },
  { key: 'measure', label: 'Measure', icon: Ruler },
  { key: 'annotate', label: 'Annotation', icon: PenTool },
];

export function Imaging({ studies, selectedStudyId, onSelectStudy }: ImagingProps) {
  const [activeTool, setActiveTool] = useState('2d');

  const selectedStudy = studies.find((s) => s.id === selectedStudyId) || null;
  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:h-[calc(100vh-5rem)]">
      {/* Left: Study List */}
      <div className="lg:col-span-3 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="Imaging Studies" icon={<ScanLine className="h-4.5 w-4.5" />} action={<DemoDataBadge />} />
          <div className="flex-1 divide-y divide-neutral-100 dark:divide-neutral-800 lg:overflow-y-auto">
            {studies.length === 0 ? (
              <EmptyState title="No studies" description="No imaging studies available." icon={<ScanLine className="h-6 w-6" />} />
            ) : (
              studies.map((study) => (
                <button
                  key={study.id}
                  onClick={() => onSelectStudy(study.id)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                    selectedStudyId === study.id ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{study.description}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{study.modality} · {study.bodyPart} · {formatDate(study.studyDate)}</p>
                  <div className="flex items-center gap-2">
                    <StatusBadge variant={study.deidentified ? 'success' : 'warning'}>
                      {study.deidentified ? 'De-identified' : 'Not de-identified'}
                    </StatusBadge>
                    <StatusBadge variant={study.status === 'available' ? 'success' : 'info'} pulse={study.status === 'pending'}>
                      {study.status === 'available' ? 'Available' : study.status === 'pending' ? 'Pending' : 'Integration required'}
                    </StatusBadge>
                  </div>
                </button>
              ))
            )}
          </div>
          <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
            <div className="space-y-1.5 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/50">
              <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Study Metadata</p>
              {selectedStudy ? (
                <div className="space-y-1 text-xs text-neutral-600 dark:text-neutral-400">
                  <p>Accession: {selectedStudy.accessionNumber}</p>
                  <p>Series: {selectedStudy.seriesCount}</p>
                  <p>Date: {formatDate(selectedStudy.studyDate)}</p>
                </div>
              ) : (
                <p className="text-xs text-neutral-400">Select a study to view metadata</p>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Center: Imaging Viewport */}
      <div className="lg:col-span-6">
        <Card className="lg:h-full flex flex-col">
          {!selectedStudy ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState title="Select a study" description="Choose an imaging study from the list to open the viewer." icon={<ScanLine className="h-6 w-6" />} />
            </div>
          ) : (
            <>
              {/* Toolbar */}
              <div className="flex items-center gap-1 border-b border-neutral-200 p-2 dark:border-neutral-800">
                {toolbarTools.map((tool) => {
                  const Icon = tool.icon;
                  return (
                    <button
                      key={tool.key}
                      onClick={() => setActiveTool(tool.key)}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                        activeTool === tool.key
                          ? 'bg-teal-600 text-white'
                          : 'text-neutral-500 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800'
                      }`}
                      title={tool.label}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span className="hidden sm:inline">{tool.label}</span>
                    </button>
                  );
                })}
              </div>

              {/* Viewport */}
              <div className="flex flex-1 items-center justify-center bg-neutral-950 p-4" style={{ minHeight: 400 }}>
                <div className="flex flex-col items-center justify-center text-center">
                  <div className="mb-4 flex h-20 w-20 items-center justify-center rounded-2xl bg-neutral-900">
                    <ScanLine className="h-10 w-10 text-neutral-600" />
                  </div>
                  <p className="text-sm font-semibold text-neutral-300">OHIF Viewer Integration Required</p>
                  <p className="mt-1 max-w-sm text-xs text-neutral-500">
                    This is a demo workspace. The OHIF Viewer is not embedded in demo mode.
                    Connect a DICOM backend (e.g., Orthanc or dcm4che) to enable full imaging visualization.
                  </p>
                  <div className="mt-4 flex items-center gap-2">
                    <Button variant="secondary" size="sm" disabled>
                      <ExternalLink className="h-3.5 w-3.5" />
                      Launch OHIF Viewer
                    </Button>
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-xs text-amber-500">
                    <AlertCircle className="h-3.5 w-3.5" />
                    AI image analysis is not available. Do not infer AI analyzed the image.
                  </div>
                </div>
              </div>

              {/* Study info bar */}
              <div className="flex items-center justify-between gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
                <div className="flex items-center gap-3 text-xs text-neutral-500 dark:text-neutral-400">
                  <span>{selectedStudy.modality}</span>
                  <span>·</span>
                  <span>{selectedStudy.bodyPart}</span>
                  <span>·</span>
                  <span>{selectedStudy.seriesCount} series</span>
                </div>
                <StatusBadge variant={selectedStudy.deidentified ? 'success' : 'warning'}>
                  {selectedStudy.deidentified ? 'De-identified' : 'Not de-identified'}
                </StatusBadge>
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Right: Report & AI Explanation */}
      <div className="lg:col-span-3 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="Radiology Report" icon={<FileText className="h-4.5 w-4.5" />} />
          <div className="flex-1 overflow-y-auto p-4">
            {!selectedStudy ? (
              <EmptyState title="No study selected" description="Select a study to view its radiology report." icon={<FileText className="h-6 w-6" />} />
            ) : !selectedStudy.reportText ? (
              <EmptyState title="No report available" description="This study has no associated radiology report." icon={<FileText className="h-6 w-6" />} />
            ) : (
              <div className="space-y-4">
                <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <p className="mb-1.5 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Report Text</p>
                  <p className="whitespace-pre-wrap text-xs leading-relaxed text-neutral-700 dark:text-neutral-300">{selectedStudy.reportText}</p>
                </div>

                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-3 dark:border-teal-700/30 dark:bg-teal-950/10">
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                    <p className="text-xs font-semibold text-teal-600 dark:text-teal-400">AI Explanation of Report</p>
                  </div>
                  <p className="text-xs leading-relaxed text-neutral-700 dark:text-neutral-300">
                    This report describes a CT scan of the abdomen and pelvis. The key finding is a small, simple cyst in the right kidney classified as Bosniak I, which is benign and typically requires no treatment. All other organs appeared normal with no signs of acute disease.
                  </p>
                  <p className="mt-2 text-xs text-neutral-400">
                    Note: This AI explanation summarizes the written radiology report only. It does not analyze the image itself.
                  </p>
                </div>

                <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <p className="mb-1.5 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Questions for Doctor</p>
                  <ol className="space-y-1 text-xs text-neutral-700 dark:text-neutral-300">
                    <li>1. Does the renal cyst need follow-up imaging?</li>
                    <li>2. At what interval should I have a repeat scan?</li>
                    <li>3. Are there any symptoms I should watch for?</li>
                  </ol>
                </div>

                <SafetyNotice variant="compact" />

                <div className="flex items-center gap-2 text-xs text-neutral-400">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <span>Report-to-image links show anatomical text only. No coordinate mapping in demo mode.</span>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
