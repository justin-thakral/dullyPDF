import { describe, expect, it } from 'vitest';

import {
  ALLOWED_SCHEMA_TYPES,
  inferSchemaFromRows,
  parseSchemaText,
} from '../../../src/utils/schema';

describe('inferSchemaFromRows', () => {
  it('infers bool, int, date, and string types across mixed column samples', () => {
    const schema = inferSchemaFromRows(
      ['active', 'count', 'dob', 'note'],
      [
        { active: 'true', count: '42', dob: '2024-01-31', note: 'alpha' },
        { active: 'No', count: '-7', dob: '01/30/2024', note: '100a' },
      ],
    );

    expect(schema).toEqual({
      fields: [
        { name: 'active', type: 'bool' },
        { name: 'count', type: 'int' },
        { name: 'dob', type: 'date' },
        { name: 'note', type: 'string' },
      ],
      sampleCount: 2,
    });
  });

  it('rejects impossible calendar dates like Feb 30 and Apr 31', () => {
    const schema = inferSchemaFromRows(
      ['bad_date'],
      [
        { bad_date: '2024-02-30' },
        { bad_date: '2024-04-31' },
        { bad_date: '2024-06-31' },
      ],
    );

    expect(schema.fields).toEqual([{ name: 'bad_date', type: 'string' }]);
  });

  it('respects sampleSize when inferring column types', () => {
    const schema = inferSchemaFromRows(
      ['flag'],
      [{ flag: 'yes' }, { flag: 'no' }, { flag: 'maybe' }],
      { sampleSize: 2 },
    );

    expect(schema.sampleCount).toBe(2);
    expect(schema.fields).toEqual([{ name: 'flag', type: 'bool' }]);
  });
});

describe('parseSchemaText', () => {
  it('parses comments, dedupes names, supports optional types, and falls back invalid types', () => {
    const schema = parseSchemaText(
      [
        '# comment',
        'mrn:int',
        'visit_date:date',
        'active:bool',
        'name',
        'name:string',
        'bad_type:FLOAT',
        'spaced_field: INT',
      ].join('\n'),
    );

    expect(schema).toEqual({
      fields: [
        { name: 'mrn', type: 'int' },
        { name: 'visit_date', type: 'date' },
        { name: 'active', type: 'bool' },
        { name: 'name', type: 'string' },
        { name: 'bad_type', type: 'string' },
        { name: 'spaced_field', type: 'int' },
      ],
      sampleCount: 0,
    });
  });
});

describe('ALLOWED_SCHEMA_TYPES', () => {
  it('contains only the supported schema type set', () => {
    expect(new Set(ALLOWED_SCHEMA_TYPES)).toEqual(
      new Set(['string', 'int', 'date', 'bool']),
    );
    expect(ALLOWED_SCHEMA_TYPES.has('float' as any)).toBe(false);
  });
});
