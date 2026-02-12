/**
 * Geometry helpers for field positioning.
 */
import type { FieldRect, PageSize } from '../types';

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function clampRectToPage(rect: FieldRect, page: PageSize, minSize = 6): FieldRect {
  const width = clamp(rect.width, minSize, page.width);
  const height = clamp(rect.height, minSize, page.height);
  const x = clamp(rect.x, 0, Math.max(0, page.width - width));
  const y = clamp(rect.y, 0, Math.max(0, page.height - height));
  return { x, y, width, height };
}

/**
 * Coerce rect inputs into a consistent {x,y,width,height} shape.
 */
export function rectToBox(rect: unknown): { x: number; y: number; width: number; height: number } | null {
  if (!rect) return null;
  if (Array.isArray(rect) && rect.length === 4) {
    const [x1, y1, x2, y2] = rect.map((value) => Number(value));
    if ([x1, y1, x2, y2].some((val) => Number.isNaN(val))) return null;
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
  }
  if (typeof rect === 'object') {
    const candidate = rect as { x?: number; y?: number; width?: number; height?: number };
    if (
      typeof candidate.x === 'number' &&
      typeof candidate.y === 'number' &&
      typeof candidate.width === 'number' &&
      typeof candidate.height === 'number'
    ) {
      return {
        x: candidate.x,
        y: candidate.y,
        width: candidate.width,
        height: candidate.height,
      };
    }
  }
  return null;
}

export function toViewportRect(rect: FieldRect, scale: number): FieldRect {
  return {
    x: rect.x * scale,
    y: rect.y * scale,
    width: rect.width * scale,
    height: rect.height * scale,
  };
}
