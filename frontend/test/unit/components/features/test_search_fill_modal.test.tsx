import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';

import type { CheckboxHint, CheckboxRule, PdfField, TextTransformRule } from '../../../../src/types';
import SearchFillModal from '../../../../src/components/features/SearchFillModal';

function makeField(overrides: Partial<PdfField> & Pick<PdfField, 'id' | 'name' | 'type' | 'page'>): PdfField {
  return {
    id: overrides.id,
    name: overrides.name,
    type: overrides.type,
    page: overrides.page,
    rect: { x: 0, y: 0, width: 100, height: 20 },
    ...overrides,
  };
}

function buildProps(overrides: Partial<ComponentProps<typeof SearchFillModal>> = {}) {
  return {
    open: true,
    onClose: vi.fn(),
    sessionId: 1,
    dataSourceKind: 'csv' as const,
    dataSourceLabel: 'records.csv',
    columns: ['mrn', 'full_name'],
    identifierKey: 'mrn',
    rows: [{ mrn: '001', full_name: 'Ada Lovelace' }],
    fields: [] as PdfField[],
    checkboxRules: [] as CheckboxRule[],
    checkboxHints: [] as CheckboxHint[],
    onFieldsChange: vi.fn(),
    onClearFields: vi.fn(),
    onAfterFill: vi.fn(),
    onError: vi.fn(),
    onRequestDataSource: vi.fn(),
    demoSearch: null,
    ...overrides,
  };
}

async function runSearch(query: string) {
  const user = userEvent.setup();
  const queryInput = screen.getByLabelText('Search');
  await user.clear(queryInput);
  await user.type(queryInput, query);
  await user.click(screen.getByRole('button', { name: 'Search' }));
}

