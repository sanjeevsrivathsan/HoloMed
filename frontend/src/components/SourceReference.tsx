import { FileText, Link2, Image, ExternalLink } from 'lucide-react';
import type { SourceReference } from '@/lib/types';

const typeIcons = {
  document: FileText,
  measurement: Link2,
  image: Image,
};

export function SourceReferenceItem({ reference }: { reference: SourceReference }) {
  const Icon = typeIcons[reference.type] || FileText;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-neutral-200 px-3 py-2 dark:border-neutral-800">
      <Icon className="h-4 w-4 shrink-0 text-neutral-400" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-neutral-700 dark:text-neutral-300">{reference.label}</p>
        <p className="truncate text-xs text-neutral-400">{reference.location}</p>
      </div>
      <button
        className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 dark:hover:bg-neutral-800"
        aria-label="Open source reference"
      >
        <ExternalLink className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function SourceReferenceList({ references }: { references: SourceReference[] }) {
  if (references.length === 0) return null;
  return (
    <div className="space-y-2">
      {references.map((ref) => (
        <SourceReferenceItem key={ref.id} reference={ref} />
      ))}
    </div>
  );
}
