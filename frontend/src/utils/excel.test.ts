import { describe, expect, it } from 'vitest';
import * as XLSX from 'xlsx';

import { parseExcel } from './excel';

describe('parseExcel', () => {
  it('keeps row alignment when headers contain empty columns', async () => {
    const workbook = XLSX.utils.book_new();
    const sheet = XLSX.utils.aoa_to_sheet([
      ['first', '', 'last', 'age'],
      ['Ada', '', 'Lovelace', 36],
    ]);
    XLSX.utils.book_append_sheet(workbook, sheet, 'Sheet1');
    const buffer = XLSX.write(workbook, { type: 'array' });

    const parsed = await parseExcel(buffer);

    expect(parsed.columns).toEqual(['first', 'last', 'age']);
    expect(parsed.rows).toHaveLength(1);
    expect(parsed.rows[0]).toEqual({
      first: 'Ada',
      last: 'Lovelace',
      age: '36',
    });
  });

  it('dedupes duplicate headers so values are not overwritten', async () => {
    const workbook = XLSX.utils.book_new();
    const sheet = XLSX.utils.aoa_to_sheet([
      ['phone', 'phone', 'phone'],
      ['111', '222', '333'],
    ]);
    XLSX.utils.book_append_sheet(workbook, sheet, 'Sheet1');
    const buffer = XLSX.write(workbook, { type: 'array' });

    const parsed = await parseExcel(buffer);

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
