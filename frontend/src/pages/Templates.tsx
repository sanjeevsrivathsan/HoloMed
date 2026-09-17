import { useState, useMemo } from 'react';
import {
  LayoutTemplate, Plus, Eye, Edit3, Trash2, GripVertical, Check, Download,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { Modal } from '@/components/Modal';
import { StatusBadge } from '@/components/StatusBadge';
import { EmptyState } from '@/components/States';
import type { Template, TemplateSection } from '@/lib/types';

interface TemplatesProps {
  templates: Template[];
  onSaveTemplate: (template: Template) => void;
}

const categoryColors: Record<string, string> = {
  Patient: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  Clinical: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400',
  Hospital: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  Laboratory: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400',
  Custom: 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400',
};

const allSectionLabels = [
  'Executive Summary',
  'Important Findings',
  'Reported Abnormal Values',
  'Normal Values',
  'Medical Terms',
  'Questions for Doctor',
];

export function Templates({ templates, onSaveTemplate }: TemplatesProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(templates[0] || null);
  const [editing, setEditing] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editCategory, setEditCategory] = useState<Template['category']>('Custom');
  const [editSections, setEditSections] = useState<TemplateSection[]>([]);

  const groupedSections = useMemo(() => {
    if (!selectedTemplate) return {};
    const groups: Record<string, TemplateSection[]> = {};
    selectedTemplate.sections.forEach((s) => {
      const g = s.grouped || 'Ungrouped';
      if (!groups[g]) groups[g] = [];
      groups[g].push(s);
    });
    return groups;
  }, [selectedTemplate]);

  const startEdit = (template: Template) => {
    setEditName(template.name);
    setEditDescription(template.description);
    setEditCategory(template.category);
    setEditSections([...template.sections]);
    setEditing(true);
  };

  const startNew = () => {
    setEditName('');
    setEditDescription('');
    setEditCategory('Custom');
    setEditSections(allSectionLabels.map((label, i) => ({ id: `s${i}`, label, order: i + 1, visible: true, grouped: 'Summary' })));
    setEditing(true);
  };

  const saveEdit = () => {
    if (!selectedTemplate) {
      const newTemplate: Template = {
        id: `tpl_${Date.now()}`,
        name: editName || 'Untitled Template',
        description: editDescription,
        category: editCategory,
        sections: editSections,
        updatedAt: new Date().toISOString().slice(0, 10),
      };
      onSaveTemplate(newTemplate);
      setSelectedTemplate(newTemplate);
    } else {
      const updated: Template = {
        ...selectedTemplate,
        name: editName,
        description: editDescription,
        category: editCategory,
        sections: editSections,
        updatedAt: new Date().toISOString().slice(0, 10),
      };
      onSaveTemplate(updated);
      setSelectedTemplate(updated);
    }
    setEditing(false);
  };

  const moveSection = (idx: number, dir: 'up' | 'down') => {
    const newSections = [...editSections];
    const swapIdx = dir === 'up' ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= newSections.length) return;
    [newSections[idx], newSections[swapIdx]] = [newSections[swapIdx], newSections[idx]];
    setEditSections(newSections.map((s, i) => ({ ...s, order: i + 1 })));
  };

  const previewData: Record<string, string> = {
    'Executive Summary': 'Routine blood panel completed. Most values within normal range.',
    'Important Findings': 'HbA1c at 5.9% (upper normal). LDL cholesterol borderline high.',
    'Reported Abnormal Values': 'HbA1c: 5.9% (flagged high-normal). LDL: 135 mg/dL.',
    'Normal Values': 'Hemoglobin: 13.8 g/dL. WBC: 6.2 K/uL. Creatinine: 0.9 mg/dL.',
    'Medical Terms': 'HbA1c: Glycated hemoglobin. LDL: Low-density lipoprotein.',
    'Questions for Doctor': '1. Should I adjust my diet? 2. When should I retest?',
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      {/* Left: Template List */}
      <div className="lg:col-span-4">
        <Card>
          <CardHeader
            title="Templates"
            icon={<LayoutTemplate className="h-4.5 w-4.5" />}
            action={<Button size="sm" onClick={startNew}><Plus className="h-3.5 w-3.5" /> New</Button>}
          />
          <div className="px-4 pb-2"></div>
          <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {templates.length === 0 ? (
              <EmptyState title="No templates" description="Create a template to get started." icon={<LayoutTemplate className="h-6 w-6" />} />
            ) : (
              templates.map((tpl) => (
                <button
                  key={tpl.id}
                  onClick={() => setSelectedTemplate(tpl)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                    selectedTemplate?.id === tpl.id ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{tpl.name}</p>
                    <span className={`badge ${categoryColors[tpl.category]}`}>{tpl.category}</span>
                  </div>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{tpl.description}</p>
                  <p className="text-xs text-neutral-400">{tpl.sections.length} sections · Updated {tpl.updatedAt}</p>
                </button>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Right: Template Detail / Editor */}
      <div className="lg:col-span-8">
        <Card>
          {!selectedTemplate && !editing ? (
            <EmptyState title="Select a template" description="Choose a template from the list to view or edit it." icon={<LayoutTemplate className="h-6 w-6" />} />
          ) : editing ? (
            <>
              <CardHeader
                title={selectedTemplate ? 'Edit Template' : 'New Template'}
                icon={<Edit3 className="h-4.5 w-4.5" />}
                action={
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
                    <Button size="sm" onClick={saveEdit}><Check className="h-3.5 w-3.5" /> Save</Button>
                  </div>
                }
              />
              <div className="space-y-4 p-5">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Template Name</label>
                  <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} className="input" placeholder="Template name" />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Description</label>
                  <input type="text" value={editDescription} onChange={(e) => setEditDescription(e.target.value)} className="input" placeholder="Template description" />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Category</label>
                  <select value={editCategory} onChange={(e) => setEditCategory(e.target.value as Template['category'])} className="input max-w-xs">
                    {['Patient', 'Clinical', 'Hospital', 'Laboratory', 'Custom'].map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Sections</label>
                  <div className="space-y-1.5">
                    {editSections.map((section, idx) => (
                      <div key={section.id} className="flex items-center gap-2 rounded-lg border border-neutral-200 p-2 dark:border-neutral-800">
                        <GripVertical className="h-4 w-4 text-neutral-300 dark:text-neutral-600" />
                        <div className="flex flex-col gap-0.5">
                          <button onClick={() => moveSection(idx, 'up')} disabled={idx === 0} className="text-neutral-400 hover:text-neutral-600 disabled:opacity-30" aria-label="Move up">
                            <Plus className="h-3 w-3 rotate-45" />
                          </button>
                          <button onClick={() => moveSection(idx, 'down')} disabled={idx === editSections.length - 1} className="text-neutral-400 hover:text-neutral-600 disabled:opacity-30" aria-label="Move down">
                            <Plus className="h-3 w-3 -rotate-45" />
                          </button>
                        </div>
                        <input
                          type="text"
                          value={section.label}
                          onChange={(e) => setEditSections(editSections.map((s, i) => i === idx ? { ...s, label: e.target.value } : s))}
                          className="input flex-1 text-xs"
                        />
                        <input
                          type="text"
                          value={section.grouped || ''}
                          onChange={(e) => setEditSections(editSections.map((s, i) => i === idx ? { ...s, grouped: e.target.value } : s))}
                          placeholder="Group"
                          className="input max-w-[100px] text-xs"
                        />
                        <label className="flex items-center gap-1 text-xs text-neutral-500">
                          <input
                            type="checkbox"
                            checked={section.visible}
                            onChange={(e) => setEditSections(editSections.map((s, i) => i === idx ? { ...s, visible: e.target.checked } : s))}
                            className="rounded border-neutral-300 text-teal-600 focus:ring-teal-500"
                          />
                          Visible
                        </label>
                        <button
                          onClick={() => setEditSections(editSections.filter((_, i) => i !== idx))}
                          className="rounded p-1 text-neutral-400 hover:bg-error-50 hover:text-error-600 dark:hover:bg-error-700/10"
                          aria-label="Remove section"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                    <Button variant="outline" size="sm" onClick={() => setEditSections([...editSections, { id: `s${Date.now()}`, label: 'New Section', order: editSections.length + 1, visible: true, grouped: 'Summary' }])}>
                      <Plus className="h-3.5 w-3.5" /> Add Section
                    </Button>
                  </div>
                </div>
              </div>
            </>
          ) : selectedTemplate ? (
            <>
              <CardHeader
                title={selectedTemplate.name}
                subtitle={selectedTemplate.description}
                icon={<LayoutTemplate className="h-4.5 w-4.5" />}
                action={
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setPreviewOpen(true)}><Eye className="h-3.5 w-3.5" /> Preview</Button>
                    <Button variant="secondary" size="sm" onClick={() => startEdit(selectedTemplate)}><Edit3 className="h-3.5 w-3.5" /> Edit</Button>
                  </div>
                }
              />
              <div className="p-5">
                <div className="mb-4 flex items-center gap-2">
                  <span className={`badge ${categoryColors[selectedTemplate.category]}`}>{selectedTemplate.category}</span>
                  <StatusBadge variant="neutral">{selectedTemplate.sections.length} sections</StatusBadge>
                  <StatusBadge variant="neutral">Updated {selectedTemplate.updatedAt}</StatusBadge>
                </div>
                <div className="space-y-4">
                  {Object.entries(groupedSections).map(([group, sections]) => (
                    <div key={group}>
                      <p className="mb-2 text-xs font-semibold text-neutral-500 dark:text-neutral-400">{group}</p>
                      <div className="space-y-1.5">
                        {sections.sort((a, b) => a.order - b.order).map((section) => (
                          <div key={section.id} className="flex items-center gap-2 rounded-lg border border-neutral-200 px-3 py-2 dark:border-neutral-800">
                            <span className="text-xs font-medium text-neutral-400">#{section.order}</span>
                            <span className="flex-1 text-sm text-neutral-700 dark:text-neutral-300">{section.label}</span>
                            <StatusBadge variant={section.visible ? 'success' : 'neutral'}>
                              {section.visible ? 'Visible' : 'Hidden'}
                            </StatusBadge>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : null}
        </Card>
      </div>

      {/* Preview Modal */}
      <Modal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title="Template Preview"
        description={selectedTemplate?.name}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPreviewOpen(false)}>Close</Button>
            <Button onClick={() => setPreviewOpen(false)}><Download className="h-3.5 w-3.5" /> Export Summary</Button>
          </>
        }
      >
        <div className="space-y-3">
          {selectedTemplate?.sections.filter((s) => s.visible).sort((a, b) => a.order - b.order).map((section) => (
            <div key={section.id} className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <p className="mb-1 text-xs font-semibold text-teal-600 dark:text-teal-400">{section.label}</p>
              <p className="text-sm text-neutral-700 dark:text-neutral-300">
                {previewData[section.label] || 'Not available in source report.'}
              </p>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}
