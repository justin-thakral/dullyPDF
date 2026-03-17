import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { ApiError } from '../../../../src/services/apiConfig';

const apiMocks = vi.hoisted(() => ({
  getPublicFillLink: vi.fn(),
  submitPublicFillLink: vi.fn(),
  downloadPublicFillLinkResponsePdf: vi.fn(),
}));

const recaptchaMocks = vi.hoisted(() => ({
  loadRecaptcha: vi.fn().mockResolvedValue(undefined),
  getRecaptchaToken: vi.fn().mockResolvedValue('recaptcha-token'),
}));

vi.mock('../../../../src/services/api', async () => {
  return {
    ApiService: {
      getPublicFillLink: apiMocks.getPublicFillLink,
      submitPublicFillLink: apiMocks.submitPublicFillLink,
      downloadPublicFillLinkResponsePdf: apiMocks.downloadPublicFillLinkResponsePdf,
    },
  };
});

vi.mock('../../../../src/utils/recaptcha', () => ({
  loadRecaptcha: recaptchaMocks.loadRecaptcha,
  getRecaptchaToken: recaptchaMocks.getRecaptchaToken,
}));

import FillLinkPublicPage from '../../../../src/components/pages/FillLinkPublicPage';

describe('FillLinkPublicPage', () => {
  beforeEach(() => {
    apiMocks.getPublicFillLink.mockReset();
    apiMocks.submitPublicFillLink.mockReset();
    apiMocks.downloadPublicFillLinkResponsePdf.mockReset();
    recaptchaMocks.loadRecaptcha.mockClear();
    recaptchaMocks.getRecaptchaToken.mockClear();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(HTMLAnchorElement.prototype, 'click', {
      configurable: true,
      value: vi.fn(),
    });
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:submitted-pdf'),
      revokeObjectURL: vi.fn(),
    });
  });

  it('loads a public link and submits a respondent response', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: true,
      questions: [
        { key: 'full_name', label: 'Full Name', type: 'text' },
        { key: 'dob', label: 'DOB', type: 'date' },
      ],
    });
    apiMocks.submitPublicFillLink.mockResolvedValue({
      success: true,
      responseId: 'resp-1',
      respondentLabel: 'Ada Lovelace',
      link: {
        status: 'active',
        requireAllFields: true,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text' },
          { key: 'dob', label: 'DOB', type: 'date' },
        ],
      },
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    expect(screen.getByText('A respondent name or ID is required on every submission.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Submit response' }).className).toContain('ui-button--primary');

    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.type(screen.getByLabelText('DOB'), '1990-01-01');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.submitPublicFillLink).toHaveBeenCalledWith('token-1', {
        answers: {
          full_name: 'Ada Lovelace',
          dob: '1990-01-01',
        },
        recaptchaToken: 'recaptcha-token',
        recaptchaAction: 'fill_link_submit',
        attemptId: expect.any(String),
      });
    });

    expect(await screen.findByText('Thanks, Ada Lovelace. Your response was submitted.')).toBeTruthy();
  });

  it('shows a download button only after submit when the template enables respondent PDF copies', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: false,
      allowRespondentPdfDownload: true,
      questions: [
        { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
      ],
    });
    apiMocks.submitPublicFillLink.mockResolvedValue({
      success: true,
      responseId: 'resp-10',
      responseDownloadAvailable: true,
      responseDownloadPath: '/api/fill-links/public/token-1/responses/resp-10/download',
      respondentLabel: 'Ada Lovelace',
      link: {
        status: 'active',
        requireAllFields: false,
        allowRespondentPdfDownload: true,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
        ],
      },
    });
    apiMocks.downloadPublicFillLinkResponsePdf.mockResolvedValue({
      blob: new Blob(['pdf']),
      filename: 'submitted-template.pdf',
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    expect(screen.getByText('PDF copy available after submit')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download submitted PDF' })).toBeNull();

    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    const downloadButton = await screen.findByRole('button', { name: 'Download submitted PDF' });
    expect(downloadButton).toBeTruthy();

    await user.click(downloadButton);

    await waitFor(() => {
      expect(apiMocks.downloadPublicFillLinkResponsePdf).toHaveBeenCalledWith(
        'token-1',
        'resp-10',
        { downloadPath: '/api/fill-links/public/token-1/responses/resp-10/download' },
      );
    });
  });

  it('blocks submission client-side when all fields are required and a question is blank', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: true,
      questions: [
        { key: 'full_name', label: 'Full Name', type: 'text' },
        { key: 'dob', label: 'DOB', type: 'date' },
      ],
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    expect(await screen.findByText('All fields are required. Missing: DOB.')).toBeTruthy();
    expect(apiMocks.submitPublicFillLink).not.toHaveBeenCalled();
  });

  it('blocks submit when no respondent identity field is answered', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: false,
      questions: [
        { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
        { key: 'dob', label: 'DOB', type: 'date' },
      ],
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    expect(await screen.findByText('Enter a respondent name or ID before submitting.')).toBeTruthy();
    expect(apiMocks.submitPublicFillLink).not.toHaveBeenCalled();
  });

  it('does not treat an identity checkbox as a valid respondent name or ID', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: false,
      questions: [
        { key: 'employee_id_confirmed', label: 'Employee ID Confirmed', type: 'boolean', requiredForRespondentIdentity: true },
        { key: 'notes', label: 'Notes', type: 'text' },
      ],
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.click(screen.getByLabelText('Employee ID Confirmed'));
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    expect(await screen.findByText('Enter a respondent name or ID before submitting.')).toBeTruthy();
    expect(apiMocks.submitPublicFillLink).not.toHaveBeenCalled();
  });

  it('allows any one identity field to satisfy the respondent requirement', async () => {
    const user = userEvent.setup();
    const questions = [
      { key: 'first_name', label: 'First Name', type: 'text', requiredForRespondentIdentity: true },
      { key: 'last_name', label: 'Last Name', type: 'text', requiredForRespondentIdentity: true },
      { key: 'dob', label: 'DOB', type: 'date' },
    ];
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: false,
      questions,
    });
    apiMocks.submitPublicFillLink.mockResolvedValue({
      success: true,
      responseId: 'resp-2',
      respondentLabel: 'Ada',
      link: {
        status: 'active',
        requireAllFields: false,
        questions,
      },
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    expect(screen.queryAllByText('Required')).toHaveLength(0);

    await user.type(screen.getByLabelText('First Name'), 'Ada');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.submitPublicFillLink).toHaveBeenCalledWith(
        'token-1',
        expect.objectContaining({
          answers: expect.objectContaining({
            first_name: 'Ada',
          }),
          attemptId: expect.any(String),
        }),
      );
    });

    expect(await screen.findByText('Thanks, Ada. Your response was submitted.')).toBeTruthy();
  });

  it('refreshes the public link after a submit race closes the form', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink
      .mockResolvedValueOnce({
        status: 'active',
        requireAllFields: false,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
        ],
      })
      .mockResolvedValueOnce({
        status: 'closed',
        closedReason: 'response_limit',
        statusMessage: 'This link has reached its response limit.',
        requireAllFields: false,
        questions: [],
      });
    apiMocks.submitPublicFillLink.mockRejectedValue(
      new ApiError('This link has reached its response limit.', 409),
    );

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    expect(await screen.findByText('This form is closed')).toBeTruthy();
    expect(screen.getAllByText('This link has reached its response limit.')).toHaveLength(2);
    expect(apiMocks.getPublicFillLink).toHaveBeenCalledTimes(2);
  });

  it('drops answers for removed questions after a 409 schema refresh before retrying', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink
      .mockResolvedValueOnce({
        status: 'active',
        requireAllFields: false,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
          { key: 'dob', label: 'DOB', type: 'date' },
        ],
      })
      .mockResolvedValueOnce({
        status: 'active',
        requireAllFields: false,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
          { key: 'nickname', label: 'Nickname', type: 'text' },
        ],
      });
    apiMocks.submitPublicFillLink
      .mockRejectedValueOnce(new ApiError('This form changed. Refresh and try again.', 409))
      .mockResolvedValueOnce({
        success: true,
        responseId: 'resp-2',
        respondentLabel: 'Ada Lovelace',
        link: {
          status: 'active',
          requireAllFields: false,
          questions: [
            { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
          ],
        },
      });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.type(screen.getByLabelText('DOB'), '1990-01-01');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.getPublicFillLink).toHaveBeenCalledTimes(2);
    });
    expect(screen.queryByLabelText('DOB')).toBeNull();
    expect((screen.getByLabelText('Full Name') as HTMLInputElement).value).toBe('Ada Lovelace');
    expect((screen.getByLabelText('Nickname') as HTMLInputElement).value).toBe('');

    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.submitPublicFillLink).toHaveBeenLastCalledWith('token-1', {
        answers: {
          full_name: 'Ada Lovelace',
          nickname: '',
        },
        recaptchaToken: 'recaptcha-token',
        recaptchaAction: 'fill_link_submit',
        attemptId: expect.any(String),
      });
    });
  });

  it('drops removed multi-select options after a 409 refresh before retrying', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink
      .mockResolvedValueOnce({
        status: 'active',
        requireAllFields: false,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
          {
            key: 'topics',
            label: 'Topics',
            type: 'multi_select',
            options: [
              { key: 'alpha', label: 'Alpha' },
              { key: 'beta', label: 'Beta' },
            ],
          },
        ],
      })
      .mockResolvedValueOnce({
        status: 'active',
        requireAllFields: false,
        questions: [
          { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
          {
            key: 'topics',
            label: 'Topics',
            type: 'multi_select',
            options: [
              { key: 'alpha', label: 'Alpha' },
            ],
          },
        ],
      });
    apiMocks.submitPublicFillLink
      .mockRejectedValueOnce(new ApiError('This form changed. Refresh and try again.', 409))
      .mockResolvedValueOnce({
        success: true,
        responseId: 'resp-3',
        respondentLabel: 'Ada Lovelace',
        link: {
          status: 'active',
          requireAllFields: false,
          questions: [
            { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
            {
              key: 'topics',
              label: 'Topics',
              type: 'multi_select',
              options: [{ key: 'alpha', label: 'Alpha' }],
            },
          ],
        },
      });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.click(screen.getByLabelText('Alpha'));
    await user.click(screen.getByLabelText('Beta'));
    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.getPublicFillLink).toHaveBeenCalledTimes(2);
    });
    expect(screen.queryByLabelText('Beta')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.submitPublicFillLink).toHaveBeenLastCalledWith(
        'token-1',
        expect.objectContaining({
          answers: {
            full_name: 'Ada Lovelace',
            topics: ['alpha'],
          },
        }),
      );
    });
  });

  it('renders a closed state when the link is no longer active', async () => {
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'closed',
      statusMessage: 'This link is no longer accepting responses.',
    });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByText('This form is closed')).toBeTruthy();
    expect(screen.getByText('This link is no longer accepting responses.')).toBeTruthy();
    expect(screen.queryByText('A respondent name or ID is required on every submission.')).toBeNull();
    expect(screen.queryByText('DullyPDF always requires a respondent name or ID, even when partial answers are allowed.')).toBeNull();
  });

  it('reuses the same submit attempt id when a public submit retry happens without answer changes', async () => {
    const user = userEvent.setup();
    apiMocks.getPublicFillLink.mockResolvedValue({
      status: 'active',
      requireAllFields: false,
      questions: [
        { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
      ],
    });
    apiMocks.submitPublicFillLink
      .mockRejectedValueOnce(new Error('Network lost response.'))
      .mockResolvedValueOnce({
        success: true,
        responseId: 'resp-4',
        respondentLabel: 'Ada Lovelace',
        link: {
          status: 'active',
          requireAllFields: false,
          questions: [
            { key: 'full_name', label: 'Full Name', type: 'text', requiredForRespondentIdentity: true },
          ],
        },
      });

    render(<FillLinkPublicPage token="token-1" />);

    expect(await screen.findByRole('heading', { name: 'Fill out this form' })).toBeTruthy();
    await user.type(screen.getByLabelText('Full Name'), 'Ada Lovelace');
    await user.click(screen.getByRole('button', { name: 'Submit response' }));
    expect(await screen.findByText('Network lost response.')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Submit response' }));

    await waitFor(() => {
      expect(apiMocks.submitPublicFillLink).toHaveBeenCalledTimes(2);
    });

    const firstAttemptId = apiMocks.submitPublicFillLink.mock.calls[0][1]?.attemptId;
    const secondAttemptId = apiMocks.submitPublicFillLink.mock.calls[1][1]?.attemptId;
    expect(firstAttemptId).toEqual(expect.any(String));
    expect(secondAttemptId).toBe(firstAttemptId);
  });
});
