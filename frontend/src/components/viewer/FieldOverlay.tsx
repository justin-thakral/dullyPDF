/**
 * Overlay layer for draggable/resizable field boxes.
 */
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react';
import type { FieldRect, FieldType, PdfField, PageSize } from '../../types';
import { fieldConfidenceTierForField, nameConfidenceTierForField } from '../../utils/confidence';
import { clamp, clampRectToPage, toViewportRect } from '../../utils/coords';
import { getDefaultFieldRect, getMinFieldSize } from '../../utils/fields';

const SMALL_FIELD_THRESHOLD_PDF = 24;
const CREATE_CLICK_THRESHOLD = 2;

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
  fieldType: FieldType;
  mode: DragMode;
  startX: number;
  startY: number;
  startRect: FieldRect;
  pointerId: number;
  pointerTarget: HTMLElement | null;
};

type CreateState = {
  pointerId: number;
  pointerTarget: HTMLElement | null;
  start: { x: number; y: number };
  current: { x: number; y: number };
};

type DragPreviewState = {
  fieldId: string;
  rect: FieldRect;
} | null;

type FieldOverlayProps = {
  fields: PdfField[];
  pageSize: PageSize;
  scale: number;
  moveEnabled: boolean;
  resizeEnabled: boolean;
  createEnabled: boolean;
  activeCreateTool: FieldType | null;
  showFieldNames: boolean;
  selectedFieldId: string | null;
  onSelectField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onCreateFieldWithRect: (type: FieldType, rect: FieldRect) => void;
  onBeginFieldChange: () => void;
  onCommitFieldChange: () => void;
};

