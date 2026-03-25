import { describe, expect, it } from 'vitest';

import type { PdfField, RadioGroupSuggestion } from '../../../src/types';
import {
  applyRadioGroupSuggestion,
  buildRadioSuggestionFieldMap,
  isRadioGroupSuggestionApplied,
  resolveRadioGroupSuggestionTargets,
} from '../../../src/utils/radioGroupSuggestions';

function makeCheckbox(id: string, name: string, x: number): PdfField {
  return {
    id,
    name,
    type: 'checkbox',
    page: 1,
    rect: { x, y: 10, width: 14, height: 14 },
    value: null,
  };
}

const SUGGESTION: RadioGroupSuggestion = {
  id: 'marital-status',
  suggestedType: 'radio_group',
  groupKey: 'marital_status',
  groupLabel: 'Marital Status',
  sourceField: 'marital_status_value',
  suggestedFields: [
    { fieldId: 'single', fieldName: 'status_single', optionKey: 'single', optionLabel: 'Single' },
    { fieldId: 'married', fieldName: 'status_married', optionKey: 'married', optionLabel: 'Married' },
  ],
  selectionReason: 'enum',
};

describe('radioGroupSuggestions', () => {
  it('resolves suggestion targets by field id and field name', () => {
    const targets = resolveRadioGroupSuggestionTargets(
      [
        makeCheckbox('single', 'status_single', 10),
        makeCheckbox('married', 'status_married', 40),
      ],
      SUGGESTION,
    );

    expect(targets.map((entry) => entry.field.id)).toEqual(['single', 'married']);
    expect(targets.map((entry) => entry.optionKey)).toEqual(['single', 'married']);
  });

  it('applies a suggestion as an ai_suggestion radio group', () => {
    const nextFields = applyRadioGroupSuggestion(
      [
        makeCheckbox('single', 'status_single', 10),
        makeCheckbox('married', 'status_married', 40),
      ],
      SUGGESTION,
    );

    expect(nextFields.map((field) => field.type)).toEqual(['radio', 'radio']);
    expect(nextFields[0].radioGroupId).toBe('marital-status');
    expect(nextFields[0].radioGroupKey).toBe('marital_status_value');
    expect(nextFields[0].radioGroupSource).toBe('ai_suggestion');
    expect(nextFields[1].radioOptionKey).toBe('married');
    expect(isRadioGroupSuggestionApplied(nextFields, SUGGESTION)).toBe(true);
  });

  it('builds a field lookup keyed by the highest-confidence suggestion', () => {
    const fields = [
      makeCheckbox('single', 'status_single', 10),
      makeCheckbox('married', 'status_married', 40),
    ];
    const weaker: RadioGroupSuggestion = {
      ...SUGGESTION,
      id: 'weaker',
      confidence: 0.2,
    };
    const stronger: RadioGroupSuggestion = {
      ...SUGGESTION,
      id: 'stronger',
      confidence: 0.9,
    };

    const lookup = buildRadioSuggestionFieldMap(fields, [weaker, stronger]);

    expect(lookup.get('single')?.id).toBe('stronger');
    expect(lookup.get('married')?.id).toBe('stronger');
  });
});
