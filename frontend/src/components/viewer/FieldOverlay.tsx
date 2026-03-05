/**
 * Overlay layer for draggable/resizable field boxes.
 */
import { type PointerEvent as ReactPointerEvent, useEffect, useRef } from 'react';
import type { FieldRect, PdfField, PageSize } from '../../types';
import { fieldConfidenceTierForField, nameConfidenceTierForField } from '../../utils/confidence';
import { clamp, clampRectToPage, toViewportRect } from '../../utils/coords';

const MIN_FIELD_SIZE = 6;

type CornerResizeMode = 'resize-tl' | 'resize-tr' | 'resize-bl' | 'resize-br';
type DragMode =
  | 'move'
  | CornerResizeMode
  | 'resize-left'
  | 'resize-right'
  | 'resize-top'
  | 'resize-bottom';

type DragState = {
  fieldId: string;
  mode: DragMode;
  startX: number;
  startY: number;
  startRect: FieldRect;
  pointerId: number;
  pointerTarget: HTMLElement | null;
};

type FieldOverlayProps = {
  fields: PdfField[];
  pageSize: PageSize;
  scale: number;
  showFieldNames: boolean;
  selectedFieldId: string | null;
  onSelectField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onBeginFieldChange: () => void;
  onCommitFieldChange: () => void;
};

function isCornerResizeMode(mode: DragMode): mode is CornerResizeMode {
  return mode === 'resize-tl' || mode === 'resize-tr' || mode === 'resize-bl' || mode === 'resize-br';
}

function resizeCornerFreeform(
  base: FieldRect,
  mode: CornerResizeMode,
  dx: number,
  dy: number,
  pageSize: PageSize,
): FieldRect {
  const left = base.x;
  const top = base.y;
  const right = base.x + base.width;
  const bottom = base.y + base.height;

  if (mode === 'resize-br') {
    const maxWidth = Math.max(MIN_FIELD_SIZE, pageSize.width - left);
    const maxHeight = Math.max(MIN_FIELD_SIZE, pageSize.height - top);
    return {
      x: left,
      y: top,
      width: clamp(base.width + dx, MIN_FIELD_SIZE, maxWidth),
      height: clamp(base.height + dy, MIN_FIELD_SIZE, maxHeight),
    };
  }

  if (mode === 'resize-tr') {
    const maxWidth = Math.max(MIN_FIELD_SIZE, pageSize.width - left);
    const nextY = clamp(top + dy, 0, bottom - MIN_FIELD_SIZE);
    return {
      x: left,
      y: nextY,
      width: clamp(base.width + dx, MIN_FIELD_SIZE, maxWidth),
      height: bottom - nextY,
    };
  }

  if (mode === 'resize-bl') {
    const maxHeight = Math.max(MIN_FIELD_SIZE, pageSize.height - top);
    const nextX = clamp(left + dx, 0, right - MIN_FIELD_SIZE);
    return {
      x: nextX,
      y: top,
      width: right - nextX,
      height: clamp(base.height + dy, MIN_FIELD_SIZE, maxHeight),
    };
  }

  const nextX = clamp(left + dx, 0, right - MIN_FIELD_SIZE);
  const nextY = clamp(top + dy, 0, bottom - MIN_FIELD_SIZE);
  return {
    x: nextX,
    y: nextY,
    width: right - nextX,
    height: bottom - nextY,
  };
}

