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
    currentPage: 2,
    onUpdateField: vi.fn(),
    onUpdateFieldDraft: vi.fn(),
    onDeleteField: vi.fn(),
    onCreateField: vi.fn(),
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
    const onUpdateFieldDraft = vi.fn();
    const onBeginFieldChange = vi.fn();
    const onCommitFieldChange = vi.fn();

    render(
      <FieldInspectorPanel
        {...createProps({
          onUpdateField,
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
    const lastDraftCall = onUpdateFieldDraft.mock.lastCall;
    expect(lastDraftCall?.[0]).toBe('field-1');
    expect((lastDraftCall?.[1] as { name: string }).name).toMatch(/^Full Name.*X$/);

    await user.tab();
    expect(onCommitFieldChange).toHaveBeenCalledTimes(1);

    await user.selectOptions(screen.getByLabelText('Type'), 'date');
    expect(onUpdateField).toHaveBeenLastCalledWith('field-1', { type: 'date' });

    const pageInput = screen.getByLabelText('Page');
    await user.click(pageInput);
    await user.type(pageInput, '3');
    const pageCalls = onUpdateField.mock.calls.filter(
      (call) => typeof (call[1] as Partial<PdfField>).page === 'number',
    );
    expect(pageCalls.length).toBeGreaterThan(0);
    expect(((pageCalls.at(-1)?.[1] as { page: number }).page)).toBeGreaterThanOrEqual(1);

    onUpdateField.mockClear();
    const xInput = screen.getByLabelText('X');
    await user.click(xInput);
    await user.type(xInput, '5');
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
    fireEvent.change(pageInput, { target: { value: '1.7' } });

    const pageCalls = onUpdateField.mock.calls
      .filter((call) => typeof (call[1] as Partial<PdfField>).page === 'number')
      .map((call) => (call[1] as { page: number }).page);

    expect(pageCalls).toHaveLength(2);
    for (const value of pageCalls) {
      expect(value).toBeGreaterThanOrEqual(1);
      expect(Number.isInteger(value)).toBe(true);
    }
  });

  it('enforces minimum width and height when resizing', async () => {
    const user = userEvent.setup();
    const onUpdateField = vi.fn();

    render(<FieldInspectorPanel {...createProps({ onUpdateField })} />);

    const widthInput = screen.getByLabelText('Width');
    await user.click(widthInput);
    await user.type(widthInput, '-');
    expect(onUpdateField).toHaveBeenLastCalledWith('field-1', {
      rect: { x: 14, y: 22, width: 6, height: 30 },
    });

    onUpdateField.mockClear();
    const heightInput = screen.getByLabelText('Height');
    await user.click(heightInput);
    await user.type(heightInput, '-');
    expect(onUpdateField).toHaveBeenLastCalledWith('field-1', {
      rect: { x: 14, y: 22, width: 120, height: 6 },
    });
  });

  it('wires create/delete callbacks and undo/redo disabled states', async () => {
    const user = userEvent.setup();
    const onCreateField = vi.fn();
    const onDeleteField = vi.fn();
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    const { rerender } = render(
      <FieldInspectorPanel
        {...createProps({
          onCreateField,
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

    await user.click(screen.getByRole('button', { name: 'Add Text' }));
    await user.click(screen.getByRole('button', { name: 'Add Date' }));
    await user.click(screen.getByRole('button', { name: 'Add Signature' }));
    await user.click(screen.getByRole('button', { name: 'Add Checkbox' }));

    expect(onCreateField).toHaveBeenCalledTimes(4);
    expect(onCreateField).toHaveBeenNthCalledWith(1, 'text');
    expect(onCreateField).toHaveBeenNthCalledWith(2, 'date');
    expect(onCreateField).toHaveBeenNthCalledWith(3, 'signature');
    expect(onCreateField).toHaveBeenNthCalledWith(4, 'checkbox');

    const undoButtonBefore = screen.getByRole('button', { name: 'Undo' }) as HTMLButtonElement;
    const redoButtonBefore = screen.getByRole('button', { name: 'Redo' }) as HTMLButtonElement;
    expect(undoButtonBefore.disabled).toBe(true);
    expect(redoButtonBefore.disabled).toBe(true);

    rerender(
      <FieldInspectorPanel
        {...createProps({
          onCreateField,
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
});
