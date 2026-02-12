import { describe, expect, it } from 'vitest';

import { FIELD_TYPES, fieldTypeLabel } from '../../../src/utils/fieldUi';

describe('fieldUi utils', () => {
  it('keeps field type ordering stable for dropdown rendering', () => {
    expect(FIELD_TYPES).toEqual(['text', 'date', 'signature', 'checkbox']);
  });

  it('maps known field types to expected labels', () => {
    expect(fieldTypeLabel('text')).toBe('Text');
    expect(fieldTypeLabel('date')).toBe('Date');
    expect(fieldTypeLabel('signature')).toBe('Signature');
    expect(fieldTypeLabel('checkbox')).toBe('Checkbox');
  });

  it('uses a generic fallback label for unknown field types', () => {
    expect(fieldTypeLabel('custom_field' as any)).toBe('Field');
  });
});
