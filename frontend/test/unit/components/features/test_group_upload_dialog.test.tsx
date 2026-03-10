import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GroupUploadDialog } from '../../../../src/components/features/GroupUploadDialog';

vi.mock('../../../../src/components/ui/CommonFormsAttribution', () => ({
  CommonFormsAttribution: ({ suffix = '' }: { suffix?: string }) => <span>{`CommonForms${suffix}`}</span>,
}));

describe('GroupUploadDialog', () => {
  const baseProps = {
    open: true,
    groupName: 'Admissions packet',
    onGroupNameChange: vi.fn(),
    items: [],
    wantsRename: false,
    onWantsRenameChange: vi.fn(),
    wantsMap: false,
    onWantsMapChange: vi.fn(),
    processing: false,
    localError: null,
    progressLabel: 'Processing…',
    pageSummary: {
      maxPages: 100,
      totalPages: 0,
      largestPageCount: 0,
      withinLimit: true,
    },
    creditEstimate: null,
    creditsRemaining: 12,
    schemaUploadInProgress: false,
    dataSourceLabel: null,
    onChooseDataSource: vi.fn(),
    onClose: vi.fn(),
    onAddFiles: vi.fn(),
    onRemoveFile: vi.fn(),
    onConfirm: vi.fn(),
  } as const;

  it('renders separate main and side columns inside the modal body', () => {
    render(<GroupUploadDialog {...baseProps} />);

    const body = document.querySelector('.group-upload-modal__body');
    expect(body).toBeTruthy();
    expect(body?.children.length).toBe(2);
    expect(body?.children[0]?.className).toContain('group-upload-modal__column--main');
    expect(body?.children[1]?.className).toContain('group-upload-modal__column--side');
  });

  it('shows schema controls when mapping is enabled', () => {
    render(
      <GroupUploadDialog
        {...baseProps}
        wantsMap
        dataSourceLabel="team/onboarding/intake-schema-with-a-very-long-file-name-for-layout-checks.xlsx"
      />,
    );

    expect(screen.getByText('Schema file')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'CSV' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Excel' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'JSON' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'TXT' })).toBeTruthy();
    expect(
      screen.getByText('team/onboarding/intake-schema-with-a-very-long-file-name-for-layout-checks.xlsx'),
    ).toBeTruthy();
  });

  it('renders loading status once instead of duplicating the same detail line', () => {
    render(
      <GroupUploadDialog
        {...baseProps}
        items={[
          {
            id: 'pdf-1',
            file: new File(['pdf'], 'packet.pdf', { type: 'application/pdf' }),
            name: 'packet.pdf',
            pageCount: null,
            error: null,
            status: 'loading',
            detail: 'Counting pages…',
            savedFormId: null,
          },
        ]}
      />,
    );

    expect(screen.getAllByText('Counting pages…')).toHaveLength(1);
  });
});
