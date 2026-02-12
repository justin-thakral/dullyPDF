import { beforeEach, describe, expect, it, vi } from 'vitest';

const { readXlsxFileMock } = vi.hoisted(() => ({
  readXlsxFileMock: vi.fn(),
}));

vi.mock('read-excel-file', () => ({
  default: readXlsxFileMock,
}));

import { parseCsv } from '../../../src/utils/csv';
import { parseExcel, parseExcelTable } from '../../../src/utils/excel';

describe('parseExcelTable', () => {
  it('parses headers, skips empty rows, dedupes normalized keys, and enforces maxRows', () => {
    const parsed = parseExcelTable(
      [
        ['Phone Number', 'phone-number', 'Name'],
        ['111', '222', 'Ada'],
        ['', '', ''],
        ['333', '444', 'Grace'],
      ],
      { maxRows: 1 },
    );

    expect(parsed.columns).toEqual(['Phone Number', 'phone-number_2', 'Name']);
    expect(parsed.headerRenames).toEqual([
      { original: 'phone-number', renamed: 'phone-number_2' },
    ]);
    expect(parsed.rows).toEqual([
      {
        'Phone Number': '111',
        'phone-number_2': '222',
        Name: 'Ada',
      },
    ]);
  });

  it('matches CSV normalization semantics for equivalent headers and values', () => {
    const excelParsed = parseExcelTable([
      ['Patient ID', 'patient-id', 'patient_id'],
      ['1', '2', '3'],
    ]);
    const csvParsed = parseCsv('Patient ID,patient-id,patient_id\n1,2,3');

    expect(excelParsed.columns).toEqual(csvParsed.columns);
    expect(excelParsed.rows).toEqual(csvParsed.rows);
    expect(excelParsed.headerRenames).toEqual(csvParsed.headerRenames);
  });
});

describe('parseExcel workbook parsing', () => {
  beforeEach(() => {
    readXlsxFileMock.mockReset();
  });

  it('uses sheet metadata when available and reports the selected sheet name', async () => {
    readXlsxFileMock
      .mockResolvedValueOnce([
        { id: 'sheet-a', name: 'Main' },
        { id: 'sheet-b', name: 'Patients' },
      ])
      .mockResolvedValueOnce([
        ['id', 'name'],
        [1, 'Ada'],
      ]);

    const parsed = await parseExcel(new Uint8Array([1, 2, 3]).buffer, { sheetIndex: 1 });

    expect(readXlsxFileMock).toHaveBeenNthCalledWith(1, expect.any(ArrayBuffer), { getSheets: true });
    expect(readXlsxFileMock).toHaveBeenNthCalledWith(2, expect.any(ArrayBuffer), { sheet: 'sheet-b' });
    expect(parsed.sheetName).toBe('Patients');
    expect(parsed.columns).toEqual(['id', 'name']);
    expect(parsed.rows).toEqual([{ id: '1', name: 'Ada' }]);
  });

  it('falls back to default workbook parse when metadata loading fails', async () => {
    readXlsxFileMock
      .mockRejectedValueOnce(new Error('sheet metadata unavailable'))
      .mockResolvedValueOnce([
        ['id', 'name'],
        [1, 'Ada'],
      ]);

    const parsed = await parseExcel(new Uint8Array([9, 9, 9]).buffer);

    expect(readXlsxFileMock).toHaveBeenNthCalledWith(1, expect.any(ArrayBuffer), { getSheets: true });
    expect(readXlsxFileMock).toHaveBeenNthCalledWith(2, expect.any(ArrayBuffer));
    expect(parsed.sheetName).toBeNull();
    expect(parsed.columns).toEqual(['id', 'name']);
    expect(parsed.rows).toEqual([{ id: '1', name: 'Ada' }]);
  });

  it('handles empty workbooks and falls back to first sheet when sheetIndex is out of range', async () => {
    readXlsxFileMock
      .mockResolvedValueOnce([{ id: 'first-sheet', name: '' }])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([]);

    const parsed = await parseExcel(new Uint8Array([4, 5, 6]).buffer, { sheetIndex: 99 });

    expect(readXlsxFileMock).toHaveBeenNthCalledWith(1, expect.any(ArrayBuffer), { getSheets: true });
    expect(readXlsxFileMock).toHaveBeenNthCalledWith(2, expect.any(ArrayBuffer), { sheet: 'first-sheet' });
    expect(readXlsxFileMock).toHaveBeenNthCalledWith(3, expect.any(ArrayBuffer));
    expect(parsed).toEqual({
      columns: [],
      rows: [],
      sheetName: null,
    });
  });
});
