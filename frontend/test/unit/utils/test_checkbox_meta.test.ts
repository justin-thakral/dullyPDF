import { describe, expect, it } from 'vitest';

import type { PdfField } from '../../../src/types';
import { computeCheckboxMeta } from '../../../src/utils/checkboxMeta';

function checkboxField(overrides: Partial<PdfField> & Pick<PdfField, 'id' | 'name'>): PdfField {
  return {
    id: overrides.id,
    name: overrides.name,
    type: 'checkbox',
    page: 1,
    rect: { x: 0, y: 0, width: 12, height: 12 },
    ...overrides,
  };
}

describe('computeCheckboxMeta', () => {
  it('uses explicit metadata when both group and option are provided', () => {
    const fields = [
      checkboxField({
        id: 'explicit',
        name: 'ignored',
        groupKey: 'Patient Consent',
        optionKey: 'Allow Email',
        optionLabel: 'Allow Email',
      }),
    ];

    const metaById = computeCheckboxMeta(fields, []);

    expect(metaById.get('explicit')).toEqual({
      groupKey: 'patient_consent',
      optionKey: 'allow_email',
      optionLabel: 'Allow Email',
    });
  });

  it('strips i_/checkbox_ prefixes and aligns to row-key groups when metadata conflicts', () => {
    const fields = [
      checkboxField({
        id: 'i_prefix',
        name: 'i_patient_consent',
        groupKey: 'stored_group',
        optionKey: 'stored_option',
      }),
      checkboxField({
        id: 'checkbox_prefix',
        name: 'checkbox_contact_permission',
        groupKey: 'different_group',
        optionKey: 'different_option',
      }),
    ];

    const metaById = computeCheckboxMeta(fields, ['patient_consent', 'contact_permission']);

    expect(metaById.get('i_prefix')).toEqual({
      groupKey: 'patient_consent',
      optionKey: 'yes',
      optionLabel: undefined,
    });
    expect(metaById.get('checkbox_prefix')).toEqual({
      groupKey: 'contact_permission',
      optionKey: 'yes',
      optionLabel: undefined,
    });
  });

  it('infers shared-prefix groups and keeps multi-token option suffixes', () => {
    const fields = [
      checkboxField({ id: 'full_time', name: 'employment_status_full_time' }),
      checkboxField({ id: 'part_time', name: 'employment_status_part_time' }),
    ];

    const metaById = computeCheckboxMeta(fields, []);

    expect(metaById.get('full_time')).toEqual({
      groupKey: 'employment_status',
      optionKey: 'full_time',
      optionLabel: undefined,
    });
    expect(metaById.get('part_time')).toEqual({
      groupKey: 'employment_status',
      optionKey: 'part_time',
      optionLabel: undefined,
    });
  });

  it('uses boolean token fallback and defaults unmatched names to yes', () => {
    const fields = [
      checkboxField({ id: 'yes_token', name: 'smoker_yes' }),
      checkboxField({ id: 'false_token', name: 'pregnant_false' }),
      checkboxField({ id: 'default_yes', name: 'allergies' }),
    ];

    const metaById = computeCheckboxMeta(fields, []);

    expect(metaById.get('yes_token')).toEqual({
      groupKey: 'smoker',
      optionKey: 'yes',
      optionLabel: undefined,
    });
    expect(metaById.get('false_token')).toEqual({
      groupKey: 'pregnant',
      optionKey: 'false',
      optionLabel: undefined,
    });
    expect(metaById.get('default_yes')).toEqual({
      groupKey: 'allergies',
      optionKey: 'yes',
      optionLabel: undefined,
    });
  });

  it('keeps one metadata entry per field id when option keys collide', () => {
    const fields = [
      checkboxField({ id: 'email_1', name: 'contact_method_email' }),
      checkboxField({ id: 'email_2', name: 'contact_method_email' }),
      checkboxField({ id: 'phone', name: 'contact_method_phone' }),
    ];

    const metaById = computeCheckboxMeta(fields, []);

    expect(metaById.size).toBe(3);
    expect(metaById.get('email_1')).toEqual({
      groupKey: 'contact_method',
      optionKey: 'email',
      optionLabel: undefined,
    });
    expect(metaById.get('email_2')).toEqual({
      groupKey: 'contact_method',
      optionKey: 'email',
      optionLabel: undefined,
    });
    expect(metaById.get('phone')).toEqual({
      groupKey: 'contact_method',
      optionKey: 'phone',
      optionLabel: undefined,
    });
  });
});
