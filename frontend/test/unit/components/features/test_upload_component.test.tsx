import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import UploadComponent from '../../../../src/components/features/UploadComponent';

describe('UploadComponent', () => {
  it('validates file type/extension and max-size before upload', async () => {
    const user = userEvent.setup({ applyAccept: false });
    const onFileUpload = vi.fn();
    const onValidationError = vi.fn();
    render(
      <UploadComponent
        variant="detect"
        onFileUpload={onFileUpload}
        onValidationError={onValidationError}
      />,
    );

    const input = screen.getByLabelText('Upload PDF Document') as HTMLInputElement;

    const invalidFile = new File(['abc'], 'notes.txt', { type: 'text/plain' });
    await user.upload(input, invalidFile);
    expect(onValidationError).toHaveBeenCalledWith('Please select a PDF file.');

    const tooLarge = new File(['x'], 'large.pdf', { type: 'application/pdf' });
    Object.defineProperty(tooLarge, 'size', { configurable: true, value: 51 * 1024 * 1024 });
    await user.upload(input, tooLarge);
    expect(onValidationError).toHaveBeenCalledWith('File size must be less than 50MB.');

    const validPdf = new File(['%PDF-1.7'], 'valid.pdf', { type: 'application/pdf' });
    await user.upload(input, validPdf);
    expect(onFileUpload).toHaveBeenCalledWith(validPdf);
  });

  it('supports input upload, keyboard activation, and drag-drop paths', async () => {
    const user = userEvent.setup();
    const onFileUpload = vi.fn();
    render(<UploadComponent variant="detect" onFileUpload={onFileUpload} />);

    const input = screen.getByLabelText('Upload PDF Document') as HTMLInputElement;
    const dropzone = screen.getByRole('button');

    const pickerSpy = vi.fn();
    (input as HTMLInputElement & { showPicker?: () => void }).showPicker = pickerSpy;
    dropzone.focus();
    await user.keyboard('{Enter}');
    expect(pickerSpy).toHaveBeenCalledTimes(1);

    const uploaded = new File(['input'], 'input.pdf', { type: 'application/pdf' });
    await user.upload(input, uploaded);
    expect(onFileUpload).toHaveBeenCalledWith(uploaded);

    const dropped = new File(['drop'], 'dropped.pdf', { type: 'application/pdf' });
    fireEvent.dragEnter(dropzone);
    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [dropped],
      },
    });
    expect(onFileUpload).toHaveBeenCalledWith(dropped);
  });

  it('renders saved variant, wires select/delete callbacks, and respects deleting state', async () => {
    const user = userEvent.setup();
    const onSelectSavedForm = vi.fn();
    const onDeleteSavedForm = vi.fn();
    render(
      <UploadComponent
        variant="saved"
        savedForms={[
          { id: 'a', name: 'Saved A', createdAt: '2025-01-01T00:00:00.000Z' },
          { id: 'b', name: 'Saved B', createdAt: '' },
        ]}
        deletingFormId="a"
        onSelectSavedForm={onSelectSavedForm}
        onDeleteSavedForm={onDeleteSavedForm}
      />,
    );

    expect(screen.getByText('Saved A')).toBeTruthy();
    expect(screen.getByText('Saved B')).toBeTruthy();
    expect(screen.getByText('Unknown date')).toBeTruthy();

    const rowAButton = screen.getByRole('button', { name: /^Saved A/i }) as HTMLButtonElement;
    const rowBButton = screen.getByRole('button', { name: /^Saved B/i }) as HTMLButtonElement;
    const deleteA = screen.getByRole('button', { name: 'Delete saved form Saved A' }) as HTMLButtonElement;
    const deleteB = screen.getByRole('button', { name: 'Delete saved form Saved B' });

    expect(rowAButton.disabled).toBe(true);
    expect(deleteA.disabled).toBe(true);
    expect(deleteA.textContent).toBe('Loading…');

    await user.click(rowAButton);
    await user.click(deleteA);
    expect(onSelectSavedForm).not.toHaveBeenCalled();
    expect(onDeleteSavedForm).not.toHaveBeenCalled();

    await user.click(rowBButton);
    await user.click(deleteB);
    expect(onSelectSavedForm).toHaveBeenCalledWith('b');
    expect(onDeleteSavedForm).toHaveBeenCalledWith('b');
  });

  it('supports group filtering, opening and deleting groups, and launching create group from saved forms', async () => {
    const user = userEvent.setup();
    const onSelectGroupFilter = vi.fn();
    const onOpenGroup = vi.fn();
    const onDeleteGroup = vi.fn();
    const onEditGroup = vi.fn();
    const onOpenCreateGroup = vi.fn();
    const { rerender } = render(
      <UploadComponent
        variant="saved"
        savedForms={[
          { id: 'a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' },
          { id: 'b', name: 'Bravo Intake', createdAt: '2025-01-02T00:00:00.000Z' },
          { id: 'c', name: 'Charlie Consent', createdAt: '2025-01-03T00:00:00.000Z' },
        ]}
        groups={[
          {
            id: 'group-1',
            name: 'Admissions',
            templateIds: ['a', 'c'],
            templateCount: 2,
            templates: [],
          },
        ]}
        selectedGroupFilterId="all"
        onSelectGroupFilter={onSelectGroupFilter}
        onOpenGroup={onOpenGroup}
        onDeleteGroup={onDeleteGroup}
        onEditGroup={onEditGroup}
        onOpenCreateGroup={onOpenCreateGroup}
      />,
    );

    await user.selectOptions(screen.getByRole('combobox'), 'group-1');
    expect(onSelectGroupFilter).toHaveBeenCalledWith('group-1');

    await user.click(screen.getByRole('checkbox', { name: /Switch to groups/i }));
    await user.click(screen.getByRole('button', { name: /^Admissions/i }));
    await user.click(screen.getByRole('button', { name: 'Edit group Admissions' }));
    await user.click(screen.getByRole('button', { name: 'Delete group Admissions' }));
    await user.click(screen.getByRole('button', { name: 'Create Group' }));
    expect(onOpenGroup).toHaveBeenCalledWith('group-1');
    expect(onEditGroup).toHaveBeenCalledWith('group-1');
    expect(onDeleteGroup).toHaveBeenCalledWith('group-1');
    expect(onOpenCreateGroup).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('checkbox', { name: /Switch to templates/i }));

    rerender(
      <UploadComponent
        variant="saved"
        savedForms={[
          { id: 'a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' },
          { id: 'b', name: 'Bravo Intake', createdAt: '2025-01-02T00:00:00.000Z' },
          { id: 'c', name: 'Charlie Consent', createdAt: '2025-01-03T00:00:00.000Z' },
        ]}
        groups={[
          {
            id: 'group-1',
            name: 'Admissions',
            templateIds: ['a', 'c'],
            templateCount: 2,
            templates: [],
          },
        ]}
        selectedGroupFilterId="group-1"
      />,
    );

    expect(screen.getByText('Alpha Packet')).toBeTruthy();
    expect(screen.getByText('Charlie Consent')).toBeTruthy();
    expect(screen.queryByText('Bravo Intake')).toBeNull();
  });

  it('applies default headings/subtitles for detect, fillable, and saved variants', () => {
    const { rerender } = render(<UploadComponent variant="detect" />);
    expect(screen.getByText('Upload PDF Document')).toBeTruthy();
    expect(screen.getByText(/Drag and drop your PDF file here, or click to browse/i)).toBeTruthy();

    rerender(<UploadComponent variant="fillable" />);
    expect(screen.getByText('Upload Fillable PDF Template')).toBeTruthy();
    expect(screen.getByText('Open your existing fillable PDF directly in the editor')).toBeTruthy();
    expect(screen.queryByText('click to browse')).toBeNull();

    rerender(<UploadComponent variant="saved" savedForms={[]} />);
    expect(screen.getByText('Your Saved Forms')).toBeTruthy();
    expect(screen.getByText('Select a form from your saved templates')).toBeTruthy();
    expect(screen.getByText('No saved forms yet. Save a form to see it here.')).toBeTruthy();
  });

  it('renders the group upload variant and opens its dialog callback', async () => {
    const user = userEvent.setup();
    const onOpenDialog = vi.fn();

    render(<UploadComponent variant="group" onOpenDialog={onOpenDialog} />);

    expect(screen.getByText('Upload PDF Group')).toBeTruthy();
    expect(screen.getByText('Detect, rename, map, and group multiple PDFs in one batch')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /Upload PDF Group/i }));
    expect(onOpenDialog).toHaveBeenCalledTimes(1);
  });

  it('shows a loading message for empty saved forms while backend startup is pending', () => {
    render(<UploadComponent variant="saved" savedForms={[]} savedFormsLoading />);

    expect(screen.getByText('Loading saved forms while the backend starts…')).toBeTruthy();
    expect(screen.queryByText('No saved forms yet. Save a form to see it here.')).toBeNull();
  });

  it('shows the empty-state message when a selected group has no matching saved forms', () => {
    render(
      <UploadComponent
        variant="saved"
        savedForms={[{ id: 'a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' }]}
        groups={[
          {
            id: 'group-1',
            name: 'Admissions',
            templateIds: ['missing'],
            templateCount: 1,
            templates: [],
          },
        ]}
        selectedGroupFilterId="group-1"
      />,
    );

    expect(screen.getByText('No saved forms match this group filter.')).toBeTruthy();
  });

  it('keeps a stable group-filter label when the selected group is not yet present in the options', async () => {
    const user = userEvent.setup();
    const onSelectGroupFilter = vi.fn();

    const { rerender } = render(
      <UploadComponent
        variant="saved"
        savedForms={[{ id: 'a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' }]}
        groups={[]}
        groupsLoading
        selectedGroupFilterId="group-1"
        onSelectGroupFilter={onSelectGroupFilter}
      />,
    );

    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('__selected_group_pending__');
    expect(
      ((screen.getByRole('combobox') as HTMLSelectElement).selectedOptions.item(0)?.textContent) || '',
    ).toBe('Loading selected group…');

    rerender(
      <UploadComponent
        variant="saved"
        savedForms={[{ id: 'a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' }]}
        groups={[
          {
            id: 'group-1',
            name: 'Admissions',
            templateIds: ['a'],
            templateCount: 1,
            templates: [],
          },
        ]}
        selectedGroupFilterId="group-1"
        onSelectGroupFilter={onSelectGroupFilter}
      />,
    );

    expect(
      ((screen.getByRole('combobox') as HTMLSelectElement).selectedOptions.item(0)?.textContent) || '',
    ).toBe('Admissions');
    await user.selectOptions(screen.getByRole('combobox'), 'all');
    expect(onSelectGroupFilter).toHaveBeenCalledWith('all');
  });

  it('does not leak all saved forms while a missing selected group is still resolving', () => {
    render(
      <UploadComponent
        variant="saved"
        savedForms={[
          { id: 'a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' },
          { id: 'b', name: 'Bravo Intake', createdAt: '2025-01-02T00:00:00.000Z' },
        ]}
        groups={[]}
        groupsLoading
        selectedGroupFilterId="group-1"
        selectedGroupFilterLabel="Admissions"
      />,
    );

    expect(screen.getByText('No saved forms match this group filter.')).toBeTruthy();
    expect(screen.queryByText('Alpha Packet')).toBeNull();
    expect(screen.queryByText('Bravo Intake')).toBeNull();
    expect(
      ((screen.getByRole('combobox') as HTMLSelectElement).selectedOptions.item(0)?.textContent) || '',
    ).toBe('Admissions');
  });
});
