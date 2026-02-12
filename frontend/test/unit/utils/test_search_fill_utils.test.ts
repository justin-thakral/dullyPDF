import { describe, expect, it } from 'vitest';

import {
  coerceCheckboxBoolean,
  coerceCheckboxPresence,
  getNumericSuffixBase,
  normalizeCheckboxValueMap,
  splitCheckboxListValue,
} from '../../../src/utils/searchFill';

describe('searchFill helpers', () => {
  describe('coerceCheckboxBoolean', () => {
    it('coerces booleans, numbers, and common string tokens', () => {
      expect(coerceCheckboxBoolean(true)).toBe(true);
      expect(coerceCheckboxBoolean(false)).toBe(false);
      expect(coerceCheckboxBoolean(1)).toBe(true);
      expect(coerceCheckboxBoolean(0)).toBe(false);
      expect(coerceCheckboxBoolean(-2)).toBe(true);
      expect(coerceCheckboxBoolean(' yes ')).toBe(true);
      expect(coerceCheckboxBoolean('checked')).toBe(true);
      expect(coerceCheckboxBoolean('0')).toBe(false);
      expect(coerceCheckboxBoolean('off')).toBe(false);
      expect(coerceCheckboxBoolean('f')).toBe(false);
    });

    it('returns null for nullish and ambiguous/unrecognized tokens', () => {
      expect(coerceCheckboxBoolean(null)).toBeNull();
      expect(coerceCheckboxBoolean(undefined)).toBeNull();
      expect(coerceCheckboxBoolean(Number.NaN)).toBeNull();
      expect(coerceCheckboxBoolean('y/n')).toBeNull();
      expect(coerceCheckboxBoolean('maybe')).toBeNull();
      expect(coerceCheckboxBoolean({ value: true })).toBeNull();
    });
  });

  describe('coerceCheckboxPresence', () => {
    it('keeps direct boolean coercion semantics when available', () => {
      expect(coerceCheckboxPresence('yes')).toBe(true);
      expect(coerceCheckboxPresence('no')).toBe(false);
      expect(coerceCheckboxPresence(0)).toBe(false);
      expect(coerceCheckboxPresence(2)).toBe(true);
    });

    it('treats ambiguous normalized tokens as null', () => {
      expect(coerceCheckboxPresence(Number.NaN)).toBeNull();
      expect(coerceCheckboxPresence('y/n')).toBeNull();
      expect(coerceCheckboxPresence('yes-no')).toBeNull();
      expect(coerceCheckboxPresence('true/false')).toBeNull();
      expect(coerceCheckboxPresence('0/1')).toBeNull();
    });

    it('treats false-presence tokens as false and meaningful values as true', () => {
      expect(coerceCheckboxPresence('n/a')).toBe(false);
      expect(coerceCheckboxPresence('not available')).toBe(false);
      expect(coerceCheckboxPresence('unknown')).toBe(false);
      expect(coerceCheckboxPresence('some selected value')).toBe(true);
      expect(coerceCheckboxPresence('')).toBeNull();
    });

    it('handles array/object inputs with presence semantics', () => {
      expect(coerceCheckboxPresence([])).toBe(false);
      expect(coerceCheckboxPresence(['x'])).toBe(true);
      expect(coerceCheckboxPresence({ selected: true })).toBe(true);
    });
  });

  describe('splitCheckboxListValue', () => {
    it('splits string values across supported delimiters', () => {
      expect(splitCheckboxListValue('a, b; c|d / e')).toEqual(['a', 'b', 'c', 'd', 'e']);
      expect(splitCheckboxListValue('alpha')).toEqual(['alpha']);
    });

    it('preserves ambiguous and false-presence tokens as single entries', () => {
      expect(splitCheckboxListValue('y/n')).toEqual(['y/n']);
      expect(splitCheckboxListValue('true/false')).toEqual(['true/false']);
      expect(splitCheckboxListValue('n/a')).toEqual(['n/a']);
    });

    it('handles arrays, scalars, and empty values', () => {
      expect(splitCheckboxListValue([' a ', ' ', 'b'])).toEqual(['a', 'b']);
      expect(splitCheckboxListValue(42)).toEqual(['42']);
      expect(splitCheckboxListValue(null)).toEqual([]);
      expect(splitCheckboxListValue('   ')).toEqual([]);
    });
  });

  describe('normalizeCheckboxValueMap', () => {
    it('normalizes keys/values and skips empty normalized keys', () => {
      const valueMap = {
        ' Yes ': 'Y',
        'In Progress': 'In Progress',
        '': 'ignored',
        'a-b': 'One Two',
      };

      expect(normalizeCheckboxValueMap(valueMap)).toEqual({
        yes: 'y',
        in_progress: 'in_progress',
        a_b: 'one_two',
      });
    });

    it('preserves original mapped values when normalization removes all characters', () => {
      expect(normalizeCheckboxValueMap({ choice: '@@@' })).toEqual({ choice: '@@@' });
      expect(normalizeCheckboxValueMap(undefined)).toBeUndefined();
    });
  });

  describe('getNumericSuffixBase', () => {
    it('returns the base name for trailing numeric suffixes', () => {
      expect(getNumericSuffixBase('emergency_contact_name_2')).toBe('emergency_contact_name');
      expect(getNumericSuffixBase('field_10')).toBe('field');
      expect(getNumericSuffixBase('group_option_003')).toBe('group_option');
    });

    it('returns null when there is no valid trailing numeric suffix', () => {
      expect(getNumericSuffixBase('name_')).toBeNull();
      expect(getNumericSuffixBase('name_2_extra')).toBeNull();
      expect(getNumericSuffixBase('plain_name')).toBeNull();
    });
  });
});
