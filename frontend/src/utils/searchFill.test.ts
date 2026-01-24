import { describe, expect, it } from 'vitest';

import {
  coerceCheckboxBoolean,
  coerceCheckboxPresence,
  getNumericSuffixBase,
  normalizeCheckboxValueMap,
  splitCheckboxListValue,
} from './searchFill';

describe('searchFill utils', () => {
  it('normalizes checkbox value maps for case-insensitive matching', () => {
    const valueMap = {
      Yes: 'Y',
      No: 'N',
      'In Progress': 'In Progress',
    };

    expect(normalizeCheckboxValueMap(valueMap)).toEqual({
      yes: 'y',
      no: 'n',
      in_progress: 'in_progress',
    });
  });

  it('extracts the base key for numeric suffix fallbacks', () => {
    expect(getNumericSuffixBase('emergency_contact_name_2')).toBe('emergency_contact_name');
    expect(getNumericSuffixBase('name_10')).toBe('name');
    expect(getNumericSuffixBase('name_')).toBeNull();
    expect(getNumericSuffixBase('name_2_extra')).toBeNull();
  });

  it('coerces checkbox booleans with common tokens', () => {
    expect(coerceCheckboxBoolean(true)).toBe(true);
    expect(coerceCheckboxBoolean(false)).toBe(false);
    expect(coerceCheckboxBoolean('yes')).toBe(true);
    expect(coerceCheckboxBoolean('no')).toBe(false);
    expect(coerceCheckboxBoolean('checked')).toBe(true);
    expect(coerceCheckboxBoolean('unchecked')).toBe(false);
    expect(coerceCheckboxBoolean('y/n')).toBeNull();
  });

  it('handles presence-style checkbox values', () => {
    expect(coerceCheckboxPresence('y/n')).toBeNull();
    expect(coerceCheckboxPresence('true/false')).toBeNull();
    expect(coerceCheckboxPresence('n/a')).toBe(false);
    expect(coerceCheckboxPresence('unknown')).toBe(false);
    expect(coerceCheckboxPresence('some value')).toBe(true);
    expect(coerceCheckboxPresence('')).toBeNull();
  });

  it('splits list values but preserves ambiguous tokens', () => {
    expect(splitCheckboxListValue('a/b')).toEqual(['a', 'b']);
    expect(splitCheckboxListValue('y/n')).toEqual(['y/n']);
    expect(splitCheckboxListValue('n/a')).toEqual(['n/a']);
    expect(splitCheckboxListValue([' a ', 'b'])).toEqual(['a', 'b']);
  });
});