function resizeCornerWithAspectRatio(
  base: FieldRect,
  mode: CornerResizeMode,
  dx: number,
  dy: number,
  pageSize: PageSize,
): FieldRect {
  const safeWidth = Math.max(base.width, MIN_FIELD_SIZE);
  const safeHeight = Math.max(base.height, MIN_FIELD_SIZE);
  const left = base.x;
  const top = base.y;
  const right = left + safeWidth;
  const bottom = top + safeHeight;

  const sizeDx = (mode === 'resize-br' || mode === 'resize-tr' ? 1 : -1) * dx;
  const sizeDy = (mode === 'resize-br' || mode === 'resize-bl' ? 1 : -1) * dy;

  // Project pointer movement onto the aspect-ratio diagonal (O(1) each pointer move) to avoid axis-flip jumps.
  const diagonalDot = (safeWidth * safeWidth) + (safeHeight * safeHeight);
  const projected = ((sizeDx * safeWidth) + (sizeDy * safeHeight)) / diagonalDot;
  const minScale = Math.max(MIN_FIELD_SIZE / safeWidth, MIN_FIELD_SIZE / safeHeight);

  const maxWidth = mode === 'resize-br' || mode === 'resize-tr'
    ? pageSize.width - left
    : right;
  const maxHeight = mode === 'resize-br' || mode === 'resize-bl'
    ? pageSize.height - top
    : bottom;
  const maxScale = Math.min(
    Math.max(MIN_FIELD_SIZE, maxWidth) / safeWidth,
    Math.max(MIN_FIELD_SIZE, maxHeight) / safeHeight,
  );
  const scale = clamp(1 + projected, minScale, Math.max(minScale, maxScale));

  const width = safeWidth * scale;
  const height = safeHeight * scale;

  if (mode === 'resize-br') {
    return { x: left, y: top, width, height };
  }
  if (mode === 'resize-tr') {
    return { x: left, y: bottom - height, width, height };
  }
  if (mode === 'resize-bl') {
    return { x: right - width, y: top, width, height };
  }
  return { x: right - width, y: bottom - height, width, height };
}

/**
 * Render editable field boxes and pointer-driven geometry updates.
 */