describe('SearchFillModal', () => {
  it('validates missing source, rows, query, and search key', async () => {
    const user = userEvent.setup();

    const propsMissingSource = buildProps({
      dataSourceKind: 'none',
      dataSourceLabel: null,
      rows: [{ mrn: '001', full_name: 'Ada Lovelace' }],
    });
    const { rerender } = render(<SearchFillModal {...propsMissingSource} />);
    await runSearch('ada');
    expect(screen.getByText('Choose a CSV, Excel, JSON, or respondent source first.')).toBeTruthy();

    const propsMissingRows = buildProps({
      rows: [],
      demoSearch: {
        query: 'ada',
        searchKey: 'mrn',
        searchMode: 'contains',
        autoRun: true,
        token: 12,
      },
    });
    rerender(<SearchFillModal {...propsMissingRows} />);
    await waitFor(() => {
      expect(screen.getByText('No record rows are available to search.')).toBeTruthy();
    });

    const propsMissingQuery = buildProps({
      rows: [{ mrn: '001', full_name: 'Ada Lovelace' }],
    });
    rerender(<SearchFillModal {...propsMissingQuery} />);
    await user.click(screen.getByRole('button', { name: 'Search' }));
    expect(screen.getByText('Enter a search value.')).toBeTruthy();

    const propsMissingSearchKey = buildProps({
      columns: [],
      identifierKey: null,
      rows: [{ mrn: '001', full_name: 'Ada Lovelace' }],
    });
    rerender(<SearchFillModal {...propsMissingSearchKey} />);
    await runSearch('ada');
    expect(screen.getByText('Choose a column to search.')).toBeTruthy();
  });

  it('supports contains/equals search, any-column mode, and result limits', async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: 30 }, (_, index) => ({
      mrn: `${index + 1}`,
      full_name: `Alex ${index + 1}`,
      city: index % 2 === 0 ? 'Austin' : 'Boston',
    }));
    const props = buildProps({
      columns: ['mrn', 'full_name', 'city'],
      identifierKey: 'mrn',
      rows,
    });
    render(<SearchFillModal {...props} />);

    await user.selectOptions(screen.getByLabelText('Column'), '__any__');
    await runSearch('alex');

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Fill PDF' })).toHaveLength(25);
    });

    await user.selectOptions(screen.getByLabelText('Match'), 'equals');
    await user.selectOptions(screen.getByLabelText('Column'), 'full_name');
    await runSearch('alex 7');

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Fill PDF' })).toHaveLength(1);
      expect(screen.getByText('7 • Alex 7')).toBeTruthy();
    });
  });

  it('renders row preview content and wires Fill PDF action callbacks', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const onAfterFill = vi.fn();
    const onClose = vi.fn();
    const fields = [
      makeField({ id: 'full-name', name: 'full_name', type: 'text', page: 1 }),
    ];
    const props = buildProps({
      rows: [
        {
          mrn: '12345',
          full_name: 'Grace Hopper',
          dob: '1906-12-09',
          phone: '+1-555-1000',
          email: 'grace@example.com',
        },
      ],
      fields,
      onFieldsChange,
      onAfterFill,
      onClose,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('12345');
    expect(screen.getByText('12345 • Grace Hopper')).toBeTruthy();
    expect(screen.getByText('DOB 1906-12-09 • +1-555-1000 • grace@example.com')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
      expect(onAfterFill).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('supports selecting multiple group PDF targets before filling', async () => {
    const user = userEvent.setup();
    const onFillTargets = vi.fn();
    const onAfterFill = vi.fn();
    const onClose = vi.fn();

    render(
      <SearchFillModal
        {...buildProps({
          rows: [{ mrn: '100', full_name: 'Ada Lovelace' }],
          fillTargets: [
            { id: 'tpl-a', name: 'Admissions Packet' },
            { id: 'tpl-b', name: 'Consent Form' },
          ],
          activeFillTargetId: 'tpl-a',
          onFillTargets,
          onAfterFill,
          onClose,
        })}
      />,
    );

    expect(screen.getByText('Select which PDFs receive the row')).toBeTruthy();
    expect(screen.getByText('1 PDF selected')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'All PDFs' }));
    expect(screen.getByText('2 PDFs selected')).toBeTruthy();

    await runSearch('100');
    await user.click(screen.getByRole('button', { name: 'Fill selected PDFs' }));

    await waitFor(() => {
      expect(onFillTargets).toHaveBeenCalledWith(
        { mrn: '100', full_name: 'Ada Lovelace' },
        ['tpl-a', 'tpl-b'],
      );
      expect(onAfterFill).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('clears stale field values before applying a respondent record', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'full-name', name: 'full_name', type: 'text', page: 1, value: 'Justin Thakral' }),
      makeField({ id: 'member-id', name: 'member_id', type: 'text', page: 1, value: 'OLD-1' }),
    ];
    const props = buildProps({
      dataSourceKind: 'respondent',
      dataSourceLabel: 'Fill By Link respondents',
      columns: ['respondent_label', 'member_id'],
      identifierKey: 'respondent_label',
      rows: [{ respondent_label: 'Ada Lovelace', member_id: 'NEW-42' }],
      fields,
      onFieldsChange,
    });

    render(<SearchFillModal {...props} />);

    await runSearch('Ada');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const byId = new Map(nextFields.map((field) => [field.id, field.value]));
    expect(byId.get('full-name')).toBeNull();
    expect(byId.get('member-id')).toBe('NEW-42');
  });

  it('fills text/date fields using direct and fallback key heuristics', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'name', name: 'name', type: 'text', page: 1 }),
      makeField({ id: 'appointment-date', name: 'appointment_date', type: 'date', page: 1 }),
      makeField({ id: 'city-state-zip', name: 'city_state_zip', type: 'text', page: 1 }),
      makeField({ id: 'phone-one', name: 'phone_1', type: 'text', page: 1 }),
      makeField({ id: 'age', name: 'age', type: 'text', page: 1 }),
    ];
    const props = buildProps({
      columns: ['mrn', 'first_name', 'last_name', 'appointment_date', 'city', 'state', 'zip', 'phone', 'dob', 'date'],
      rows: [
        {
          mrn: '900',
          first_name: 'Ada',
          last_name: 'Lovelace',
          appointment_date: '2025-01-02T15:30:00Z',
          city: 'London',
          state: 'UK',
          zip: '12345',
          phone: '111-222',
          dob: '1990-01-01',
          date: '2024-01-02',
        },
      ],
      fields,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('900');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const byId = new Map(nextFields.map((field) => [field.id, field]));

    expect(byId.get('name')?.value).toBe('Ada Lovelace');
    expect(byId.get('appointment-date')?.value).toBe('2025-01-02');
    expect(byId.get('city-state-zip')?.value).toBe('London, UK, 12345');
    expect(byId.get('phone-one')?.value).toBe('111-222');
    expect(byId.get('age')?.value).toBe(34);
  });

  it('applies concat text transform rules when direct values are missing', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'full-name', name: 'full_name', type: 'text', page: 1 }),
    ];
    const textTransformRules: TextTransformRule[] = [
      {
        targetField: 'full_name',
        operation: 'concat',
        sources: ['first_name', 'last_name'],
        separator: ' ',
        confidence: 0.92,
      },
    ];

    const props = buildProps({
      columns: ['mrn', 'first_name', 'last_name'],
      rows: [{ mrn: '910', first_name: 'Ada', last_name: 'Lovelace' }],
      fields,
      textTransformRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('910');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    expect(nextFields[0]?.value).toBe('Ada Lovelace');
  });

  it('applies split_name_first_rest rules from full_name into first/last fields', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'first-name', name: 'first_name', type: 'text', page: 1 }),
      makeField({ id: 'last-name', name: 'last_name', type: 'text', page: 1 }),
    ];
    const textTransformRules: TextTransformRule[] = [
      {
        targetField: 'first_name',
        operation: 'split_name_first_rest',
        sources: ['full_name'],
        part: 'first',
        confidence: 0.88,
      },
      {
        targetField: 'last_name',
        operation: 'split_name_first_rest',
        sources: ['full_name'],
        part: 'rest',
        confidence: 0.88,
      },
    ];

    const props = buildProps({
      columns: ['mrn', 'full_name'],
      rows: [{ mrn: '911', full_name: 'Mary Ann Smith' }],
      fields,
      textTransformRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('911');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const byId = new Map(nextFields.map((field) => [field.id, field]));
    expect(byId.get('first-name')?.value).toBe('Mary');
    expect(byId.get('last-name')?.value).toBe('Ann Smith');
  });

  it('prefers direct row values over text transform rules for the same target field', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'first-name', name: 'first_name', type: 'text', page: 1 }),
    ];
    const textTransformRules: TextTransformRule[] = [
      {
        targetField: 'first_name',
        operation: 'split_name_first_rest',
        sources: ['full_name'],
        part: 'first',
        confidence: 0.95,
      },
    ];

    const props = buildProps({
      columns: ['mrn', 'first_name', 'full_name'],
      rows: [{ mrn: '912', first_name: 'Direct', full_name: 'Derived Value' }],
      fields,
      textTransformRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('912');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    expect(nextFields[0]?.value).toBe('Direct');
  });

  it('normalizes slash-delimited YYYY/MM/DD values for date fields', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'appointment-date', name: 'appointment_date', type: 'date', page: 1 }),
    ];
    const props = buildProps({
      columns: ['mrn', 'appointment_date'],
      rows: [
        {
          mrn: '901',
          appointment_date: '2025/01/02',
        },
      ],
      fields,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('901');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    expect(nextFields[0]?.value).toBe('2025-01-02');
  });

  it('applies checkbox values from direct keys, aliases, hints, and rules with deterministic conflict resolution', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'allergies_yes', name: 'allergies_yes', type: 'checkbox', page: 1 }),
      makeField({ id: 'allergies_no', name: 'allergies_no', type: 'checkbox', page: 1 }),
      makeField({ id: 'pregnant_yes', name: 'pregnant_yes', type: 'checkbox', page: 1 }),
      makeField({ id: 'pregnant_no', name: 'pregnant_no', type: 'checkbox', page: 1 }),
      makeField({ id: 'drug_use_yes', name: 'drug_use_yes', type: 'checkbox', page: 1 }),
      makeField({ id: 'drug_use_no', name: 'drug_use_no', type: 'checkbox', page: 1 }),
      makeField({ id: 'marketing', name: 'i_marketing_opt_in', type: 'checkbox', page: 1 }),
    ];
    const checkboxHints: CheckboxHint[] = [
      {
        databaseField: 'pregnancy_status',
        groupKey: 'pregnant',
        directBooleanPossible: true,
      },
    ];
    const checkboxRules: CheckboxRule[] = [
      {
        databaseField: 'drug_status',
        groupKey: 'drug_use',
        operation: 'enum',
        valueMap: {
          reported: 'yes',
          none: 'no',
        },
      },
    ];

    const props = buildProps({
      columns: [
        'mrn',
        'has_allergies',
        'pregnancy_status',
        'drug_status',
        'i_drug_use_no',
        'i_marketing_opt_in',
      ],
      rows: [
        {
          mrn: '777',
          has_allergies: 'yes',
          pregnancy_status: 'no',
          drug_status: 'reported',
          i_drug_use_no: 'true',
          i_marketing_opt_in: 'true',
        },
      ],
      fields,
      checkboxHints,
      checkboxRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('777');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const valueById = new Map(nextFields.map((field) => [field.id, field.value]));

    expect(valueById.get('allergies_yes')).toBe(true);
    expect(valueById.get('allergies_no')).toBe(false);
    expect(valueById.get('pregnant_yes')).toBe(false);
    expect(valueById.get('pregnant_no')).toBe(true);
    expect(valueById.get('drug_use_yes')).toBeUndefined();
    expect(valueById.get('drug_use_no')).toBe(true);
    expect(valueById.get('marketing')).toBe(true);
  });

  it('wires clear-input and close interactions without card-click propagation', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onClearFields = vi.fn();
    const props = buildProps({
      fields: [
        makeField({ id: 'filled', name: 'full_name', type: 'text', page: 1, value: 'existing' }),
      ],
      onClose,
      onClearFields,
    });
    render(<SearchFillModal {...props} />);

    await user.click(screen.getByRole('button', { name: 'Clear inputs' }));
    expect(onClearFields).toHaveBeenCalledTimes(1);

    await user.click(screen.getByText('Search, Fill & Clear'));
    expect(onClose).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('presentation'));
    expect(onClose).toHaveBeenCalledTimes(2);

    const resultsRegion = screen.getByLabelText('Search results');
    expect(within(resultsRegion).getByText('No results yet.')).toBeTruthy();
    expect(document.body.querySelector('.ui-dialog-backdrop')).toBeTruthy();
    expect(document.body.querySelector('.searchfill-modal__card')).toBeTruthy();
  });

  it('applies multiple checkbox rules targeting different options in the same group', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'allergy_penicillin', name: 'allergies_penicillin', type: 'checkbox', page: 1 }),
      makeField({ id: 'allergy_shellfish', name: 'allergies_shellfish', type: 'checkbox', page: 1 }),
      makeField({ id: 'allergy_latex', name: 'allergies_latex', type: 'checkbox', page: 1 }),
    ];
    const checkboxRules: CheckboxRule[] = [
      {
        databaseField: 'has_penicillin_allergy',
        groupKey: 'allergies',
        operation: 'yes_no',
        trueOption: 'penicillin',
      },
      {
        databaseField: 'has_shellfish_allergy',
        groupKey: 'allergies',
        operation: 'yes_no',
        trueOption: 'shellfish',
      },
    ];
    const props = buildProps({
      columns: ['mrn', 'has_penicillin_allergy', 'has_shellfish_allergy'],
      rows: [
        {
          mrn: '500',
          has_penicillin_allergy: 'yes',
          has_shellfish_allergy: 'yes',
        },
      ],
      fields,
      checkboxRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('500');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const valueById = new Map(nextFields.map((field) => [field.id, field.value]));

    expect(valueById.get('allergy_penicillin')).toBe(true);
    expect(valueById.get('allergy_shellfish')).toBe(true);
    expect(valueById.get('allergy_latex')).toBe(false);
  });

  it('applies checkbox rules before hints when both target the same group', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'consent_yes', name: 'consent_yes', type: 'checkbox', page: 1 }),
      makeField({ id: 'consent_no', name: 'consent_no', type: 'checkbox', page: 1 }),
    ];
    const checkboxHints: CheckboxHint[] = [
      {
        databaseField: 'consent_status',
        groupKey: 'consent',
        directBooleanPossible: true,
      },
    ];
    const checkboxRules: CheckboxRule[] = [
      {
        databaseField: 'consent_status',
        groupKey: 'consent',
        operation: 'enum',
        valueMap: {
          '0': 'yes',
        },
      },
    ];

    const props = buildProps({
      columns: ['mrn', 'consent_status'],
      rows: [{ mrn: '600', consent_status: '0' }],
      fields,
      checkboxHints,
      checkboxRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('600');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const valueById = new Map(nextFields.map((field) => [field.id, field.value]));

    expect(valueById.get('consent_yes')).toBe(true);
    expect(valueById.get('consent_no')).toBe(false);
  });

  it('applies checkbox rules when row values only exist under patient_ prefixed keys', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'smoker_yes', name: 'smoker_yes', type: 'checkbox', page: 1 }),
      makeField({ id: 'smoker_no', name: 'smoker_no', type: 'checkbox', page: 1 }),
    ];
    const checkboxRules: CheckboxRule[] = [
      {
        databaseField: 'smoker_status',
        groupKey: 'smoker',
        operation: 'enum',
        valueMap: {
          current: 'yes',
          never: 'no',
        },
      },
    ];

    const props = buildProps({
      columns: ['mrn', 'patient_smoker_status'],
      rows: [{ mrn: '601', patient_smoker_status: 'current' }],
      fields,
      checkboxRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('601');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const valueById = new Map(nextFields.map((field) => [field.id, field.value]));

    expect(valueById.get('smoker_yes')).toBe(true);
    expect(valueById.get('smoker_no')).toBe(false);
  });

  it('normalizes compact enum values against spaced valueMap keys for checkbox rules', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'drug_yes', name: 'drug_use_yes', type: 'checkbox', page: 1 }),
      makeField({ id: 'drug_no', name: 'drug_use_no', type: 'checkbox', page: 1 }),
    ];
    const checkboxRules: CheckboxRule[] = [
      {
        databaseField: 'drug_status',
        groupKey: 'drug_use',
        operation: 'enum',
        valueMap: {
          'no reported': 'no',
        },
      },
    ];

    const props = buildProps({
      columns: ['mrn', 'drug_status'],
      rows: [{ mrn: '602', drug_status: 'NoReported' }],
      fields,
      checkboxRules,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('602');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const valueById = new Map(nextFields.map((field) => [field.id, field.value]));

    expect(valueById.get('drug_yes')).toBe(false);
    expect(valueById.get('drug_no')).toBe(true);
  });

  it('does not crash when a row value is an invalid Date object', async () => {
    const user = userEvent.setup();
    const onFieldsChange = vi.fn();
    const fields = [
      makeField({ id: 'notes', name: 'notes', type: 'text', page: 1 }),
      makeField({ id: 'valid-field', name: 'full_name', type: 'text', page: 1 }),
    ];
    const props = buildProps({
      columns: ['mrn', 'notes', 'full_name'],
      rows: [
        {
          mrn: '999',
          notes: new Date(NaN),
          full_name: 'Valid Name',
        },
      ],
      fields,
      onFieldsChange,
    });
    render(<SearchFillModal {...props} />);

    await runSearch('999');
    await user.click(screen.getByRole('button', { name: 'Fill PDF' }));

    await waitFor(() => {
      expect(onFieldsChange).toHaveBeenCalledTimes(1);
    });
    const nextFields = onFieldsChange.mock.calls[0][0] as PdfField[];
    const byId = new Map(nextFields.map((field) => [field.id, field]));

    expect(byId.get('notes')?.value).toBeNull();
    expect(byId.get('valid-field')?.value).toBe('Valid Name');
  });
});
