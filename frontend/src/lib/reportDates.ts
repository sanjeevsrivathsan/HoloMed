/**
 * Report-date choices shown during review. Detected dates are only suggestions; the user confirms.
 * Kept free of path aliases so it runs under `node --test`.
 */

export type DateKind = 'collected' | 'received' | 'registered' | 'reported' | 'report_date';

export interface DetectedDate {
  kind: DateKind;
  label: string;          // label as printed
  text: string;           // date as printed
  value: string | null;   // ISO date when unambiguous
  alternatives: string[]; // both readings when the day/month order is unknown
}

export interface DateOption {
  value: string;
  labels: string[];
  printed: string[];
  ambiguous: boolean;
}

export const dateKindLabels: Record<DateKind, string> = {
  collected: 'Collected',
  received: 'Received',
  registered: 'Registered',
  reported: 'Reported',
  report_date: 'Date',
};

/** One option per distinct date; an ambiguous day/month date contributes both readings. */
export function dateOptions(candidates: DetectedDate[]): DateOption[] {
  const byValue = new Map<string, DateOption>();
  for (const c of candidates) {
    const readings = c.value ? [c.value] : c.alternatives;
    readings.forEach((value, i) => {
      const label = c.value ? dateKindLabels[c.kind]
        : `${dateKindLabels[c.kind]} (if read as ${i === 0 ? 'day/month' : 'month/day'})`;
      const opt = byValue.get(value) ?? { value, labels: [], printed: [], ambiguous: false };
      if (!opt.labels.includes(label)) opt.labels.push(label);
      const printed = `${c.label}: ${c.text}`;
      if (!opt.printed.includes(printed)) opt.printed.push(printed);
      opt.ambiguous = opt.ambiguous || !c.value;
      byValue.set(value, opt);
    });
  }
  return [...byValue.values()];
}

/** A single unambiguous detected date can be accepted with one click; anything else needs a choice. */
export function needsExplicitChoice(options: DateOption[]): boolean {
  return !(options.length === 1 && !options[0].ambiguous);
}
