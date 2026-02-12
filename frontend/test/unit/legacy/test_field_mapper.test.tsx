import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  uploadDatabaseFields: vi.fn(),
  mapFields: vi.fn(),
}));

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    uploadDatabaseFields: apiMocks.uploadDatabaseFields,
    mapFields: apiMocks.mapFields,
  },
}));

import FieldMapper from '../../fixtures/legacy/FieldMapper';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const getFileInput = () => document.getElementById('fields-upload') as HTMLInputElement;

const uploadValidTxtFile = async (filename = 'db_fields.txt') => {
  apiMocks.uploadDatabaseFields.mockResolvedValue({
    filename,
    databaseFields: ['first_name', 'last_name', 'dob', 'mrn', 'email', 'phone'],
    totalFields: 6,
  });

  fireEvent.change(getFileInput(), {
    target: { files: [new File(['first_name\nlast_name'], filename, { type: 'text/plain' })] },
  });

  await screen.findByText(`Uploaded: ${filename}`);
};

describe('FieldMapper', () => {
  beforeEach(() => {
    apiMocks.uploadDatabaseFields.mockReset();
    apiMocks.mapFields.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('validates uploaded file type before calling upload API', async () => {
    render(<FieldMapper sessionId="session-1" />);

    fireEvent.change(getFileInput(), {
      target: { files: [new File(['a,b'], 'fields.csv', { type: 'text/csv' })] },
    });

    expect(
      await screen.findByText('Please upload a .txt file containing database field names'),
    ).toBeTruthy();
    expect(apiMocks.uploadDatabaseFields).not.toHaveBeenCalled();
  });

  it('shows upload progress and success preview after uploading database fields', async () => {
    render(<FieldMapper sessionId="session-1" />);

    const pending = deferred<{ filename: string; databaseFields: string[]; totalFields: number }>();
    apiMocks.uploadDatabaseFields.mockReturnValue(pending.promise);

    fireEvent.change(getFileInput(), {
      target: { files: [new File(['first_name'], 'db_fields.txt', { type: 'text/plain' })] },
    });

    expect(screen.getByText('Uploading...')).toBeTruthy();
    expect(getFileInput().disabled).toBe(true);

    pending.resolve({
      filename: 'db_fields.txt',
      databaseFields: ['first_name', 'last_name', 'dob', 'mrn', 'email', 'phone'],
      totalFields: 6,
    });

    expect(await screen.findByText('Uploaded: db_fields.txt')).toBeTruthy();
    expect(screen.getByText('Loaded 6 database fields')).toBeTruthy();
    expect(screen.getByText('first_name')).toBeTruthy();
    expect(screen.getByText('+1 more')).toBeTruthy();
  });

  it('generates mappings, renders results, and colors confidence badges by threshold', async () => {
    const onMappingsGenerated = vi.fn();
    const pdfFormFields = [{ name: 'member_first_name' }, { name: 'member_last_name' }];

    render(
      <FieldMapper
        sessionId="session-abc"
        pdfFormFields={pdfFormFields}
        onMappingsGenerated={onMappingsGenerated}
      />,
    );

    await uploadValidTxtFile();

    const pending = deferred<any>();
    apiMocks.mapFields.mockReturnValue(pending.promise);

    fireEvent.click(screen.getByRole('button', { name: /Generate AI Mappings/i }));

    expect(screen.getByText('Generating AI Mappings...')).toBeTruthy();

    pending.resolve({
      success: true,
      mappingResults: {
        mappings: [
          {
            id: 'map-1',
            databaseField: 'first_name',
            pdfField: 'member_first_name',
            confidence: 0.9,
            reasoning: 'exact match',
          },
          {
            id: 'map-2',
            databaseField: 'last_name',
            pdfField: 'member_last_name',
            confidence: 0.7,
            reasoning: 'close match',
          },
          {
            id: 'map-3',
            databaseField: 'city',
            pdfField: 'member_city',
            confidence: 0.5,
            reasoning: 'weak match',
          },
        ],
        unmappedDatabaseFields: ['member_middle_name'],
        unmappedPdfFields: ['member_suffix'],
        confidence: 0.72,
      },
    });

    expect(await screen.findByText('AI-Generated Field Mappings')).toBeTruthy();

    expect(apiMocks.mapFields).toHaveBeenCalledWith(
      'session-abc',
      ['first_name', 'last_name', 'dob', 'mrn', 'email', 'phone'],
      pdfFormFields,
    );
    expect(onMappingsGenerated).toHaveBeenCalledWith({
      mappings: [
        {
          id: 'map-1',
          databaseField: 'first_name',
          pdfField: 'member_first_name',
          confidence: 0.9,
          reasoning: 'exact match',
        },
        {
          id: 'map-2',
          databaseField: 'last_name',
          pdfField: 'member_last_name',
          confidence: 0.7,
          reasoning: 'close match',
        },
        {
          id: 'map-3',
          databaseField: 'city',
          pdfField: 'member_city',
          confidence: 0.5,
          reasoning: 'weak match',
        },
      ],
      unmappedDatabaseFields: ['member_middle_name'],
      unmappedPdfFields: ['member_suffix'],
      confidence: 0.72,
    });

    expect(screen.getByText('member_middle_name')).toBeTruthy();
    expect(screen.getByText('member_suffix')).toBeTruthy();

    const highBadge = screen.getByText('90%') as HTMLElement;
    const mediumBadge = screen.getByText('70%') as HTMLElement;
    const lowBadge = screen.getByText('50%') as HTMLElement;
    const overallConfidence = screen.getByText('72%') as HTMLElement;

    expect(highBadge.style.backgroundColor).toBe('rgb(16, 185, 129)');
    expect(mediumBadge.style.backgroundColor).toBe('rgb(245, 158, 11)');
    expect(lowBadge.style.backgroundColor).toBe('rgb(239, 68, 68)');
    expect(overallConfidence.style.color).toBe('rgb(245, 158, 11)');
  });

  it('shows mapping errors when generation fails', async () => {
    render(<FieldMapper sessionId="session-1" />);

    await uploadValidTxtFile();

    apiMocks.mapFields.mockResolvedValue({ success: false, error: 'Mapping generation failed on server' });
    fireEvent.click(screen.getByRole('button', { name: /Generate AI Mappings/i }));

    expect(await screen.findByText('Mapping generation failed on server')).toBeTruthy();
  });

  it('applies a single mapping with renamed-field callback payload and marks it applied', async () => {
    const onFieldRenamed = vi.fn();

    render(<FieldMapper sessionId="session-1" onFieldRenamed={onFieldRenamed} />);

    await uploadValidTxtFile();

    apiMocks.mapFields.mockResolvedValue({
      success: true,
      mappingResults: {
        mappings: [
          {
            id: 'map-1',
            databaseField: 'member_name',
            originalPdfField: 'old_pdf_name',
            pdfField: 'new_pdf_name',
            confidence: 87,
            reasoning: 'semantic match',
          },
        ],
        unmappedDatabaseFields: [],
        unmappedPdfFields: [],
        confidence: 0.87,
      },
    });

    fireEvent.click(screen.getByRole('button', { name: /Generate AI Mappings/i }));
    await screen.findByText('Apply Mapping');

    fireEvent.click(screen.getByRole('button', { name: 'Apply Mapping' }));

    expect(onFieldRenamed).toHaveBeenCalledWith('old_pdf_name', 'new_pdf_name', 0.87);
    expect(await screen.findByRole('button', { name: 'Applied' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Applied' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('resets upload and mapping state when starting over', async () => {
    render(<FieldMapper sessionId="session-1" />);

    await uploadValidTxtFile();

    apiMocks.mapFields.mockResolvedValue({
      success: true,
      mappingResults: {
        mappings: [
          {
            id: 'map-1',
            databaseField: 'first_name',
            pdfField: 'member_first_name',
            confidence: 0.9,
            reasoning: 'exact match',
          },
        ],
        unmappedDatabaseFields: [],
        unmappedPdfFields: [],
        confidence: 0.9,
      },
    });

    fireEvent.click(screen.getByRole('button', { name: /Generate AI Mappings/i }));
    await screen.findByText('AI-Generated Field Mappings');

    fireEvent.click(screen.getByRole('button', { name: 'Start Over' }));

    await waitFor(() => {
      expect(screen.queryByText('AI-Generated Field Mappings')).toBeNull();
    });
    expect(screen.getByText('Choose database fields file (.txt)')).toBeTruthy();
    expect(getFileInput().value).toBe('');
  });
});
