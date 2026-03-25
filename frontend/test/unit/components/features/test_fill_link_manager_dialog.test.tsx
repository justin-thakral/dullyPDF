import type { ComponentProps } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FillLinkManagerDialog } from '../../../../src/components/features/FillLinkManagerDialog';
import { ApiService } from '../../../../src/services/api';

describe('FillLinkManagerDialog', () => {
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
          respondentPdfEditableEnabled: false,
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
    vi.stubGlobal('open', vi.fn());
    window.open = vi.fn() as unknown as typeof window.open;
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

    const respondentPdfToggle = screen.getByRole('checkbox', { name: /allow pdf download/i }) as HTMLInputElement;

    expect(respondentPdfToggle).toBeTruthy();
    expect(respondentPdfToggle.checked).toBe(true);
    expect(screen.queryByText('Respondents can download a flat PDF after submit.')).toBeTruthy();

    renderGroupDialog();
    expect(screen.queryAllByRole('checkbox', { name: /allow pdf download/i })).toHaveLength(1);
  });

  it('shows the editable respondent PDF toggle disabled until PDF downloads are enabled', () => {
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    const editableToggle = screen.getByRole('checkbox', { name: /download editable pdf/i }) as HTMLInputElement;
    expect(editableToggle.disabled).toBe(true);

    fireEvent.click(screen.getByRole('checkbox', { name: /allow pdf download/i }));
    expect(editableToggle.disabled).toBe(false);
  });

  it('forces respondent downloads to stay flat when post-submit signing is enabled', () => {
    const onPublishTemplate = vi.fn();
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      onPublishTemplate,
      templateSourceQuestions: [
        { key: 'full_name', label: 'Full Name', type: 'text', sourceType: 'pdf_field', visible: true },
        { key: 'email', label: 'Email', type: 'email', sourceType: 'custom', visible: true },
      ],
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /allow pdf download/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /download editable pdf/i }));
    expect((screen.getByRole('checkbox', { name: /download editable pdf/i }) as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByRole('checkbox', { name: /require signature/i }));

    const editableToggle = screen.getByRole('checkbox', { name: /download editable pdf/i }) as HTMLInputElement;
    expect(editableToggle.checked).toBe(false);
    expect(editableToggle.disabled).toBe(true);
    expect(screen.getByText('Signed flows always stay flat.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Publish link' }));
    expect(onPublishTemplate).toHaveBeenCalledWith(expect.objectContaining({
      allowRespondentEditablePdfDownload: false,
    }));
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
    fireEvent.click(screen.getByRole('checkbox', { name: /allow pdf download/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /download editable pdf/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Publish link' }));

    expect(onPublishTemplate).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Template One',
      requireAllFields: false,
      allowRespondentPdfDownload: true,
      allowRespondentEditablePdfDownload: true,
      webFormConfig: expect.objectContaining({
        schemaVersion: 2,
      }),
    }));
  });

  it('passes post-submit signing config when publishing a template link', () => {
    const onPublishTemplate = vi.fn();
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      onPublishTemplate,
      templateSourceQuestions: [
        { key: 'full_name', label: 'Full Name', type: 'text', sourceType: 'pdf_field', visible: true },
        { key: 'email', label: 'Email', type: 'email', sourceType: 'custom', visible: true },
      ],
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /require signature/i }));
    fireEvent.change(screen.getByLabelText('Signature mode'), { target: { value: 'consumer' } });
    fireEvent.change(screen.getByLabelText('Signer name question'), { target: { value: 'full_name' } });
    fireEvent.change(screen.getByLabelText('Signer email question'), { target: { value: 'email' } });
    fireEvent.click(screen.getByRole('button', { name: 'Publish link' }));

    expect(onPublishTemplate).toHaveBeenCalledWith(expect.objectContaining({
      signingConfig: {
        enabled: true,
        signatureMode: 'consumer',
        documentCategory: 'ordinary_business_form',
        manualFallbackEnabled: true,
        signerNameQuestionKey: 'full_name',
        signerEmailQuestionKey: 'email',
      },
    }));
  });

  it('defaults the signer email mapping to the email question and hides signature fields from the public preview', () => {
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      templateSourceQuestions: [
        { key: 'full_name', label: 'Full Name', type: 'text', sourceType: 'pdf_field', visible: true },
        { key: 'email', label: 'Email', type: 'text', sourceType: 'pdf_field', visible: true },
        { key: 'signature', label: 'Signature', type: 'text', sourceType: 'pdf_field', visible: true },
      ],
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /require signature/i }));

    const signerEmailSelect = screen.getByLabelText('Signer email question') as HTMLSelectElement;
    expect(signerEmailSelect.value).toBe('email');

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(screen.queryByRole('textbox', { name: 'Signature' })).toBeNull();
    expect(screen.getByRole('textbox', { name: 'Full Name' })).toBeTruthy();
  });

  it('reveals post-submit signing settings when the signing toggle is enabled', () => {
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      templateSourceQuestions: [
        { key: 'full_name', label: 'Full Name', type: 'text', sourceType: 'pdf_field', visible: true },
        { key: 'email', label: 'Email', type: 'email', sourceType: 'custom', visible: true },
      ],
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    const toggle = screen.getByRole('checkbox', { name: /require signature/i }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(screen.queryByRole('heading', { name: 'Post-submit signing' })).toBeNull();

    fireEvent.click(toggle);

    expect(toggle.checked).toBe(true);
    expect(screen.getByRole('heading', { name: 'Post-submit signing' })).toBeTruthy();
  });

  it('auto-adds a signer email question when post-submit signing is enabled without one', () => {
    const onPublishTemplate = vi.fn();
    renderTemplateDialog({
      templateLink: null,
      templateResponses: [],
      onPublishTemplate,
      templateSourceQuestions: [
        { key: 'full_name', label: 'Full Name', type: 'text', sourceType: 'pdf_field', visible: true },
        { key: 'company', label: 'Company', type: 'text', sourceType: 'pdf_field', visible: true },
      ],
      groupName: null,
      hasActiveGroup: false,
      groupLink: null,
      groupResponses: [],
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /require signature/i }));

    const signerEmailSelect = screen.getByLabelText('Signer email question') as HTMLSelectElement;
    expect(signerEmailSelect.disabled).toBe(false);
    expect(Array.from(signerEmailSelect.options).some((option) => option.textContent === 'Signer Email')).toBe(true);
    expect(signerEmailSelect.value).toBe('signer_email');

    fireEvent.click(screen.getByRole('button', { name: 'Publish link' }));
    expect(onPublishTemplate).toHaveBeenCalledWith(expect.objectContaining({
      signingConfig: expect.objectContaining({
        enabled: true,
        signerEmailQuestionKey: 'signer_email',
      }),
      webFormConfig: expect.objectContaining({
        questions: expect.arrayContaining([
          expect.objectContaining({
            key: 'signer_email',
            type: 'email',
            required: true,
          }),
        ]),
      }),
    }));
  });

  it('shows signed-form downloads in the responses tab when a linked signing request is complete', () => {
    const downloadSpy = vi.spyOn(ApiService, 'downloadAuthenticatedFile').mockResolvedValue(undefined);
    renderTemplateDialog({
      templateResponses: [
        {
          id: 'resp-signed-1',
          linkId: 'template-link-1',
          scopeType: 'template',
          templateId: 'tpl-1',
          respondentLabel: 'Ada Lovelace',
          respondentSecondaryLabel: 'ada@example.com',
          answers: { full_name: 'Ada Lovelace' },
          submittedAt: '2026-03-10T12:00:00.000Z',
          signingRequestId: 'sign-1',
          signingStatus: 'completed',
          signingCompletedAt: '2026-03-10T12:15:00.000Z',
          linkedSigning: {
            requestId: 'sign-1',
            status: 'completed',
            completedAt: '2026-03-10T12:15:00.000Z',
            artifacts: {
              signedPdf: { available: true, downloadPath: '/api/signing/requests/sign-1/artifacts/signed_pdf' },
              auditReceipt: { available: true, downloadPath: '/api/signing/requests/sign-1/artifacts/audit_receipt' },
            },
          },
        },
      ],
    });

    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));

    expect(screen.getByText('Signed')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Download signed PDF' }));
    expect(downloadSpy).toHaveBeenCalledWith(
      '/api/signing/requests/sign-1/artifacts/signed_pdf',
      expect.objectContaining({ filename: 'Ada Lovelace-signed.pdf' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Audit receipt' }));
    expect(downloadSpy).toHaveBeenCalledWith(
      '/api/signing/requests/sign-1/artifacts/audit_receipt',
      expect.objectContaining({ filename: 'Ada Lovelace-audit-receipt.pdf' }),
    );
  });

  it('searches after typing and keeps manual refresh available for the current query', async () => {
    const { onRefreshGroup, onSearchGroupResponses } = renderGroupDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));

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
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));
    const input = screen.getByPlaceholderText('Name, email, phone, or answer');

    fireEvent.change(input, { target: { value: 'ada' } });
    vi.advanceTimersByTime(300);
    expect(props.onSearchGroupResponses).toHaveBeenCalledTimes(1);

    rerender(<FillLinkManagerDialog {...props} open={false} />);
    rerender(<FillLinkManagerDialog {...props} open />);
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));

    const reopenedInput = screen.getByPlaceholderText('Name, email, phone, or answer') as HTMLInputElement;
    expect(reopenedInput.value).toBe('');

    vi.advanceTimersByTime(300);
    expect(props.onSearchGroupResponses).toHaveBeenCalledTimes(1);
    expect(props.onRefreshGroup).not.toHaveBeenCalled();
  });

  it('clears the group respondent query when switching to a different group', () => {
    const props = buildGroupDialogProps();
    const { rerender } = render(<FillLinkManagerDialog {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));
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
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));

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
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));
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
    fireEvent.click(screen.getByRole('button', { name: 'Responses' }));

    vi.advanceTimersByTime(300);
    expect(nextOnSearchGroupResponses).not.toHaveBeenCalled();
    expect(nextOnRefreshGroup).not.toHaveBeenCalled();
  });

  it('closes the open field details when the same field row is clicked again', () => {
    renderGroupDialog({
      groupSourceQuestions: [
        {
          key: 'respondent_identifier',
          label: 'Respondent name or ID',
          type: 'text',
          sourceType: 'synthetic',
          required: true,
          requiredForRespondentIdentity: true,
          synthetic: true,
          order: 0,
        },
      ],
    });

    expect(screen.getByDisplayValue('Respondent Name or ID')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Respondent name or ID/i }));

    expect(screen.queryByDisplayValue('Respondent Name or ID')).toBeNull();
  });
});
