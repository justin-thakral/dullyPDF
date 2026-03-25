import { describe, expect, it } from 'vitest';

import type { PdfField } from '../../../src/types';
import {
  buildNextRadioToolDraft,
  buildRadioGroups,
  convertFieldsToRadioGroup,
  createRadioFieldFromRect,
  setRadioGroupSelectedValue,
} from '../../../src/utils/radioGroups';

function makeCheckbox(id: string, name: string, x: number): PdfField {
  return {
    id,
    name,
    type: 'checkbox',
    page: 1,
    rect: { x, y: 10, width: 14, height: 14 },
  };
}

describe('radioGroups utils', () => {
  it('converts checkbox selections into an ordered radio group', () => {
    const fields = [
      makeCheckbox('field-1', 'single', 10),
      makeCheckbox('field-2', 'married', 40),
    ];
    const draft = buildNextRadioToolDraft(fields, 'Marital Status');

    const converted = convertFieldsToRadioGroup(fields, ['field-1', 'field-2'], draft);
    const radioFields = converted.filter((field) => field.type === 'radio');

    expect(radioFields).toHaveLength(2);
    expect(radioFields[0].radioGroupLabel).toBe('Marital Status');
    expect(radioFields[0].radioOptionOrder).toBe(1);

    const groups = buildRadioGroups(converted);
    expect(groups).toEqual([
      expect.objectContaining({
        label: 'Marital Status',
        key: 'marital_status',
        options: [
          expect.objectContaining({ fieldId: 'field-1' }),
          expect.objectContaining({ fieldId: 'field-2' }),
        ],
      }),
    ]);
  });

  it('creates new radio widgets with square geometry and unique option keys', () => {
    const draft = buildNextRadioToolDraft([], 'Coverage');
    const first = createRadioFieldFromRect([], 1, { width: 200, height: 200 }, {
      x: 10,
      y: 10,
      width: 18,
      height: 12,
    }, draft);
    const second = createRadioFieldFromRect([first], 1, { width: 200, height: 200 }, {
      x: 40,
      y: 10,
      width: 14,
      height: 14,
    }, draft);

    expect(first.type).toBe('radio');
    expect(first.rect.width).toBe(first.rect.height);
    expect(second.radioOptionKey).not.toBe(first.radioOptionKey);
  });

  it('starts a fresh conversion draft instead of appending into an unrelated radio group', () => {
    const manualDraft = buildNextRadioToolDraft([], 'Household Status');
    const firstManual = createRadioFieldFromRect([], 1, { width: 200, height: 200 }, {
      x: 10,
      y: 10,
      width: 14,
      height: 14,
    }, manualDraft);
    const secondManual = createRadioFieldFromRect([firstManual], 1, { width: 200, height: 200 }, {
      x: 40,
      y: 10,
      width: 14,
      height: 14,
    }, manualDraft);
    const existingFields = [firstManual, secondManual];

    const quickDraft = buildNextRadioToolDraft(existingFields);
    const converted = convertFieldsToRadioGroup(
      [
        ...existingFields,
        makeCheckbox('field-3', 'yes', 10),
        makeCheckbox('field-4', 'no', 40),
      ],
      ['field-3', 'field-4'],
      quickDraft,
    );
    const quickFields = converted.filter((field) => field.id === 'field-3' || field.id === 'field-4');

    expect(quickDraft.groupId).not.toBe(manualDraft.groupId);
    expect(quickFields.map((field) => field.radioGroupId)).toEqual([quickDraft.groupId, quickDraft.groupId]);
    expect(quickFields.map((field) => field.radioOptionKey)).toEqual(['option_1', 'option_2']);
    expect(quickFields.map((field) => field.radioOptionOrder)).toEqual([1, 2]);
  });

  it('keeps only one selected value inside a radio group', () => {
    const fields = convertFieldsToRadioGroup(
      [makeCheckbox('field-1', 'yes', 10), makeCheckbox('field-2', 'no', 40)],
      ['field-1', 'field-2'],
      buildNextRadioToolDraft([], 'Over 18'),
    );

    const selected = setRadioGroupSelectedValue(fields, 'field-2');

    expect(selected.find((field) => field.id === 'field-1')?.value).toBeNull();
    expect(selected.find((field) => field.id === 'field-2')?.value).toBe(
      selected.find((field) => field.id === 'field-2')?.radioOptionKey,
    );
  });
});
