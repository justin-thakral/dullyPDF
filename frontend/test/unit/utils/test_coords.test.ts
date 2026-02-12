import { describe, expect, it } from 'vitest';

import { clamp, clampRectToPage, toViewportRect } from '../../../src/utils/coords';

describe('coords utils', () => {
  it('clamps scalar values to inclusive min/max boundaries', () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-4, 0, 10)).toBe(0);
    expect(clamp(18, 0, 10)).toBe(10);
  });

  it('clamps rectangles to page bounds and enforces minimum size', () => {
    expect(
      clampRectToPage(
        { x: -10, y: 120, width: 2, height: 1 },
        { width: 100, height: 80 },
      ),
    ).toEqual({
      x: 0,
      y: 74,
      width: 6,
      height: 6,
    });
  });

  it('caps oversized rectangles to page dimensions before positioning', () => {
    expect(
      clampRectToPage(
        { x: 50, y: 20, width: 300, height: 400 },
        { width: 200, height: 150 },
      ),
    ).toEqual({
      x: 0,
      y: 0,
      width: 200,
      height: 150,
    });
  });

  it('uses the provided min size override', () => {
    expect(
      clampRectToPage(
        { x: 5, y: 5, width: 1, height: 2 },
        { width: 50, height: 50 },
        10,
      ),
    ).toEqual({
      x: 5,
      y: 5,
      width: 10,
      height: 10,
    });
  });

  it('converts PDF-space rectangles to viewport-space by scale', () => {
    expect(toViewportRect({ x: 12, y: 20, width: 40, height: 30 }, 1.5)).toEqual({
      x: 18,
      y: 30,
      width: 60,
      height: 45,
    });
    expect(toViewportRect({ x: 12, y: 20, width: 40, height: 30 }, 0)).toEqual({
      x: 0,
      y: 0,
      width: 0,
      height: 0,
    });
  });
});
