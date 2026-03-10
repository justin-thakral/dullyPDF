import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { PdfField } from '../../../../src/types';
import { FieldInspectorPanel } from '../../../../src/components/panels/FieldInspectorPanel';

type FieldInspectorPanelProps = ComponentProps<typeof FieldInspectorPanel>;

const SAMPLE_FIELD: PdfField = {
  id: 'field-1',
  name: 'Full Name',
  type: 'text',
  page: 2,
  rect: {
    x: 14,
    y: 22,
    width: 120,
    height: 30,
  },
};

function createProps(overrides: Partial<FieldInspectorPanelProps> = {}): FieldInspectorPanelProps {
  return {
    fields: [SAMPLE_FIELD],
    selectedFieldId: SAMPLE_FIELD.id,
    activeCreateTool: null,
    arrowKeyMoveEnabled: false,
    arrowKeyMoveStep: 5,
    onUpdateField: vi.fn(),
    onSetFieldType: vi.fn(),
    onUpdateFieldDraft: vi.fn(),
    onDeleteField: vi.fn(),
    onCreateToolChange: vi.fn(),
    onArrowKeyMoveEnabledChange: vi.fn(),
    onArrowKeyMoveStepChange: vi.fn(),
    onBeginFieldChange: vi.fn(),
    onCommitFieldChange: vi.fn(),
    canUndo: true,
    canRedo: true,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    ...overrides,
  };
}

