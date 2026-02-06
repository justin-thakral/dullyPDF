import { describe, expect, it } from 'vitest';

import { parseExcel, parseExcelTable } from './excel';

// read-excel-file's browser build expects a DOMParser; provide a lightweight polyfill so
// we can run these tests in Vitest's default node environment (avoids pulling in jsdom).
import { DOMParser as XmlDomParser } from '@xmldom/xmldom';

(globalThis as any).DOMParser = XmlDomParser as any;

describe('parseExcel', () => {
  it('parses the shipped sample workbook', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const file = readFileSync(resolve(process.cwd(), 'public', 'sample-data', 'healthdb_vw_form_fields.xlsx'));
    const buffer = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength);

    const parsed = await parseExcel(buffer);

    expect(parsed.sheetName === null || typeof parsed.sheetName === 'string').toBe(true);
    expect(parsed.columns.length).toBeGreaterThan(0);
  });

  it('keeps row alignment when headers contain empty columns', async () => {
    const parsed = parseExcelTable([
      ['first', '', 'last', 'age'],
      ['Ada', '', 'Lovelace', 36],
    ]);

    expect(parsed.columns).toEqual(['first', 'last', 'age']);
    expect(parsed.rows).toHaveLength(1);
    expect(parsed.rows[0]).toEqual({
      first: 'Ada',
      last: 'Lovelace',
      age: '36',
    });
  });

  it('dedupes duplicate headers so values are not overwritten', async () => {
    const parsed = parseExcelTable([
      ['phone', 'phone', 'phone'],
      ['111', '222', '333'],
    ]);

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
