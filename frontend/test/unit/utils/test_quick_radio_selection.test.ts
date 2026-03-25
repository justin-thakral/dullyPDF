import { describe, expect, it } from 'vitest';

import type { PdfField } from '../../../src/types';
import {
  collectQuickRadioSelection,
  fieldMatchesQuickRadioSelection,
  toQuickRadioSelectionRect,
} from '../../../src/utils/quickRadioSelection';

function makeCheckbox(id: string, rect: PdfField['rect']): PdfField {
  return {
    id,
    name: id,
    type: 'checkbox',
    page: 1,
    rect,
  };
}

describe('quickRadioSelection utils', () => {
  it('builds a rectangular marquee instead of a square drag box', () => {
    expect(
      toQuickRadioSelectionRect(
        { x: 10, y: 12 },
        { x: 40, y: 24 },
        { width: 200, height: 200 },
      ),
    ).toEqual({
      x: 10,
      y: 12,
      width: 30,
      height: 12,
    });
  });

  it('treats quick clicks as point selection instead of a default marquee', () => {
    expect(
      toQuickRadioSelectionRect(
        { x: 10, y: 12 },
        { x: 11, y: 13 },
        { width: 200, height: 200 },
      ),
    ).toBeNull();
  });

  it('uses precise coverage by default and only falls back to overlap in touch mode', () => {
    const fieldRect = { x: 20, y: 20, width: 14, height: 14 };
    const selectionRect = { x: 30, y: 20, width: 8, height: 14 };
    const point = { x: 32, y: 24 };

    expect(fieldMatchesQuickRadioSelection(fieldRect, selectionRect, point, 'precise')).toBe(false);
    expect(fieldMatchesQuickRadioSelection(fieldRect, selectionRect, point, 'touch')).toBe(true);
  });

  it('selects only checkboxes that match the marquee rule', () => {
    const fields = [
      makeCheckbox('inside', { x: 10, y: 10, width: 14, height: 14 }),
      makeCheckbox('outside', { x: 60, y: 10, width: 14, height: 14 }),
    ];

    expect(
      collectQuickRadioSelection(
        fields,
        { x: 8, y: 8, width: 24, height: 24 },
        { x: 24, y: 24 },
        'precise',
      ),
    ).toEqual(['inside']);
  });

  it('supports single-click selection when the pointer lands inside a checkbox', () => {
    const fields = [
      makeCheckbox('inside', { x: 10, y: 10, width: 14, height: 14 }),
      makeCheckbox('outside', { x: 60, y: 10, width: 14, height: 14 }),
    ];

    expect(
      collectQuickRadioSelection(
        fields,
        null,
        { x: 15, y: 15 },
        'precise',
      ),
    ).toEqual(['inside']);
  });
});
