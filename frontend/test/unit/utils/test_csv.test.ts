import { describe, expect, it } from 'vitest';

import { parseCsv } from '../../../src/utils/csv';

describe('parseCsv', () => {
  it('parses quoted fields with escaped quotes, custom delimiter, and CRLF line endings', () => {
    const csv = [
      'name;note;city',
      '"Ada";"He said ""hello""; then left";"New',
      'York"',
      '"Grace";"plain";"Arlington"',
    ].join('\r\n');

    const parsed = parseCsv(csv, { delimiter: ';' });

    expect(parsed.columns).toEqual(['name', 'note', 'city']);
    expect(parsed.rows).toHaveLength(2);
    expect(parsed.rows[0]).toEqual({
      name: 'Ada',
      note: 'He said "hello"; then left',
      city: 'New\r\nYork',
    });
    expect(parsed.rows[1]).toEqual({
      name: 'Grace',
      note: 'plain',
      city: 'Arlington',
    });
  });

  it('trims headers and renames exact duplicate header names', () => {
    const parsed = parseCsv([' phone ,phone', '111,222'].join('\n'));

    expect(parsed.columns).toEqual(['phone', 'phone_2']);
    expect(parsed.headerRenames).toEqual([{ original: 'phone', renamed: 'phone_2' }]);
    expect(parsed.rows[0]).toEqual({
      phone: '111',
      phone_2: '222',
    });
  });

  it('skips rows where all values are blank after trimming', () => {
    const parsed = parseCsv(['id,name', '1,Ada', ',', '  ,  ', '2,Grace'].join('\n'));

    expect(parsed.columns).toEqual(['id', 'name']);
    expect(parsed.rows).toEqual([
      { id: '1', name: 'Ada' },
      { id: '2', name: 'Grace' },
    ]);
  });

  it('enforces maxRows on returned data records', () => {
    const parsed = parseCsv(['id,name', '1,Ada', '2,Grace', '3,Alan'].join('\n'), {
      maxRows: 2,
    });

    expect(parsed.rows).toEqual([
      { id: '1', name: 'Ada' },
      { id: '2', name: 'Grace' },
    ]);
  });

  it('throws on CSV with unclosed quoted field', () => {
    expect(() => parseCsv('name,desc\nAda,"Her name is')).toThrow(
      'CSV contains an unclosed quoted field.',
    );
  });

  it('applies normalized-key dedupe rules after CSV header parsing', () => {
    const parsed = parseCsv(['Patient ID,patient-id,patient_id', '1,2,3'].join('\n'));

    expect(parsed.columns).toEqual(['Patient ID', 'patient-id_2', 'patient_id_3']);
    expect(parsed.headerRenames).toEqual([
      { original: 'patient-id', renamed: 'patient-id_2' },
      { original: 'patient_id', renamed: 'patient_id_3' },
    ]);
    expect(parsed.rows[0]).toEqual({
      'Patient ID': '1',
      patient_id_3: '3',
      'patient-id_2': '2',
    });
  });
});
