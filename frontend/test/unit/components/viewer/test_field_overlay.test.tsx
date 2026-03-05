import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { PdfField } from '../../../../src/types';
import { FieldOverlay } from '../../../../src/components/viewer/FieldOverlay';

function makeField(overrides: Partial<PdfField> & Pick<PdfField, 'id' | 'name' | 'type'>): PdfField {
  return {
    id: overrides.id,
    name: overrides.name,
    type: overrides.type,
    page: 1,
    rect: { x: 10, y: 10, width: 30, height: 20 },
    ...overrides,
  };
}

function pointerMove(clientX: number, clientY: number, pointerId = 1, shiftKey = false) {
  window.dispatchEvent(new PointerEvent('pointermove', { clientX, clientY, pointerId, shiftKey }));
}

function pointerUp(pointerId = 1) {
  window.dispatchEvent(new PointerEvent('pointerup', { pointerId }));
}

describe('FieldOverlay', () => {
  beforeEach(() => {
    if (typeof PointerEvent === 'undefined') {
      (globalThis as any).PointerEvent = MouseEvent;
    }
  });

  it('renders labels/confidence classes, selected styling, and selection callback behavior', async () => {
    const user = userEvent.setup();
    const onSelectField = vi.fn();
    const fields = [
      makeField({
        id: 'text-field',
        name: 'Patient Name',
        type: 'text',
        fieldConfidence: 0.6,
        mappingConfidence: 0.7,
      }),
      makeField({
        id: 'checkbox-field',
        name: 'Agree',
        type: 'checkbox',
      }),
    ];
    const { container } = render(
      <FieldOverlay
        fields={fields}
        pageSize={{ width: 200, height: 120 }}
        scale={1}
        moveEnabled={false}
        resizeEnabled={false}
        createEnabled={false}
        activeCreateTool={null}
        showFieldNames
        selectedFieldId="text-field"
        onSelectField={onSelectField}
        onUpdateField={vi.fn()}
        onCreateFieldWithRect={vi.fn()}
        onBeginFieldChange={vi.fn()}
        onCommitFieldChange={vi.fn()}
      />,
    );

    const selectedBox = container.querySelector('[data-field-id="text-field"]') as HTMLDivElement;
    expect(selectedBox.className).toContain('field-box--text');
    expect(selectedBox.className).toContain('field-box--conf-low');
    expect(selectedBox.className).toContain('field-box--active');

    const label = selectedBox.querySelector('.field-label') as HTMLSpanElement;
    expect(label.textContent).toBe('Patient Name');
    expect(label.className).toContain('field-label--conf-medium');

    const checkboxBox = container.querySelector('[data-field-id="checkbox-field"]') as HTMLDivElement;
    expect(checkboxBox.querySelector('.field-label')).toBeNull();

    await user.pointer({
      target: selectedBox,
      keys: '[MouseLeft]',
      coords: { x: 20, y: 20 },
    });
    expect(onSelectField).toHaveBeenCalledWith('text-field');
  });

  it('handles move drag with page-bound clamping and begin/commit callbacks', () => {
    const onUpdateField = vi.fn();
    const onBeginFieldChange = vi.fn();
    const onCommitFieldChange = vi.fn();
    const onSelectField = vi.fn();
    const field = makeField({
      id: 'move-field',
      name: 'move-field',
      type: 'text',
      rect: { x: 10, y: 10, width: 30, height: 20 },
    });
    const { container } = render(
      <FieldOverlay
        fields={[field]}
        pageSize={{ width: 100, height: 80 }}
        scale={1}
        moveEnabled
        resizeEnabled
        createEnabled={false}
        activeCreateTool={null}
        showFieldNames={false}
        selectedFieldId={null}
        onSelectField={onSelectField}
        onUpdateField={onUpdateField}
        onCreateFieldWithRect={vi.fn()}
        onBeginFieldChange={onBeginFieldChange}
        onCommitFieldChange={onCommitFieldChange}
      />,
    );

    const box = container.querySelector('[data-field-id="move-field"]') as HTMLDivElement;
    fireEvent.pointerDown(box, { clientX: 20, clientY: 20, pointerId: 1 });
    pointerMove(220, 220, 1);
    pointerUp(1);

    expect(onBeginFieldChange).toHaveBeenCalledTimes(1);
    expect(onSelectField).toHaveBeenCalledWith('move-field');
    const lastUpdate = onUpdateField.mock.calls.slice(-1)[0];
    expect(lastUpdate).toEqual([
      'move-field',
      {
        rect: { x: 70, y: 60, width: 30, height: 20 },
      },
    ]);
    expect(onCommitFieldChange).toHaveBeenCalledTimes(1);
  });

  it('updates geometry for each resize handle and enforces minimum size', () => {
    const testCases: Array<{
      handleClass: string;
      moveTo: { x: number; y: number };
      expected: { x: number; y: number; width: number; height: number };
    }> = [
      {
        handleClass: '.field-handle--left',
        moveTo: { x: 120, y: 20 },
        expected: { x: 28, y: 10, width: 12, height: 20 },
      },
      {
        handleClass: '.field-handle--right',
        moveTo: { x: 70, y: 20 },
        expected: { x: 10, y: 10, width: 80, height: 20 },
      },
      {
        handleClass: '.field-handle--top',
        moveTo: { x: 20, y: 100 },
        expected: { x: 10, y: 18, width: 30, height: 12 },
      },
      {
        handleClass: '.field-handle--bottom',
        moveTo: { x: 20, y: 80 },
        expected: { x: 10, y: 10, width: 30, height: 70 },
      },
      {
        handleClass: '.field-handle--br',
        moveTo: { x: 80, y: 30 },
        expected: { x: 10, y: 10, width: 90, height: 30 },
      },
    ];

    for (const testCase of testCases) {
      const onUpdateField = vi.fn();
      const onCommitFieldChange = vi.fn();
      const { container, unmount } = render(
        <FieldOverlay
          fields={[
            makeField({
              id: 'resize-field',
              name: 'resize-field',
              type: 'text',
              rect: { x: 10, y: 10, width: 30, height: 20 },
            }),
          ]}
          pageSize={{ width: 100, height: 80 }}
          scale={1}
          moveEnabled
          resizeEnabled
          createEnabled={false}
          activeCreateTool={null}
          showFieldNames={false}
          selectedFieldId={null}
          onSelectField={vi.fn()}
          onUpdateField={onUpdateField}
          onCreateFieldWithRect={vi.fn()}
          onBeginFieldChange={vi.fn()}
          onCommitFieldChange={onCommitFieldChange}
        />,
      );

      const handle = container.querySelector(testCase.handleClass) as HTMLSpanElement;
      fireEvent.pointerDown(handle, { clientX: 20, clientY: 20, pointerId: 1 });
      pointerMove(testCase.moveTo.x, testCase.moveTo.y, 1);
      pointerUp(1);

      const lastUpdate = onUpdateField.mock.calls.slice(-1)[0];
      expect(lastUpdate).toEqual(['resize-field', { rect: testCase.expected }]);
      expect(onCommitFieldChange).toHaveBeenCalledTimes(1);
      unmount();
    }
  });
});
