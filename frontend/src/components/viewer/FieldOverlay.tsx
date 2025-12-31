import { type PointerEvent as ReactPointerEvent, useEffect, useRef } from 'react';
import type { FieldRect, PdfField, PageSize } from '../../types';
import { fieldConfidenceTierForField, nameConfidenceTierForField } from '../../utils/confidence';
import { clampRectToPage, toViewportRect } from '../../utils/coords';

type DragMode = 'move' | 'resize';

type DragState = {
  fieldId: string;
  mode: DragMode;
  startX: number;
  startY: number;
  startRect: FieldRect;
};

type FieldOverlayProps = {
  fields: PdfField[];
  pageSize: PageSize;
  scale: number;
  showFieldNames: boolean;
  selectedFieldId: string | null;
  onSelectField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
};

export function FieldOverlay({
  fields,
  pageSize,
  scale,
  showFieldNames,
  selectedFieldId,
  onSelectField,
  onUpdateField,
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

      const scaleValue = scaleRef.current || 1;
      const dx = (event.clientX - dragState.startX) / scaleValue;
      const dy = (event.clientY - dragState.startY) / scaleValue;

      const base = dragState.startRect;
      let nextRect: FieldRect = base;

      if (dragState.mode === 'move') {
        nextRect = {
          ...base,
          x: base.x + dx,
          y: base.y + dy,
        };
      } else {
        nextRect = {
          ...base,
          width: Math.max(6, base.width + dx),
          height: Math.max(6, base.height + dy),
        };
      }

      const clamped = clampRectToPage(nextRect, pageRef.current);
      onUpdateField(dragState.fieldId, { rect: clamped });
    };

    const handlePointerUp = () => {
      dragStateRef.current = null;
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [onUpdateField]);

  const startDrag = (
    event: ReactPointerEvent<HTMLElement>,
    field: PdfField,
    mode: DragMode,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    dragStateRef.current = {
      fieldId: field.id,
      mode,
      startX: event.clientX,
      startY: event.clientY,
      startRect: field.rect,
    };
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
              className="field-handle"
              onPointerDown={(event) => startDrag(event, field, 'resize')}
            />
          </div>
        );
      })}
    </div>
  );
}
