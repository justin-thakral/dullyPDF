import { describe, expect, it } from 'vitest';

import { parseCsv } from './csv';

describe('parseCsv', () => {
  it('keeps row alignment when headers contain empty columns', () => {
    const csv = ['first,,last,age', 'Ada,,Lovelace,36'].join('\n');
    const parsed = parseCsv(csv);

    expect(parsed.columns).toEqual(['first', 'last', 'age']);
    expect(parsed.rows).toHaveLength(1);
    expect(parsed.rows[0]).toEqual({
      first: 'Ada',
      last: 'Lovelace',
      age: '36',
    });
  });

  it('dedupes duplicate headers so values are not overwritten', () => {
    const csv = ['phone,phone,phone', '111,222,333'].join('\n');
    const parsed = parseCsv(csv);

    expect(parsed.columns).toEqual(['phone', 'phone_2', 'phone_3']);
    expect(parsed.headerRenames).toEqual([
      { original: 'phone', renamed: 'phone_2' },
      { original: 'phone', renamed: 'phone_3' },
    ]);
    expect(parsed.rows[0]).toEqual({
      phone: '111',
      phone_2: '222',
      phone_3: '333',
    });
  });
});
