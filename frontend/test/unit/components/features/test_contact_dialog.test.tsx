import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiError } from '../../../../src/services/apiConfig';
import { ContactDialog } from '../../../../src/components/features/ContactDialog';

const mocks = vi.hoisted(() => ({
  submitContact: vi.fn(),
  loadRecaptcha: vi.fn(),
  getRecaptchaToken: vi.fn(),
  enableRecaptchaBadge: vi.fn(),
  disableRecaptchaBadge: vi.fn(),
}));

vi.mock('../../../../src/services/api', () => ({
  ApiService: {
    submitContact: mocks.submitContact,
  },
}));

vi.mock('../../../../src/utils/recaptcha', () => ({
  loadRecaptcha: mocks.loadRecaptcha,
  getRecaptchaToken: mocks.getRecaptchaToken,
  enableRecaptchaBadge: mocks.enableRecaptchaBadge,
  disableRecaptchaBadge: mocks.disableRecaptchaBadge,
}));

describe('ContactDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
    mocks.submitContact.mockResolvedValue({ success: true });
    mocks.loadRecaptcha.mockResolvedValue(undefined);
    mocks.getRecaptchaToken.mockResolvedValue('token-123');
    vi.stubEnv('VITE_CONTACT_REQUIRE_RECAPTCHA', 'false');
    vi.stubEnv('VITE_RECAPTCHA_SITE_KEY', '');
    document.body.className = '';
  });

  it('resets form state on open and hydrates default email', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(
      <ContactDialog open onClose={onClose} defaultEmail="first@example.com" />,
    );

    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe('first@example.com');
    await user.type(screen.getByLabelText('Short summary'), 'Initial summary');
    await user.type(screen.getByLabelText('Message'), 'Initial message');
    await user.type(screen.getByLabelText('Name'), 'Jane Tester');

    rerender(<ContactDialog open={false} onClose={onClose} defaultEmail="ignored@example.com" />);
    rerender(<ContactDialog open onClose={onClose} defaultEmail="second@example.com" />);

    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe('second@example.com');
    expect((screen.getByLabelText('Short summary') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe('');
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Preferred contact') as HTMLSelectElement).value).toBe('email');
    expect((screen.getByLabelText('Add contact to subject') as HTMLInputElement).checked).toBe(true);
  });

  it('enforces summary/message/contact/recaptcha validation rules', async () => {
    const user = userEvent.setup();
    vi.stubEnv('VITE_CONTACT_REQUIRE_RECAPTCHA', 'true');
    vi.stubEnv('VITE_RECAPTCHA_SITE_KEY', '');

    const { container } = render(<ContactDialog open onClose={vi.fn()} />);
    const form = container.querySelector('form') as HTMLFormElement;

    fireEvent.submit(form);
    expect(screen.getByText('Add a short summary so we can triage quickly.')).toBeTruthy();

    await user.type(screen.getByLabelText('Short summary'), 'Broken form submit');
    fireEvent.submit(form);
    expect(screen.getByText('Add details about the issue or question.')).toBeTruthy();

    await user.type(screen.getByLabelText('Message'), 'Details for support triage.');
    fireEvent.submit(form);
    expect(screen.getByText('Provide at least one contact method (email or phone).')).toBeTruthy();

    await user.type(screen.getByLabelText('Email'), 'contact@example.com');
    fireEvent.submit(form);
    expect(screen.getByText('reCAPTCHA is not configured yet.')).toBeTruthy();
  });

  it('loads recaptcha, requests tokens on submit, and manages badge/body lifecycle', async () => {
    const user = userEvent.setup();
    vi.stubEnv('VITE_CONTACT_REQUIRE_RECAPTCHA', 'true');
    vi.stubEnv('VITE_RECAPTCHA_SITE_KEY', 'site-key-live');
    const onClose = vi.fn();
    const { rerender, unmount } = render(
      <ContactDialog open onClose={onClose} defaultEmail="qa@example.com" />,
    );

    await waitFor(() => {
      expect(mocks.loadRecaptcha).toHaveBeenCalledWith('site-key-live');
    });
    expect(mocks.enableRecaptchaBadge).toHaveBeenCalledWith('contact');
    expect(document.body.classList.contains('recaptcha-contact-open')).toBe(true);

    await user.type(screen.getByLabelText('Short summary'), 'Need help');
    await user.type(screen.getByLabelText('Message'), 'Contact dialog test message');
    await user.type(screen.getByLabelText('Phone'), '+1 555 222 1111');
    await user.selectOptions(screen.getByLabelText('Preferred contact'), 'phone');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => {
      expect(mocks.getRecaptchaToken).toHaveBeenCalledWith('site-key-live', 'contact');
      expect(mocks.submitContact).toHaveBeenCalledTimes(1);
    });

    rerender(<ContactDialog open={false} onClose={onClose} defaultEmail="qa@example.com" />);
    expect(document.body.classList.contains('recaptcha-contact-open')).toBe(false);
    expect(mocks.disableRecaptchaBadge).toHaveBeenCalledWith('contact');

    unmount();
    expect(mocks.disableRecaptchaBadge).toHaveBeenCalledWith('contact');
  });

  it('submits expected payload and transitions through success/send-another state', async () => {
    const user = userEvent.setup();
    vi.stubEnv('VITE_CONTACT_REQUIRE_RECAPTCHA', 'true');
    vi.stubEnv('VITE_RECAPTCHA_SITE_KEY', 'site-key-live');
    mocks.getRecaptchaToken.mockResolvedValue('token-xyz');

    render(<ContactDialog open onClose={vi.fn()} defaultEmail="default@example.com" />);

    await user.selectOptions(screen.getByLabelText('Issue type'), 'question');
    await user.type(screen.getByLabelText('Short summary'), '  Can you help?  ');
    await user.type(screen.getByLabelText('Message'), '  More details here.  ');
    await user.type(screen.getByLabelText('Name'), '  Ada Lovelace  ');
    await user.type(screen.getByLabelText('Company'), '  Analytical Engines Inc  ');
    await user.clear(screen.getByLabelText('Email'));
    await user.type(screen.getByLabelText('Email'), '  ada@example.com  ');
    await user.type(screen.getByLabelText('Phone'), '  +1-555-1111  ');
    await user.selectOptions(screen.getByLabelText('Preferred contact'), 'phone');
    await user.click(screen.getByLabelText('Add contact to subject'));
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => {
      expect(mocks.submitContact).toHaveBeenCalledTimes(1);
    });

    const payload = mocks.submitContact.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.issueType).toBe('question');
    expect(payload.summary).toBe('Can you help?');
    expect(payload.message).toBe('More details here.');
    expect(payload.contactName).toBe('Ada Lovelace');
    expect(payload.contactCompany).toBe('Analytical Engines Inc');
    expect(payload.contactEmail).toBe('ada@example.com');
    expect(payload.contactPhone).toBe('+1-555-1111');
    expect(payload.preferredContact).toBe('phone');
    expect(payload.includeContactInSubject).toBe(false);
    expect(payload.recaptchaToken).toBe('token-xyz');
    expect(payload.recaptchaAction).toBe('contact');
    expect(typeof payload.pageUrl).toBe('string');

    expect(screen.getByText('Message sent. We will reply soon.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Send another' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Send another' }));
    expect(screen.queryByText('Message sent. We will reply soon.')).toBeNull();
    expect((screen.getByLabelText('Short summary') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByRole('button', { name: 'Send message' })).toBeTruthy();
  });

  it('shows ApiError message and generic failure message on unknown errors', async () => {
    const user = userEvent.setup();
    vi.stubEnv('VITE_CONTACT_REQUIRE_RECAPTCHA', 'false');
    const onClose = vi.fn();
    mocks.submitContact.mockRejectedValueOnce(new ApiError('API said no', 400));
    mocks.submitContact.mockRejectedValueOnce(new Error('network broke'));

    render(<ContactDialog open onClose={onClose} defaultEmail="debug@example.com" />);

    await user.type(screen.getByLabelText('Short summary'), 'Summary');
    await user.type(screen.getByLabelText('Message'), 'Detailed content');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => {
      expect(screen.getByText('API said no')).toBeTruthy();
    });

    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => {
      expect(
        screen.getByText('Something went wrong sending your message. Please try again.'),
      ).toBeTruthy();
    });
  });
});
