import type { FieldRect, PageSize, PdfField } from '../types';
import { clampRectToPage } from './coords';

export type QuickRadioSelectionMode = 'precise' | 'touch';

const CREATE_CLICK_THRESHOLD = 2;
const PRECISE_SELECTION_MIN_COVERAGE = 0.9;

type PdfPoint = {
  x: number;
  y: number;
};

export function toQuickRadioSelectionRect(
  start: PdfPoint,
  current: PdfPoint,
  page: PageSize,
): FieldRect | null {
  const width = Math.abs(current.x - start.x);
  const height = Math.abs(current.y - start.y);
  if (width <= CREATE_CLICK_THRESHOLD && height <= CREATE_CLICK_THRESHOLD) {
    return null;
  }
  return clampRectToPage(
    {
      x: Math.min(start.x, current.x),
      y: Math.min(start.y, current.y),
      width,
      height,
    },
    page,
    0,
  );
}

export function rectContainsPoint(rect: FieldRect, point: PdfPoint): boolean {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

function rectsOverlap(left: FieldRect, right: FieldRect): boolean {
  const leftRight = left.x + left.width;
  const leftBottom = left.y + left.height;
  const rightRight = right.x + right.width;
  const rightBottom = right.y + right.height;
  return left.x < rightRight && leftRight > right.x && left.y < rightBottom && leftBottom > right.y;
}

function intersectionArea(left: FieldRect, right: FieldRect): number {
  if (!rectsOverlap(left, right)) {
    return 0;
  }
  const overlapWidth = Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x);
  const overlapHeight = Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y);
  return Math.max(0, overlapWidth) * Math.max(0, overlapHeight);
}

function selectionCoverage(target: FieldRect, selectionRect: FieldRect): number {
  const targetArea = Math.max(target.width * target.height, 1);
  return intersectionArea(target, selectionRect) / targetArea;
}

export function fieldMatchesQuickRadioSelection(
  fieldRect: FieldRect,
  selectionRect: FieldRect | null,
  point: PdfPoint,
  mode: QuickRadioSelectionMode,
): boolean {
  if (!selectionRect) {
    return rectContainsPoint(fieldRect, point);
  }
  if (mode === 'touch') {
    return rectsOverlap(fieldRect, selectionRect);
  }
  return selectionCoverage(fieldRect, selectionRect) >= PRECISE_SELECTION_MIN_COVERAGE;
}

export function collectQuickRadioSelection(
  fields: PdfField[],
  selectionRect: FieldRect | null,
  point: PdfPoint,
  mode: QuickRadioSelectionMode,
): string[] {
  return fields
    .filter((field) => field.type === 'checkbox')
    .filter((field) => fieldMatchesQuickRadioSelection(field.rect, selectionRect, point, mode))
    .map((field) => field.id);
}
