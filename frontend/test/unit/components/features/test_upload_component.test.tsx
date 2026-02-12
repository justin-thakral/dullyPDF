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

    const rowAButton = screen.getByText('Saved A').closest('button') as HTMLButtonElement;
    const rowBButton = screen.getByText('Saved B').closest('button') as HTMLButtonElement;
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
});
