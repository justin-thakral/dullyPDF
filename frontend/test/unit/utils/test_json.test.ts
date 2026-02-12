import { describe, expect, it } from 'vitest';

import { parseJsonDataSource } from '../../../src/utils/json';

describe('parseJsonDataSource', () => {
  it('parses object payloads with explicit schema fields and infers missing types', () => {
    const parsed = parseJsonDataSource(
      JSON.stringify({
        schema: {
          fields: [
            { name: 'id', type: 'int' },
            { name: 'active' },
            { name: 'joined' },
          ],
        },
        rows: [
          { id: '1', active: 'true', joined: '2025-01-01', extra: 'x' },
          { id: '2', active: 'false', joined: '2024-12-31', extra: 'y' },
        ],
      }),
    );

    expect(parsed.columns).toEqual(['id', 'active', 'joined']);
    expect(parsed.rows).toEqual([
      { id: '1', active: 'true', joined: '2025-01-01' },
      { id: '2', active: 'false', joined: '2024-12-31' },
    ]);
    expect(parsed.schema).toEqual({
      fields: [
        { name: 'id', type: 'int' },
        { name: 'active', type: 'bool' },
        { name: 'joined', type: 'date' },
      ],
      sampleCount: 2,
    });
  });

  it('extracts schema from columns metadata and aligns dedupe with normalized columns', () => {
    const parsed = parseJsonDataSource(
      JSON.stringify({
        columns: ['Patient Id', 'patient-id', 'DOB'],
        data: [{ 'Patient Id': '1', 'patient-id': '2', DOB: '2024-10-01', ignored: 'x' }],
      }),
    );

    expect(parsed.columns).toEqual(['Patient Id', 'patient-id_2', 'DOB']);
    expect(parsed.headerRenames).toEqual([
      { original: 'patient-id', renamed: 'patient-id_2' },
    ]);
    expect(parsed.rows).toEqual([
      {
        'Patient Id': '1',
        'patient-id_2': '2',
        DOB: '2024-10-01',
      },
    ]);
    expect(parsed.schema).toEqual({
      fields: [
        { name: 'Patient Id', type: 'bool' },
        { name: 'patient-id_2', type: 'int' },
        { name: 'DOB', type: 'date' },
      ],
      sampleCount: 1,
    });
  });

  it('parses line-delimited JSON records and flattens nested fields deterministically', () => {
    const parsed = parseJsonDataSource(
      ['{"name":"Ada","meta":{"year":1815}}', '{"name":"Grace","meta":{"year":1906}}'].join(
        '\n',
      ),
    );

    expect(parsed.columns).toEqual(['name', 'meta_year']);
    expect(parsed.rows).toEqual([
      { name: 'Ada', meta_year: 1815 },
      { name: 'Grace', meta_year: 1906 },
    ]);
    expect(parsed.schema).toEqual({
      fields: [
        { name: 'name', type: 'string' },
        { name: 'meta_year', type: 'int' },
      ],
      sampleCount: 2,
    });
  });

  it('enforces maxDepth flattening by stringifying deep nested objects at the cutoff', () => {
    const parsed = parseJsonDataSource(
      JSON.stringify({
        rows: [
          {
            id: 1,
            profile: {
              name: 'Ada',
              contact: {
                address: { city: 'London' },
              },
            },
          },
        ],
      }),
      { maxDepth: 1 },
    );

    expect(parsed.columns).toEqual(['id', 'profile_name', 'profile_contact_address']);
    expect(parsed.rows).toEqual([
      {
        id: 1,
        profile_name: 'Ada',
        profile_contact_address: '{"city":"London"}',
      },
    ]);
  });

  it('normalizes array-based rows with header rows, generated columns, and maxRows limits', () => {
    const parsed = parseJsonDataSource(
      JSON.stringify([
        ['first', 'age'],
        ['Ada', 36, 'x'],
        ['Grace', 85],
      ]),
      { maxRows: 1 },
    );

    expect(parsed.columns).toEqual(['first', 'age', 'column_3']);
    expect(parsed.rows).toEqual([{ first: 'Ada', age: 36, column_3: 'x' }]);
    expect(parsed.schema).toEqual({
      fields: [
        { name: 'first', type: 'string' },
        { name: 'age', type: 'int' },
        { name: 'column_3', type: 'string' },
      ],
      sampleCount: 1,
    });
  });

  it('normalizes primitive payloads into a single value column', () => {
    const parsed = parseJsonDataSource('42');

    expect(parsed.columns).toEqual(['value']);
    expect(parsed.rows).toEqual([{ value: 42 }]);
    expect(parsed.schema).toEqual({
      fields: [{ name: 'value', type: 'int' }],
      sampleCount: 1,
    });
  });

  it('rejects mixed array and object row formats in array payloads', () => {
    expect(() =>
      parseJsonDataSource(
        JSON.stringify([
          ['name'],
          { name: 'Ada' },
        ]),
      ),
    ).toThrow('JSON rows must be arrays or objects, not a mix of both.');
  });

  it('throws on empty, invalid, and schema-without-field-name inputs', () => {
    expect(() => parseJsonDataSource('')).toThrow('JSON file is empty.');
    expect(() => parseJsonDataSource('{invalid')).toThrow('Invalid JSON file.');
    expect(() => parseJsonDataSource(JSON.stringify({ fields: [{ name: '   ' }] }))).toThrow(
      'JSON schema has no field names.',
    );
  });
});