describe('FieldInspectorPanel', () => {
  it('renders empty state when no field is selected', () => {
    render(<FieldInspectorPanel {...createProps({ selectedFieldId: null })} />);

    expect(screen.getByText('No field selected.')).toBeTruthy();
    expect(screen.queryByLabelText('Name')).toBeNull();
  });

  it('updates selected field name/type/page/rect and emits begin/commit callbacks', async () => {
    const user = userEvent.setup();
    const onUpdateField = vi.fn();
    const onSetFieldType = vi.fn();
    const onUpdateFieldDraft = vi.fn();
    const onBeginFieldChange = vi.fn();
    const onCommitFieldChange = vi.fn();

    render(
      <FieldInspectorPanel
        {...createProps({
          onUpdateField,
          onSetFieldType,
          onUpdateFieldDraft,
          onBeginFieldChange,
          onCommitFieldChange,
        })}
      />,
    );

    const nameInput = screen.getByLabelText('Name');
    await user.click(nameInput);
    expect(onBeginFieldChange).toHaveBeenCalledTimes(1);

    await user.type(nameInput, ' X');
    await user.tab();
    expect(onUpdateField).toHaveBeenCalledWith('field-1', { name: 'Full Name X' });
    expect(onCommitFieldChange).toHaveBeenCalledTimes(1);

    await user.selectOptions(screen.getByLabelText('Type'), 'date');
    expect(onSetFieldType).toHaveBeenLastCalledWith('field-1', 'date');

    const pageInput = screen.getByLabelText('Page');
    await user.click(pageInput);
    await user.type(pageInput, '3');
    await user.tab();
    const pageCalls = onUpdateField.mock.calls.filter(
      (call) => typeof (call[1] as Partial<PdfField>).page === 'number',
    );
    expect(pageCalls.length).toBeGreaterThan(0);
    expect(((pageCalls.at(-1)?.[1] as { page: number }).page)).toBeGreaterThanOrEqual(1);

    onUpdateField.mockClear();
    const xInput = screen.getByLabelText('X');
    await user.click(xInput);
    await user.type(xInput, '5');
    await user.tab();
    const rectCalls = onUpdateField.mock.calls.filter(
      (call) => Boolean((call[1] as Partial<PdfField>).rect),
    );
    expect(rectCalls.length).toBeGreaterThan(0);
    const lastRect = (rectCalls.at(-1)?.[1] as { rect: PdfField['rect'] }).rect;
    expect(lastRect.x).toBeGreaterThan(14);
    expect(lastRect.y).toBe(22);
    expect(lastRect.width).toBe(120);
    expect(lastRect.height).toBe(30);
  });

  it('clamps page input to at least 1 and rounds fractional values', () => {
    const onUpdateField = vi.fn();

    render(<FieldInspectorPanel {...createProps({ onUpdateField })} />);

    const pageInput = screen.getByLabelText('Page');

    fireEvent.change(pageInput, { target: { value: '-5' } });
    fireEvent.blur(pageInput);
    fireEvent.change(pageInput, { target: { value: '1.7' } });
    fireEvent.blur(pageInput);

    const pageCalls = onUpdateField.mock.calls
      .filter((call) => typeof (call[1] as Partial<PdfField>).page === 'number')
      .map((call) => (call[1] as { page: number }).page);

    expect(pageCalls.length).toBeGreaterThan(0);
    for (const value of pageCalls) {
      expect(value).toBeGreaterThanOrEqual(1);
      expect(Number.isInteger(value)).toBe(true);
    }
  });

  it('enforces minimum width and height when resizing', async () => {
    const onUpdateField = vi.fn();

    render(<FieldInspectorPanel {...createProps({ onUpdateField })} />);

    const widthInput = screen.getByLabelText('Width');
    fireEvent.change(widthInput, { target: { value: '-5' } });
    fireEvent.blur(widthInput);
    expect(onUpdateField).toHaveBeenLastCalledWith('field-1', {
      rect: { x: 14, y: 22, width: 12, height: 30 },
    });

    onUpdateField.mockClear();
    const heightInput = screen.getByLabelText('Height');
    fireEvent.change(heightInput, { target: { value: '-2' } });
    fireEvent.blur(heightInput);
    expect(onUpdateField).toHaveBeenLastCalledWith('field-1', {
      rect: { x: 14, y: 22, width: 120, height: 12 },
    });
  });

  it('wires create/delete callbacks and undo/redo disabled states', async () => {
    const user = userEvent.setup();
    const onCreateToolChange = vi.fn();
    const onDeleteField = vi.fn();
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    const { rerender } = render(
      <FieldInspectorPanel
        {...createProps({
          onCreateToolChange,
          onDeleteField,
          onUndo,
          onRedo,
          canUndo: false,
          canRedo: false,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Delete field' }));
    expect(onDeleteField).toHaveBeenCalledWith('field-1');

    await user.click(screen.getByRole('button', { name: 'Text' }));
    await user.click(screen.getByRole('button', { name: 'Date' }));
    await user.click(screen.getByRole('button', { name: 'Signature' }));
    await user.click(screen.getByRole('button', { name: 'Checkbox' }));
    await user.click(screen.getByRole('button', { name: 'Off' }));

    expect(onCreateToolChange).toHaveBeenCalledTimes(5);
    expect(onCreateToolChange).toHaveBeenNthCalledWith(1, 'text');
    expect(onCreateToolChange).toHaveBeenNthCalledWith(2, 'date');
    expect(onCreateToolChange).toHaveBeenNthCalledWith(3, 'signature');
    expect(onCreateToolChange).toHaveBeenNthCalledWith(4, 'checkbox');
    expect(onCreateToolChange).toHaveBeenNthCalledWith(5, null);

    const undoButtonBefore = screen.getByRole('button', { name: 'Undo' }) as HTMLButtonElement;
    const redoButtonBefore = screen.getByRole('button', { name: 'Redo' }) as HTMLButtonElement;
    expect(undoButtonBefore.disabled).toBe(true);
    expect(redoButtonBefore.disabled).toBe(true);

    rerender(
      <FieldInspectorPanel
        {...createProps({
          onCreateToolChange,
          onDeleteField,
          onUndo,
          onRedo,
          canUndo: true,
          canRedo: true,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await user.click(screen.getByRole('button', { name: 'Redo' }));

    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onRedo).toHaveBeenCalledTimes(1);
  });

  it('updates keyboard move preferences from the create field section', async () => {
    const user = userEvent.setup();
    const onArrowKeyMoveEnabledChange = vi.fn();
    const onArrowKeyMoveStepChange = vi.fn();

    render(
      <FieldInspectorPanel
        {...createProps({
          onArrowKeyMoveEnabledChange,
          onArrowKeyMoveStepChange,
        })}
      />,
    );

    await user.click(screen.getByRole('checkbox', { name: 'Arrow keys' }));
    expect(onArrowKeyMoveEnabledChange).toHaveBeenCalledWith(true);

    const stepInput = screen.getByLabelText('Step (pt)');
    await user.clear(stepInput);
    await user.type(stepInput, '7');
    await user.tab();
    expect(onArrowKeyMoveStepChange).toHaveBeenCalledWith(7);
  });
});
