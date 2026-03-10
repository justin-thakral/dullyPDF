import type { ComponentProps } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FillLinkManagerDialog } from '../../../../src/components/features/FillLinkManagerDialog';

describe('FillLinkManagerDialog', () => {
  const baseLimits = {
    detectMaxPages: 10,
    fillableMaxPages: 10,
    savedFormsMax: 10,
    fillLinksActiveMax: 1,
    fillLinkResponsesMax: 1000,
  };

  const buildGroupDialogProps = (overrides: Partial<ComponentProps<typeof FillLinkManagerDialog>> = {}) => {
    const onClose = vi.fn();
    const onPublishTemplate = vi.fn();
    const onRefreshTemplate = vi.fn();
    const onSearchTemplateResponses = vi.fn();
    const onCloseTemplateLink = vi.fn();
    const onApplyTemplateResponse = vi.fn();
    const onUseTemplateResponsesAsSearchFill = vi.fn();
    const onPublishGroup = vi.fn();
    const onRefreshGroup = vi.fn();
    const onSearchGroupResponses = vi.fn();
    const onCloseGroupLink = vi.fn();
    const onApplyGroupResponse = vi.fn();
    const onUseGroupResponsesAsSearchFill = vi.fn();

    return {
      open: true,
      onClose,
      templateName: null,
      hasActiveTemplate: false,
      groupName: 'Hiring Packet',
      hasActiveGroup: true,
      limits: baseLimits,
      templateLink: null,
      templateResponses: [],
      onPublishTemplate,
      onRefreshTemplate,
      onSearchTemplateResponses,
      onCloseTemplateLink,
      onApplyTemplateResponse,
      onUseTemplateResponsesAsSearchFill,
      groupLink: {
        id: 'group-link-1',
        title: 'Hiring Packet',
        status: 'active',
        responseCount: 2,
        maxResponses: 1000,
        publicPath: '/respond/group-link-1',
        requireAllFields: false,
        publishedAt: '2026-03-10T12:00:00.000Z',
      },
      groupResponses: [
        {
          id: 'resp-1',
          linkId: 'group-link-1',
          scopeType: 'group',
          groupId: 'group-1',
          respondentLabel: 'Ada Lovelace',
          respondentSecondaryLabel: 'ada@example.com',
          answers: { full_name: 'Ada Lovelace' },
          submittedAt: '2026-03-10T12:00:00.000Z',
        },
      ],
      onPublishGroup,
      onRefreshGroup,
      onSearchGroupResponses,
      onCloseGroupLink,
      onApplyGroupResponse,
      onUseGroupResponsesAsSearchFill,
      ...overrides,
    } satisfies ComponentProps<typeof FillLinkManagerDialog>;
  };

  const renderGroupDialog = (overrides: Partial<ComponentProps<typeof FillLinkManagerDialog>> = {}) => {
    const props = buildGroupDialogProps(overrides);

    render(
      <FillLinkManagerDialog {...props} />,
    );

    return {
      onRefreshGroup: props.onRefreshGroup,
      onSearchGroupResponses: props.onSearchGroupResponses,
    };
  };

  const renderTemplateDialog = (overrides: Partial<ComponentProps<typeof FillLinkManagerDialog>> = {}) => {
    const props: ComponentProps<typeof FillLinkManagerDialog> = {
      ...buildGroupDialogProps({
        templateName: 'Template One',
        hasActiveTemplate: true,
        templateLink: {
          id: 'template-link-1',
          title: 'Template One Intake',
          status: 'active',
          responseCount: 3,
          maxResponses: 1000,
          publicPath: '/respond/template-link-1',
          requireAllFields: true,
          allowRespondentPdfDownload: true,
          publishedAt: '2026-03-10T12:00:00.000Z',
        },
        templateResponses: [],
        groupName: null,
        hasActiveGroup: false,
        groupLink: null,
        groupResponses: [],
      }),
      ...overrides,
    };

    render(<FillLinkManagerDialog {...props} />);

    return props;
  };

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('does not auto-search group respondents when the dialog opens with an empty query', () => {
    const { onRefreshGroup, onSearchGroupResponses } = renderGroupDialog();

    vi.advanceTimersByTime(300);

    expect(onSearchGroupResponses).not.toHaveBeenCalled();
    expect(onRefreshGroup).not.toHaveBeenCalled();
  });

  it('shows the respondent PDF toggle only for template links and reuses the saved flag state', () => {
    renderTemplateDialog();

    expect(screen.getByText('Allow respondents to download a PDF copy after submit')).toBeTruthy();
    expect(screen.getByText('Download enabled')).toBeTruthy();
    expect(screen.queryByText('Template links only. The download button appears on the success screen after a valid submission.')).toBeTruthy();

    renderGroupDialog();
    expect(screen.queryAllByText('Allow respondents to download a PDF copy after submit')).toHaveLength(1);
  });

  it('passes the respondent PDF toggle state when publishing a template link', () => {
    const onPublishTemplate = vi.fn();
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      onPublishTemplate,
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    const toggles = screen.getAllByRole('checkbox');
    fireEvent.click(toggles[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Publish Template Fill By Link' }));

    expect(onPublishTemplate).toHaveBeenCalledWith({
      requireAllFields: false,
      allowRespondentPdfDownload: true,
    });
  });

  it('searches after typing and keeps manual refresh available for the current query', async () => {
    const { onRefreshGroup, onSearchGroupResponses } = renderGroupDialog();

    const input = screen.getByPlaceholderText('Name, email, phone, or answer');
    fireEvent.change(input, { target: { value: 'ada' } });
    vi.advanceTimersByTime(300);

    expect(onSearchGroupResponses).toHaveBeenLastCalledWith('ada');

    fireEvent.click(screen.getByRole('button', { name: 'Refresh responses' }));
    expect(onRefreshGroup).toHaveBeenLastCalledWith('ada');

    fireEvent.change(input, { target: { value: '' } });
    vi.advanceTimersByTime(300);

    expect(onRefreshGroup).toHaveBeenLastCalledWith();
  });

  it('clears the group respondent query when the dialog closes and reopens', () => {
    const props = buildGroupDialogProps();
    const { rerender } = render(<FillLinkManagerDialog {...props} />);
    const input = screen.getByPlaceholderText('Name, email, phone, or answer');

    fireEvent.change(input, { target: { value: 'ada' } });
    vi.advanceTimersByTime(300);
    expect(props.onSearchGroupResponses).toHaveBeenCalledTimes(1);

    rerender(<FillLinkManagerDialog {...props} open={false} />);
    rerender(<FillLinkManagerDialog {...props} open />);

    const reopenedInput = screen.getByPlaceholderText('Name, email, phone, or answer') as HTMLInputElement;
    expect(reopenedInput.value).toBe('');

    vi.advanceTimersByTime(300);
    expect(props.onSearchGroupResponses).toHaveBeenCalledTimes(1);
    expect(props.onRefreshGroup).not.toHaveBeenCalled();
  });

  it('clears the group respondent query when switching to a different group', () => {
    const props = buildGroupDialogProps();
    const { rerender } = render(<FillLinkManagerDialog {...props} />);
    const input = screen.getByPlaceholderText('Name, email, phone, or answer');

    fireEvent.change(input, { target: { value: 'ada' } });
    vi.advanceTimersByTime(300);
    expect(props.onSearchGroupResponses).toHaveBeenCalledTimes(1);

    rerender(
      <FillLinkManagerDialog
        {...props}
        groupName="Benefits Packet"
        groupLink={{
          id: 'group-link-2',
          title: 'Benefits Packet',
          status: 'active',
          responseCount: 1,
          maxResponses: 1000,
          publicPath: '/respond/group-link-2',
          requireAllFields: false,
          publishedAt: '2026-03-10T12:05:00.000Z',
        }}
        groupResponses={[]}
      />,
    );

    const switchedInput = screen.getByPlaceholderText('Name, email, phone, or answer') as HTMLInputElement;
    expect(switchedInput.value).toBe('');

    vi.advanceTimersByTime(300);
    expect(props.onSearchGroupResponses).toHaveBeenCalledTimes(1);
    expect(props.onRefreshGroup).not.toHaveBeenCalled();
  });

  it('does not re-run the debounced search when callback props change identity after a search', () => {
    const onClose = vi.fn();
    const onPublishTemplate = vi.fn();
    const onRefreshTemplate = vi.fn();
    const onSearchTemplateResponses = vi.fn();
    const onCloseTemplateLink = vi.fn();
    const onApplyTemplateResponse = vi.fn();
    const onUseTemplateResponsesAsSearchFill = vi.fn();
    const onPublishGroup = vi.fn();
    const onRefreshGroup = vi.fn();
    const onSearchGroupResponses = vi.fn();
    const onCloseGroupLink = vi.fn();
    const onApplyGroupResponse = vi.fn();
    const onUseGroupResponsesAsSearchFill = vi.fn();

    const props: ComponentProps<typeof FillLinkManagerDialog> = {
      open: true,
      onClose,
      templateName: null,
      hasActiveTemplate: false,
      groupName: 'Hiring Packet',
      hasActiveGroup: true,
      limits: baseLimits,
      templateLink: null,
      templateResponses: [],
      onPublishTemplate,
      onRefreshTemplate,
      onSearchTemplateResponses,
      onCloseTemplateLink,
      onApplyTemplateResponse,
      onUseTemplateResponsesAsSearchFill,
      groupLink: {
        id: 'group-link-1',
        title: 'Hiring Packet',
        status: 'active',
        responseCount: 2,
        maxResponses: 1000,
        publicPath: '/respond/group-link-1',
        requireAllFields: false,
        publishedAt: '2026-03-10T12:00:00.000Z',
      },
      groupResponses: [
        {
          id: 'resp-1',
          linkId: 'group-link-1',
          scopeType: 'group',
          groupId: 'group-1',
          respondentLabel: 'Ada Lovelace',
          respondentSecondaryLabel: 'ada@example.com',
          answers: { full_name: 'Ada Lovelace' },
          submittedAt: '2026-03-10T12:00:00.000Z',
        },
      ],
      onPublishGroup,
      onRefreshGroup,
      onSearchGroupResponses,
      onCloseGroupLink,
      onApplyGroupResponse,
      onUseGroupResponsesAsSearchFill,
    };

    const { rerender } = render(<FillLinkManagerDialog {...props} />);
    const input = screen.getByPlaceholderText('Name, email, phone, or answer');

    fireEvent.change(input, { target: { value: 'ada' } });
    vi.advanceTimersByTime(300);
    expect(onSearchGroupResponses).toHaveBeenCalledTimes(1);

    const nextOnRefreshGroup = vi.fn();
    const nextOnSearchGroupResponses = vi.fn();
    rerender(
      <FillLinkManagerDialog
        {...props}
        onRefreshGroup={nextOnRefreshGroup}
        onSearchGroupResponses={nextOnSearchGroupResponses}
      />,
    );

    vi.advanceTimersByTime(300);
    expect(nextOnSearchGroupResponses).not.toHaveBeenCalled();
    expect(nextOnRefreshGroup).not.toHaveBeenCalled();
  });
});