export function FieldOverlay({
  fields,
  pageSize,
  scale,
  showFieldNames,
  selectedFieldId,
  onSelectField,
  onUpdateField,
  onBeginFieldChange,
  onCommitFieldChange,
}: FieldOverlayProps) {
  // Drag state is kept in a ref so pointer events can mutate geometry without rerendering mid-drag.
  const dragStateRef = useRef<DragState | null>(null);
  // Store latest scale and page size to avoid stale closures in the global pointer listeners.
  const scaleRef = useRef(scale);
  const pageRef = useRef(pageSize);

  useEffect(() => {
    scaleRef.current = scale;
  }, [scale]);

  useEffect(() => {
    pageRef.current = pageSize;
  }, [pageSize]);

  useEffect(() => {
    // Global listeners keep drag and resize responsive even if the cursor leaves the box.
    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState) return;
      if (event.pointerId !== dragState.pointerId) return;

      const scaleValue = scaleRef.current || 1;
      const dx = (event.clientX - dragState.startX) / scaleValue;
      const dy = (event.clientY - dragState.startY) / scaleValue;

      const page = pageRef.current;
      const base = clampRectToPage(dragState.startRect, page, MIN_FIELD_SIZE);
      let nextRect: FieldRect = base;

      if (dragState.mode === 'move') {
        nextRect = {
          ...base,
          x: base.x + dx,
          y: base.y + dy,
        };
        nextRect = clampRectToPage(nextRect, page, MIN_FIELD_SIZE);
      } else {
        const rightEdge = base.x + base.width;
        const bottomEdge = base.y + base.height;
        if (dragState.mode === 'resize-left') {
          const nextX = clamp(base.x + dx, 0, rightEdge - MIN_FIELD_SIZE);
          nextRect = {
            x: nextX,
            y: base.y,
            width: rightEdge - nextX,
            height: base.height,
          };
        } else if (dragState.mode === 'resize-right') {
          const maxWidth = Math.max(MIN_FIELD_SIZE, page.width - base.x);
          nextRect = {
            ...base,
            width: clamp(base.width + dx, MIN_FIELD_SIZE, maxWidth),
          };
        } else if (dragState.mode === 'resize-top') {
          const nextY = clamp(base.y + dy, 0, bottomEdge - MIN_FIELD_SIZE);
          nextRect = {
            x: base.x,
            y: nextY,
            width: base.width,
            height: bottomEdge - nextY,
          };
        } else if (dragState.mode === 'resize-bottom') {
          const maxHeight = Math.max(MIN_FIELD_SIZE, page.height - base.y);
          nextRect = {
            ...base,
            height: clamp(base.height + dy, MIN_FIELD_SIZE, maxHeight),
          };
        } else if (isCornerResizeMode(dragState.mode)) {
          const shouldLockAspect = event.shiftKey;
          nextRect = shouldLockAspect
            ? resizeCornerWithAspectRatio(base, dragState.mode, dx, dy, page)
            : resizeCornerFreeform(base, dragState.mode, dx, dy, page);
        }
      }

      onUpdateField(dragState.fieldId, { rect: nextRect });
    };

    const endDrag = (pointerId: number) => {
      const dragState = dragStateRef.current;
      if (!dragState || pointerId !== dragState.pointerId) return;

      if (dragState.pointerTarget) {
        try {
          dragState.pointerTarget.releasePointerCapture(dragState.pointerId);
        } catch {
          // Ignore release errors when capture is already lost.
        }
      }
      onCommitFieldChange();
      dragStateRef.current = null;
    };
    const handlePointerUp = (event: PointerEvent) => endDrag(event.pointerId);
    const handlePointerCancel = (event: PointerEvent) => endDrag(event.pointerId);

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerCancel);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerCancel);
    };
  }, [onCommitFieldChange, onUpdateField]);

  /**
   * Capture initial drag state and signal change start.
   */
  const startDrag = (
    event: ReactPointerEvent<HTMLElement>,
    field: PdfField,
    mode: DragMode,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const pointerTarget = event.currentTarget;
    if (pointerTarget) {
      try {
        pointerTarget.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture can fail in synthetic/multi-pointer scenarios; keep drag functional via window listeners.
      }
    }
    dragStateRef.current = {
      fieldId: field.id,
      mode,
      startX: event.clientX,
      startY: event.clientY,
      startRect: field.rect,
      pointerId: event.pointerId,
      pointerTarget,
    };
    onBeginFieldChange();
    onSelectField(field.id);
  };

  return (
    <div
      className="field-layer"
      style={{
        width: pageSize.width * scale,
        height: pageSize.height * scale,
      }}
    >
      {fields.map((field) => {
        const rect = toViewportRect(field.rect, scale);
        const selected = field.id === selectedFieldId;
        const confidenceTier = fieldConfidenceTierForField(field);
        const nameTier = nameConfidenceTierForField(field);
        const className = [
          'field-box',
          `field-box--${field.type}`,
          `field-box--conf-${confidenceTier}`,
          selected ? 'field-box--active' : '',
        ]
          .filter(Boolean)
          .join(' ');
        const showLabel = showFieldNames && field.type !== 'checkbox';
        const labelClassName = [
          'field-label',
          `field-label--${field.type}`,
          nameTier && nameTier !== 'high' ? `field-label--conf-${nameTier}` : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <div
            key={field.id}
            className={className}
            data-field-id={field.id}
            style={{
              left: rect.x,
              top: rect.y,
              width: rect.width,
              height: rect.height,
            }}
            onPointerDown={(event) => startDrag(event, field, 'move')}
          >
            {showLabel ? (
              <span className={labelClassName} title={field.name}>
                {field.name}
              </span>
            ) : null}
            <span
              className="field-handle field-handle--tl"
              onPointerDown={(event) => startDrag(event, field, 'resize-tl')}
            />
            <span
              className="field-handle field-handle--tr"
              onPointerDown={(event) => startDrag(event, field, 'resize-tr')}
            />
            <span
              className="field-handle field-handle--bl"
              onPointerDown={(event) => startDrag(event, field, 'resize-bl')}
            />
            <span
              className="field-handle field-handle--left"
              onPointerDown={(event) => startDrag(event, field, 'resize-left')}
            />
            <span
              className="field-handle field-handle--top"
              onPointerDown={(event) => startDrag(event, field, 'resize-top')}
            />
            <span
              className="field-handle field-handle--right"
              onPointerDown={(event) => startDrag(event, field, 'resize-right')}
            />
            <span
              className="field-handle field-handle--bottom"
              onPointerDown={(event) => startDrag(event, field, 'resize-bottom')}
            />
            <span
              className="field-handle field-handle--br"
              onPointerDown={(event) => startDrag(event, field, 'resize-br')}
            />
          </div>
        );
      })}
    </div>
  );
}
