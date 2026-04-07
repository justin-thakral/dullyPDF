import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { PdfField } from '../../../../src/types';
import { FieldListPanel } from '../../../../src/components/panels/FieldListPanel';

type FieldListPanelProps = ComponentProps<typeof FieldListPanel>;

const SAMPLE_FIELDS: PdfField[] = [
  {
    id: 'f1',
    name: 'Full Name',
    type: 'text',
    page: 1,
    rect: { x: 12, y: 18, width: 120, height: 26 },
    fieldConfidence: 0.9,
    renameConfidence: 0.7,
  },
  {
    id: 'f2',
    name: 'Birth Date',
    type: 'date',
    page: 1,
    rect: { x: 20, y: 58, width: 88, height: 24 },
    fieldConfidence: 0.6,
    mappingConfidence: 0.55,
  },
  {
    id: 'f3',
    name: 'Signature',
    type: 'signature',
    page: 2,
    rect: { x: 24, y: 92, width: 140, height: 30 },
    fieldConfidence: 0.83,
  },
];

function createProps(overrides: Partial<FieldListPanelProps> = {}): FieldListPanelProps {
  return {
    fields: SAMPLE_FIELDS,
    totalFieldCount: SAMPLE_FIELDS.length,
    selectedFieldId: null,
    selectedField: null,
    currentPage: 1,
    pageCount: 3,
    showFields: true,
    showFieldNames: true,
    showFieldInfo: false,
    transformMode: false,
    displayPreset: 'edit',
    onApplyDisplayPreset: vi.fn(),
    onTransformModeChange: vi.fn(),
    onShowFieldsChange: vi.fn(),
    onShowFieldNamesChange: vi.fn(),
    onShowFieldInfoChange: vi.fn(),
    canClearInputs: true,
    onClearInputs: vi.fn(),
    confidenceFilter: { high: true, medium: true, low: true },
    onConfidenceFilterChange: vi.fn(),
    onResetConfidenceFilters: vi.fn(),
    onSelectField: vi.fn(),
    onPageChange: vi.fn(),
    renameInProgress: false,
    ...overrides,
  };
}

