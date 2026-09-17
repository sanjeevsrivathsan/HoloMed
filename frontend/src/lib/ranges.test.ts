import { test } from 'node:test';
import assert from 'node:assert/strict';
import { printedBounds } from './ranges.ts';

test('simple printed ranges become chart limits', () => {
  assert.deepEqual(printedBounds('4.0 - 5.6'), { lower: 4, upper: 5.6 });
  assert.deepEqual(printedBounds('70 - 99 mg/dL'), { lower: 70, upper: 99 });
  assert.deepEqual(printedBounds('<100'), { upper: 100 });
  assert.deepEqual(printedBounds('> 40'), { lower: 40 });
  assert.deepEqual(printedBounds('3,5 - 5,2'), { lower: 3.5, upper: 5.2 });
});

test('tiered or descriptive ranges are never drawn', () => {
  for (const r of [
    'Desirable > 40.0; Higher Risk < 40.0',
    'Optimal < 130; Desirable 130-159; Borderline high 160-189',
    '<. 100 mg/dl (Desirable); 100-129 mg/dl (Low risk)',
    'up to 0.3',
    'Desirable : < 4; Borderline : 4.0 - 6.0',
    '',
    null,
    undefined,
  ]) {
    assert.deepEqual(printedBounds(r), {}, String(r));
  }
});
