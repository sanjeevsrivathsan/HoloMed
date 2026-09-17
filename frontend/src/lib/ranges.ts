/**
 * Printed reference ranges → chart limits.
 *
 * Only *simple* printed ranges ("4.0 - 5.6", "<100", ">40", "70 - 99 mg/dL") produce limits.
 * Tiered ranges ("Desirable 130-159; Borderline …", "<. 100 mg/dl (Desirable); …") are shown as
 * text only and never drawn, because a single line would misrepresent them. Nothing is inferred.
 * Kept free of path aliases so it runs under `node --test`.
 */

const NUM = String.raw`\d+(?:[.,]\d+)?`;
const SIMPLE = new RegExp(
  String.raw`^\s*(?:[<>≤≥]=?\s*${NUM}|${NUM}\s*(?:-|–|—|to)\s*${NUM})\s*(?:[A-Za-zµμ%/^0-9]+)?\s*$`,
);
const BETWEEN = new RegExp(String.raw`(${NUM})\s*(?:-|–|—|to)\s*(${NUM})`);
const UPPER = new RegExp(String.raw`^\s*[<≤]=?\s*(${NUM})`);
const LOWER = new RegExp(String.raw`^\s*[>≥]=?\s*(${NUM})`);

const toNumber = (text: string) => parseFloat(text.replace(',', '.'));

export function printedBounds(range?: string | null): { lower?: number; upper?: number } {
  if (!range || !SIMPLE.test(range)) return {};
  const between = range.match(BETWEEN);
  if (between) return { lower: toNumber(between[1]), upper: toNumber(between[2]) };
  const upper = range.match(UPPER);
  if (upper) return { upper: toNumber(upper[1]) };
  const lower = range.match(LOWER);
  if (lower) return { lower: toNumber(lower[1]) };
  return {};
}
