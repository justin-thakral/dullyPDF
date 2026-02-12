import { describe, expect, it } from 'vitest';

import {
  dedupeColumnsByNormalizedKey,
  normaliseDataKey,
  pickIdentifierKey,
} from '../../../src/utils/dataSource';

describe('pickIdentifierKey', () => {
  it('prefers exact known identifiers case-insensitively', () => {
    expect(pickIdentifierKey(['Record ID', 'MRN', 'patient_id'])).toBe('MRN');
  });

  it('falls back to contains-mrn, then *_id, then first column', () => {
    expect(pickIdentifierKey(['externalMrnValue', 'code'])).toBe('externalMrnValue');
    expect(pickIdentifierKey(['name', 'visit_id', 'code'])).toBe('visit_id');
    expect(pickIdentifierKey(['name', 'code'])).toBe('name');
  });

  it('returns null when no columns are provided', () => {
    expect(pickIdentifierKey([])).toBeNull();
  });
});

describe('normaliseDataKey', () => {
  it('normalizes spacing, hyphens, case, and special characters', () => {
    expect(normaliseDataKey('  Patient-Name (Legal)!  ')).toBe('patient_name_legal');
  });
});

describe('dedupeColumnsByNormalizedKey', () => {
  it('renames normalized-key collisions, rewrites row keys, and preserves non-column keys', () => {
    const deduped = dedupeColumnsByNormalizedKey(
      ['Phone Number', 'phone-number', '', 'Custom ID'],
      [
        {
          'Phone Number': '111',
          'phone-number': '222',
          '': 'blank',
          'Custom ID': 'A1',
          extra: 'keep',
        },
      ],
    );

    expect(deduped.columns).toEqual([
      'Phone Number',
      'phone-number_2',
      'column_3',
      'Custom ID',
    ]);
    expect(deduped.headerRenames).toEqual([
      { original: 'phone-number', renamed: 'phone-number_2' },
      { original: '', renamed: 'column_3' },
    ]);
    expect(deduped.rows).toEqual([
      {
        'Phone Number': '111',
        'phone-number_2': '222',
        column_3: 'blank',
        'Custom ID': 'A1',
        extra: 'keep',
      },
    ]);
  });

  it('returns original rows with no rename metadata when no collisions exist', () => {
    const rows = [{ id: '1', name: 'Ada' }];
    const deduped = dedupeColumnsByNormalizedKey(['id', 'name'], rows);

    expect(deduped.columns).toEqual(['id', 'name']);
    expect(deduped.rows).toBe(rows);
    expect(deduped.headerRenames).toBeUndefined();
  });
});