function resizeCornerFreeform(
  base: FieldRect,
  mode: CornerResizeMode,
  dx: number,
  dy: number,
  pageSize: PageSize,
  minSize: number,
): FieldRect {
  const left = base.x;
  const top = base.y;
  const right = base.x + base.width;
  const bottom = base.y + base.height;

  if (mode === 'resize-br') {
    const maxWidth = Math.max(minSize, pageSize.width - left);
    const maxHeight = Math.max(minSize, pageSize.height - top);
    return {
      x: left,
      y: top,
      width: clamp(base.width + dx, minSize, maxWidth),
      height: clamp(base.height + dy, minSize, maxHeight),
    };
  }

  if (mode === 'resize-tr') {
    const maxWidth = Math.max(minSize, pageSize.width - left);
    const nextY = clamp(top + dy, 0, bottom - minSize);
    return {
      x: left,
      y: nextY,
      width: clamp(base.width + dx, minSize, maxWidth),
      height: bottom - nextY,
    };
  }

  if (mode === 'resize-bl') {
    const maxHeight = Math.max(minSize, pageSize.height - top);
    const nextX = clamp(left + dx, 0, right - minSize);
    return {
      x: nextX,
      y: top,
      width: right - nextX,
      height: clamp(base.height + dy, minSize, maxHeight),
    };
  }

  const nextX = clamp(left + dx, 0, right - minSize);
  const nextY = clamp(top + dy, 0, bottom - minSize);
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
  minSize: number,
): FieldRect {
  const safeWidth = Math.max(base.width, minSize);
  const safeHeight = Math.max(base.height, minSize);
  const left = base.x;
  const top = base.y;
  const right = left + safeWidth;
  const bottom = top + safeHeight;

  const sizeDx = (mode === 'resize-br' || mode === 'resize-tr' ? 1 : -1) * dx;
  const sizeDy = (mode === 'resize-br' || mode === 'resize-bl' ? 1 : -1) * dy;

  // Project pointer movement onto the aspect-ratio diagonal (O(1) each pointer move) to avoid axis-flip jumps.
  const diagonalDot = (safeWidth * safeWidth) + (safeHeight * safeHeight);
  const projected = ((sizeDx * safeWidth) + (sizeDy * safeHeight)) / diagonalDot;
  const minScale = Math.max(minSize / safeWidth, minSize / safeHeight);

  const maxWidth = mode === 'resize-br' || mode === 'resize-tr'
    ? pageSize.width - left
    : right;
  const maxHeight = mode === 'resize-br' || mode === 'resize-bl'
    ? pageSize.height - top
    : bottom;
  const maxScale = Math.min(
    Math.max(minSize, maxWidth) / safeWidth,
    Math.max(minSize, maxHeight) / safeHeight,
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

function toDragRect(
  start: { x: number; y: number },
  current: { x: number; y: number },
  type: FieldType,
  page: PageSize,
): FieldRect {
  const defaultRect = getDefaultFieldRect(type);
  const minSize = getMinFieldSize(type);
  const dx = current.x - start.x;
  const dy = current.y - start.y;
  const width = Math.abs(dx);
  const height = Math.abs(dy);

  if (width <= CREATE_CLICK_THRESHOLD && height <= CREATE_CLICK_THRESHOLD) {
    return clampRectToPage(
      {
        x: start.x - defaultRect.width / 2,
        y: start.y - defaultRect.height / 2,
        width: defaultRect.width,
        height: defaultRect.height,
      },
      page,
      minSize,
    );
  }

  if (type === 'checkbox') {
    const side = Math.max(width, height, minSize);
    return clampRectToPage(
      {
        x: dx >= 0 ? start.x : start.x - side,
        y: dy >= 0 ? start.y : start.y - side,
        width: side,
        height: side,
      },
      page,
      minSize,
    );
  }

  return clampRectToPage(
    {
      x: Math.min(start.x, current.x),
      y: Math.min(start.y, current.y),
      width: Math.max(width, minSize),
      height: Math.max(height, minSize),
    },
    page,
    minSize,
  );
}

function resolveFieldLabelMetrics(rect: FieldRect) {
  const maxWidth = Math.max(12, rect.width * 0.75);
  const maxHeight = Math.max(10, rect.height * 0.75);
  return {
    maxWidth,
    maxHeight,
    fontSize: Math.max(7, Math.min(13, maxHeight * 0.44, maxWidth * 0.14)),
  };
}

/**
 * Render editable field boxes and pointer-driven geometry updates.
 */
export function FieldOverlay({
  fields,
  pageSize,
  scale,
  moveEnabled,
  resizeEnabled,
  createEnabled,
  activeCreateTool,
  showFieldNames,
  selectedFieldId,
  onSelectField,
  onUpdateField,
  onCreateFieldWithRect,
  onBeginFieldChange,
  onCommitFieldChange,
}: FieldOverlayProps) {
  // Drag state is kept in a ref so pointer events can mutate geometry without rerendering mid-drag.
  const dragStateRef = useRef<DragState | null>(null);
  const createStateRef = useRef<CreateState | null>(null);
  const layerRef = useRef<HTMLDivElement | null>(null);
  // Store latest scale and page size to avoid stale closures in the global pointer listeners.
  const scaleRef = useRef(scale);
  const pageRef = useRef(pageSize);
  const createToolRef = useRef<FieldType | null>(activeCreateTool);
  const [draftCreateRect, setDraftCreateRect] = useState<FieldRect | null>(null);
  const [dragPreview, setDragPreview] = useState<DragPreviewState>(null);
  const dragPreviewRef = useRef<DragPreviewState>(null);

  useEffect(() => {
    scaleRef.current = scale;
  }, [scale]);

  useEffect(() => {
    pageRef.current = pageSize;
  }, [pageSize]);

  useEffect(() => {
    createToolRef.current = activeCreateTool;
    if (!activeCreateTool) {
      createStateRef.current = null;
      setDraftCreateRect(null);
    }
  }, [activeCreateTool]);

  const clientPointToPdfPoint = (clientX: number, clientY: number) => {
    const layer = layerRef.current;
    if (!layer) return null;
    const bounds = layer.getBoundingClientRect();
    const scaleValue = scaleRef.current || 1;
    const page = pageRef.current;
    return {
      x: clamp((clientX - bounds.left) / scaleValue, 0, page.width),
      y: clamp((clientY - bounds.top) / scaleValue, 0, page.height),
    };
  };

  const clearDragPreview = () => {
    dragPreviewRef.current = null;
    setDragPreview(null);
  };

  const updateDragPreview = (fieldId: string, rect: FieldRect) => {
    const nextPreview = { fieldId, rect };
    dragPreviewRef.current = nextPreview;
    setDragPreview(nextPreview);
  };

  const rectsEqual = (left: FieldRect, right: FieldRect) =>
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height;

  useEffect(() => {
    // Global listeners keep drag and resize responsive even if the cursor leaves the box.
    const handlePointerMove = (event: PointerEvent) => {
      const createState = createStateRef.current;
      if (createState && event.pointerId === createState.pointerId) {
        const type = createToolRef.current;
        const point = clientPointToPdfPoint(event.clientX, event.clientY);
        if (!type || !point) return;
        createState.current = point;
        const nextDraft = toDragRect(createState.start, point, type, pageRef.current);
        setDraftCreateRect(nextDraft);
        return;
      }

      const dragState = dragStateRef.current;
      if (!dragState) return;
      if (event.pointerId !== dragState.pointerId) return;

      const scaleValue = scaleRef.current || 1;
      const dx = (event.clientX - dragState.startX) / scaleValue;
      const dy = (event.clientY - dragState.startY) / scaleValue;

      const page = pageRef.current;
      const minSize = getMinFieldSize(dragState.fieldType);
      const base = clampRectToPage(dragState.startRect, page, minSize);
      let nextRect: FieldRect = base;

      if (dragState.mode === 'move') {
        nextRect = {
          ...base,
          x: base.x + dx,
          y: base.y + dy,
        };
        nextRect = clampRectToPage(nextRect, page, minSize);
      } else {
        const rightEdge = base.x + base.width;
        const bottomEdge = base.y + base.height;

        if (dragState.mode === 'resize-left') {
          const nextX = clamp(base.x + dx, 0, rightEdge - minSize);
          nextRect = {
            x: nextX,
            y: base.y,
            width: rightEdge - nextX,
            height: base.height,
          };
        } else if (dragState.mode === 'resize-right') {
          const maxWidth = Math.max(minSize, page.width - base.x);
          nextRect = {
            ...base,
            width: clamp(base.width + dx, minSize, maxWidth),
          };
        } else if (dragState.mode === 'resize-top') {
          const nextY = clamp(base.y + dy, 0, bottomEdge - minSize);
          nextRect = {
            x: base.x,
            y: nextY,
            width: base.width,
            height: bottomEdge - nextY,
          };
        } else if (dragState.mode === 'resize-bottom') {
          const maxHeight = Math.max(minSize, page.height - base.y);
          nextRect = {
            ...base,
            height: clamp(base.height + dy, minSize, maxHeight),
          };
        } else {
          const shouldLockAspect = event.shiftKey;
          nextRect = shouldLockAspect
            ? resizeCornerWithAspectRatio(base, dragState.mode, dx, dy, page, minSize)
            : resizeCornerFreeform(base, dragState.mode, dx, dy, page, minSize);
        }

        if (dragState.fieldType === 'checkbox') {
          const side = Math.max(nextRect.width, nextRect.height, minSize);
          nextRect = clampRectToPage(
            {
              x: nextRect.x,
              y: nextRect.y,
              width: side,
              height: side,
            },
            page,
            minSize,
          );
        }
      }

      updateDragPreview(dragState.fieldId, nextRect);
    };

    const endDrag = (pointerId: number) => {
      const createState = createStateRef.current;
      if (createState && pointerId === createState.pointerId) {
        const type = createToolRef.current;
        if (createState.pointerTarget) {
          try {
            createState.pointerTarget.releasePointerCapture(createState.pointerId);
          } catch {
            // Ignore release errors when capture is already lost.
          }
        }
        if (type) {
          const rect = toDragRect(createState.start, createState.current, type, pageRef.current);
          onCreateFieldWithRect(type, rect);
        }
        createStateRef.current = null;
        setDraftCreateRect(null);
        return;
      }

      const dragState = dragStateRef.current;
      if (!dragState || pointerId !== dragState.pointerId) return;

      if (dragState.pointerTarget) {
        try {
          dragState.pointerTarget.releasePointerCapture(dragState.pointerId);
        } catch {
          // Ignore release errors when capture is already lost.
        }
      }
      const nextRect = dragPreviewRef.current?.fieldId === dragState.fieldId
        ? dragPreviewRef.current.rect
        : dragState.startRect;
      if (!rectsEqual(nextRect, dragState.startRect)) {
        onUpdateField(dragState.fieldId, { rect: nextRect });
      }
      clearDragPreview();
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
      clearDragPreview();
    };
  }, [onCommitFieldChange, onCreateFieldWithRect, onUpdateField]);

  /**
   * Capture initial drag state and signal change start.
   */
  const startDrag = (
    event: ReactPointerEvent<HTMLElement>,
    field: PdfField,
    mode: DragMode,
  ) => {
    if (!moveEnabled) return;
    if (createToolRef.current) return;
    if (mode !== 'move' && !resizeEnabled) return;
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
      fieldType: field.type,
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

  const startCreateDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!createEnabled) return;
    const type = activeCreateTool;
    if (!type) return;
    event.preventDefault();
    event.stopPropagation();
    const pointerTarget = event.currentTarget;
    if (pointerTarget) {
      try {
        pointerTarget.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture can fail in synthetic/multi-pointer scenarios; keep creation functional via window listeners.
      }
    }
    const start = clientPointToPdfPoint(event.clientX, event.clientY);
    if (!start) return;
    createStateRef.current = {
      pointerId: event.pointerId,
      pointerTarget,
      start,
      current: start,
    };
    setDraftCreateRect(toDragRect(start, start, type, pageRef.current));
  };

  return (
    <div
      className="field-layer"
      ref={layerRef}
      style={{
        width: pageSize.width * scale,
        height: pageSize.height * scale,
      }}
    >
      {createEnabled && activeCreateTool ? (
        <div
          className="field-create-surface"
          onPointerDown={startCreateDrag}
          aria-label={`Draw ${activeCreateTool} field`}
        />
      ) : null}
      {draftCreateRect ? (
        <div
          className={`field-create-draft field-create-draft--${activeCreateTool || 'text'}`}
          style={{
            left: draftCreateRect.x * scale,
            top: draftCreateRect.y * scale,
            width: draftCreateRect.width * scale,
            height: draftCreateRect.height * scale,
          }}
        />
      ) : null}
      {fields.map((field) => {
        const previewRect = dragPreview?.fieldId === field.id ? dragPreview.rect : field.rect;
        const rect = toViewportRect(previewRect, scale);
        const selected = field.id === selectedFieldId;
        const isSmallField =
          field.type === 'checkbox' ||
          (previewRect.width <= SMALL_FIELD_THRESHOLD_PDF && previewRect.height <= SMALL_FIELD_THRESHOLD_PDF);
        // Keep labels inside a 75% inset box so names stay visibly subordinate to the field bounds.
        const labelMetrics = resolveFieldLabelMetrics(rect);
        const confidenceTier = fieldConfidenceTierForField(field);
        const nameTier = nameConfidenceTierForField(field);
        const className = [
          'field-box',
          `field-box--${field.type}`,
          `field-box--conf-${confidenceTier}`,
          !moveEnabled ? 'field-box--static' : '',
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
            onPointerDown={(event) => {
              if (moveEnabled) {
                startDrag(event, field, 'move');
              } else {
                event.preventDefault();
                event.stopPropagation();
                onSelectField(field.id);
              }
            }}
          >
            {showLabel ? (
              <span
                className={labelClassName}
                title={field.name}
                style={{
                  ['--field-label-font-size' as string]: `${labelMetrics.fontSize}px`,
                  ['--field-label-max-width' as string]: `${labelMetrics.maxWidth}px`,
                  ['--field-label-max-height' as string]: `${labelMetrics.maxHeight}px`,
                }}
              >
                {field.name}
              </span>
            ) : null}
            {moveEnabled && isSmallField ? (
              <span
                className="field-move-proxy"
                onPointerDown={(event) => startDrag(event, field, 'move')}
                aria-hidden="true"
              />
            ) : null}
            {resizeEnabled ? (
              isSmallField ? (
                <span
                  className="field-handle field-handle--br"
                  onPointerDown={(event) => startDrag(event, field, 'resize-br')}
                />
              ) : (
                <>
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
                </>
              )
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
