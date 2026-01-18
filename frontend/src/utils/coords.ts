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

export function toViewportRect(rect: FieldRect, scale: number): FieldRect {
  return {
    x: rect.x * scale,
    y: rect.y * scale,
    width: rect.width * scale,
    height: rect.height * scale,
  };
}
