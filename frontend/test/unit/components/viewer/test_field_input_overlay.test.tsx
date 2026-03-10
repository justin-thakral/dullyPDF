import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import type { PdfField } from '../../../../src/types';
import { FieldInputOverlay } from '../../../../src/components/viewer/FieldInputOverlay';

function makeField(overrides: Partial<PdfField> & Pick<PdfField, 'id' | 'name' | 'type'>): PdfField {
  return {
    id: overrides.id,
    name: overrides.name,
    type: overrides.type,
    page: 1,
    rect: { x: 10, y: 20, width: 100, height: 20 },
    ...overrides,
  };
}

function StatefulOverlay({
  initialFields,
  onSelectField,
  onUpdateField,
}: {
  initialFields: PdfField[];
  onSelectField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
}) {
  const [fields, setFields] = useState<PdfField[]>(initialFields);

  return (
    <FieldInputOverlay
      fields={fields}
      pageSize={{ width: 200, height: 100 }}
      scale={1}
      selectedFieldId={null}
      onSelectField={onSelectField}
      onUpdateField={(fieldId, updates) => {
        onUpdateField(fieldId, updates);
        setFields((prev) =>
          prev.map((field) => (field.id === fieldId ? { ...field, ...updates } : field)),
        );
      }}
    />
  );
}

describe('FieldInputOverlay', () => {
  it('renders text/date/checkbox input types with coerced values and scaled geometry', () => {
    const fields = [
      makeField({
        id: 'text',
        name: 'amount',
        type: 'text',
        rect: { x: 5, y: 10, width: 60, height: 12 },
        value: 42,
      }),
      makeField({
        id: 'date',
        name: 'visit_date',
        type: 'date',
        rect: { x: 20, y: 12, width: 40, height: 10 },
        value: '2025-01-02',
      }),
      makeField({
        id: 'checkbox',
        name: 'has_consent',
        type: 'checkbox',
        rect: { x: 15, y: 30, width: 10, height: 10 },
        value: 'yes',
      }),
    ];

    const { container } = render(
      <FieldInputOverlay
        fields={fields}
        pageSize={{ width: 200, height: 100 }}
        scale={2}
        selectedFieldId="text"
        onSelectField={vi.fn()}
        onUpdateField={vi.fn()}
      />,
    );

    const layer = container.querySelector('.field-layer') as HTMLDivElement;
    expect(layer.style.width).toBe('400px');
    expect(layer.style.height).toBe('200px');

    const textInput = screen.getByLabelText('amount') as HTMLInputElement;
    const dateInput = screen.getByLabelText('visit_date') as HTMLInputElement;
    const checkboxInput = screen.getByRole('checkbox', { name: 'has_consent' }) as HTMLInputElement;

    expect(textInput.type).toBe('text');
    expect(textInput.value).toBe('42');
    expect(dateInput.type).toBe('date');
    expect(dateInput.value).toBe('2025-01-02');
    expect(checkboxInput.checked).toBe(true);

    const textBox = container.querySelector('[data-field-id="text"]') as HTMLDivElement;
    expect(textBox.style.left).toBe('10px');
    expect(textBox.style.top).toBe('20px');
    expect(textBox.style.width).toBe('120px');
    expect(textBox.style.height).toBe('24px');
  });

  it('does not treat NaN checkbox values as checked', () => {
    render(
      <FieldInputOverlay
        fields={[
          makeField({
            id: 'nan-checkbox',
            name: 'accept_terms',
            type: 'checkbox',
            value: Number.NaN,
          }),
        ]}
        pageSize={{ width: 200, height: 100 }}
        scale={1}
        selectedFieldId={null}
        onSelectField={vi.fn()}
        onUpdateField={vi.fn()}
      />,
    );

    const checkboxInput = screen.getByRole('checkbox', { name: 'accept_terms' }) as HTMLInputElement;
    expect(checkboxInput.checked).toBe(false);
  });

  it('fires select-on-focus and update callbacks on text and checkbox changes', async () => {
    const user = userEvent.setup();
    const onSelectField = vi.fn();
    const onUpdateField = vi.fn();
    const fields = [
      makeField({ id: 'text', name: 'patient_name', type: 'text', value: '' }),
      makeField({ id: 'checkbox', name: 'active', type: 'checkbox', value: false }),
    ];

    render(
      <StatefulOverlay
        initialFields={fields}
        onSelectField={onSelectField}
        onUpdateField={onUpdateField}
      />,
    );

    const textInput = screen.getByLabelText('patient_name');
    const checkboxInput = screen.getByRole('checkbox', { name: 'active' });

    await user.click(textInput);
    expect(onSelectField).toHaveBeenCalledWith('text');

    await user.type(textInput, 'Ada');
    expect((textInput as HTMLInputElement).value).toBe('Ada');
    await user.tab();
    const lastTextUpdate = onUpdateField.mock.calls
      .filter((call) => call[0] === 'text')
      .slice(-1)[0];
    expect(lastTextUpdate).toEqual(['text', { value: 'Ada' }]);

    await user.click(checkboxInput);
    expect(onSelectField).toHaveBeenCalledWith('checkbox');
    expect(onUpdateField).toHaveBeenCalledWith('checkbox', { value: true });
  });

  it('normalizes empty date values to null on blur', async () => {
    const user = userEvent.setup();
    const onUpdateField = vi.fn();
    render(
      <StatefulOverlay
        initialFields={[
          makeField({
            id: 'date',
            name: 'appointment_date',
            type: 'date',
            value: '2025-03-15',
          }),
        ]}
        onSelectField={vi.fn()}
        onUpdateField={onUpdateField}
      />,
    );

    const dateInput = screen.getByLabelText('appointment_date');
    await user.clear(dateInput);
    await user.tab();

    expect(onUpdateField).toHaveBeenCalledWith('date', { value: null });
  });
});
