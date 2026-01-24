import { describe, expect, it } from 'vitest';

import { dedupeColumnsByNormalizedKey } from './dataSource';

describe('dedupeColumnsByNormalizedKey', () => {
  it('renames normalized key collisions and rewrites rows', () => {
    const columns = ['Phone', 'phone', 'patient-name'];
    const rows = [
      {
        Phone: '111',
        phone: '222',
        'patient-name': 'Alice',
      },
    ];

    const deduped = dedupeColumnsByNormalizedKey(columns, rows);

    expect(deduped.columns).toEqual(['Phone', 'phone_2', 'patient-name']);
    expect(deduped.headerRenames).toEqual([{ original: 'phone', renamed: 'phone_2' }]);
    expect(deduped.rows[0]).toEqual({
      Phone: '111',
      phone_2: '222',
      'patient-name': 'Alice',
    });
  });
});