describe('FieldListPanel', () => {
  it('shows the renaming hint only while rename is in progress', () => {
    const { rerender } = render(<FieldListPanel {...createProps()} />);

    expect(screen.getByText('Filter, sort, and jump to fields fast.')).toBeTruthy();
    expect(screen.queryByText('(Renaming...) Filter, sort, and jump to fields fast.')).toBeNull();

    rerender(<FieldListPanel {...createProps({ renameInProgress: true })} />);

    expect(screen.getByText('(Renaming...) Filter, sort, and jump to fields fast.')).toBeTruthy();
  });

  it('clamps page navigation and applies disabled states at boundaries', async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    const props = createProps({ onPageChange, currentPage: 1, pageCount: 3 });
    const { rerender } = render(<FieldListPanel {...props} />);

    const previousButton = screen.getByRole('button', { name: 'Previous page' }) as HTMLButtonElement;
    const nextButton = screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement;
    expect(previousButton.disabled).toBe(true);
    expect(nextButton.disabled).toBe(false);

    await user.click(nextButton);
    expect(onPageChange).toHaveBeenCalledWith(2);

    const pageInput = screen.getByLabelText('Page');
    await user.clear(pageInput);
    await user.type(pageInput, '99');
    expect(onPageChange).toHaveBeenCalledWith(3);

    rerender(<FieldListPanel {...props} fields={[]} pageCount={0} />);

    expect((screen.getByRole('button', { name: 'Previous page' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('Page') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText('/ --')).toBeTruthy();
  });

  it('filters by search and type and renders empty-state messages', async () => {
    const user = userEvent.setup();
    const props = createProps({ currentPage: 1, pageCount: 3 });
    const { rerender } = render(<FieldListPanel {...props} />);

    expect(screen.getByRole('button', { name: /Full Name/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Birth Date/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Signature/i })).toBeNull();

    await user.type(screen.getByLabelText('Search'), 'birth');
    expect(screen.getByRole('button', { name: /Birth Date/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Full Name/i })).toBeNull();

    await user.selectOptions(screen.getByLabelText('Filter'), 'text');
    expect(screen.getByText('No fields match the current filter.')).toBeTruthy();

    rerender(<FieldListPanel {...props} currentPage={3} />);
    expect(screen.getByText('No fields on page 3.')).toBeTruthy();
  });

  it('wires Fields/Names/All/Info/Clear controls and respects clear disabled state', async () => {
    const user = userEvent.setup();
    const onShowFieldsChange = vi.fn();
    const onShowFieldNamesChange = vi.fn();
    const onShowFieldInfoChange = vi.fn();
    const onClearInputs = vi.fn();
    const props = createProps({
      showFields: true,
      showFieldNames: false,
      showFieldInfo: false,
      onShowFieldsChange,
      onShowFieldNamesChange,
      onShowFieldInfoChange,
      onClearInputs,
      canClearInputs: true,
    });
    const { rerender } = render(<FieldListPanel {...props} />);

    await user.click(screen.getByRole('checkbox', { name: 'Fields' }));
    await user.click(screen.getByRole('checkbox', { name: 'Names' }));
    await user.click(screen.getByRole('checkbox', { name: 'Info' }));
    await user.click(screen.getByRole('button', { name: 'Clear' }));

    expect(onShowFieldsChange).toHaveBeenCalledWith(false);
    expect(onShowFieldNamesChange).toHaveBeenCalledWith(true);
    expect(onShowFieldInfoChange).toHaveBeenCalledWith(true);
    expect(onClearInputs).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('checkbox', { name: 'All' }));
    expect(screen.getByRole('button', { name: /Signature/i })).toBeTruthy();

    rerender(<FieldListPanel {...props} canClearInputs={false} />);
    expect((screen.getByRole('button', { name: 'Clear' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('updates confidence filter controls and shows confidence labels', async () => {
    const user = userEvent.setup();
    const onConfidenceFilterChange = vi.fn();

    render(
      <FieldListPanel
        {...createProps({
          onConfidenceFilterChange,
          confidenceFilter: { high: true, medium: false, low: true },
        })}
      />,
    );

    await user.click(screen.getByRole('checkbox', { name: 'Medium' }));
    await user.click(screen.getByRole('checkbox', { name: 'High' }));

    expect(onConfidenceFilterChange).toHaveBeenNthCalledWith(1, 'medium', true);
    expect(onConfidenceFilterChange).toHaveBeenNthCalledWith(2, 'high', false);

    expect(screen.getByText('90% field')).toBeTruthy();
    expect(screen.getByText('70% name')).toBeTruthy();
    expect(screen.getByText('60% field')).toBeTruthy();
    expect(screen.getByText('55% field remap')).toBeTruthy();
  });

  it('rounds fractional page input to the nearest integer', async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    const props = createProps({ onPageChange, currentPage: 1, pageCount: 3 });
    render(<FieldListPanel {...props} />);

    const pageInput = screen.getByLabelText('Page');
    await user.clear(pageInput);
    await user.type(pageInput, '1.5');

    const pageCalls = onPageChange.mock.calls.map((call) => call[0] as number);
    for (const value of pageCalls) {
      expect(Number.isInteger(value)).toBe(true);
    }
  });

  it('selects fields and switches pages when All mode is enabled', async () => {
    const user = userEvent.setup();
    const onSelectField = vi.fn();
    const onPageChange = vi.fn();

    render(
      <FieldListPanel
        {...createProps({
          currentPage: 1,
          pageCount: 2,
          onSelectField,
          onPageChange,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Full Name/i }));
    expect(onSelectField).toHaveBeenLastCalledWith('f1');
    expect(onPageChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole('checkbox', { name: 'All' }));
    await user.click(screen.getByRole('button', { name: /Signature/i }));

    expect(onPageChange).toHaveBeenCalledWith(2);
    expect(onSelectField).toHaveBeenLastCalledWith('f3');
  });
});
