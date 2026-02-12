import { useEffect, useMemo, useState } from 'react';
import { ApiService, type ContactPayload } from '../../services/api';
import { ApiError } from '../../services/apiConfig';
import {
  disableRecaptchaBadge,
  enableRecaptchaBadge,
  getRecaptchaToken,
  loadRecaptcha,
} from '../../utils/recaptcha';
import { Alert } from '../ui/Alert';
import { Dialog } from '../ui/Dialog';
import './ContactDialog.css';

const ISSUE_OPTIONS = [
  { value: 'bug_report', label: 'Bug report' },
  { value: 'cofounder_inquiry', label: 'Co-founder inquiry' },
  { value: 'question', label: 'Question' },
  { value: 'feature_request', label: 'Feature request' },
  { value: 'partnership', label: 'Partnership' },
  { value: 'other', label: 'Other' },
] as const;

const DEFAULT_ACTION = 'contact';

type ContactDialogProps = {
  open: boolean;
  onClose: () => void;
  defaultEmail?: string | null;
};

export function ContactDialog({ open, onClose, defaultEmail }: ContactDialogProps) {
  const [issueType, setIssueType] = useState<string>('bug_report');
  const [summary, setSummary] = useState('');
  const [message, setMessage] = useState('');
  const [contactName, setContactName] = useState('');
  const [contactCompany, setContactCompany] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [preferredContact, setPreferredContact] = useState('email');
  const [includeContactInSubject, setIncludeContactInSubject] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSent, setIsSent] = useState(false);
  const isLocked = isSubmitting || isSent;

  const recaptchaSiteKey =
    typeof import.meta.env.VITE_RECAPTCHA_SITE_KEY === 'string'
      ? import.meta.env.VITE_RECAPTCHA_SITE_KEY.trim()
      : '';
  const recaptchaRequired = (() => {
    const raw = typeof import.meta.env.VITE_CONTACT_REQUIRE_RECAPTCHA === 'string'
      ? import.meta.env.VITE_CONTACT_REQUIRE_RECAPTCHA.trim().toLowerCase()
      : '';
    if (raw) {
      return !['0', 'false', 'no'].includes(raw);
    }
    return true;
  })();
  const isSubmitDisabled = isSubmitting || (recaptchaRequired && !recaptchaSiteKey);

  useEffect(() => {
    if (!open) return;
    setIssueType('bug_report');
    setSummary('');
    setMessage('');
    setContactName('');
    setContactCompany('');
    setContactEmail(defaultEmail?.trim() || '');
    setContactPhone('');
    setPreferredContact('email');
    setIncludeContactInSubject(true);
    setError(null);
    setIsSubmitting(false);
    setIsSent(false);
  }, [defaultEmail, open]);

  useEffect(() => {
    if (!open || !recaptchaSiteKey) return;
    loadRecaptcha(recaptchaSiteKey).catch(() => {
      if (recaptchaRequired) {
        setError('reCAPTCHA failed to load. Please refresh and try again.');
      }
    });
  }, [open, recaptchaRequired, recaptchaSiteKey]);

  useEffect(() => {
    if (open && recaptchaRequired) {
      enableRecaptchaBadge('contact');
    } else {
      disableRecaptchaBadge('contact');
    }
    return () => {
      disableRecaptchaBadge('contact');
    };
  }, [open, recaptchaRequired]);

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    if (open && recaptchaRequired) {
      document.body.classList.add('recaptcha-contact-open');
    } else {
      document.body.classList.remove('recaptcha-contact-open');
    }
    return () => {
      document.body.classList.remove('recaptcha-contact-open');
    };
  }, [open, recaptchaRequired]);

  const issueLabel = useMemo(
    () => ISSUE_OPTIONS.find((option) => option.value === issueType)?.label ?? 'Contact',
    [issueType],
  );

  const trimmedSummary = summary.trim();
  const trimmedMessage = message.trim();

  const contactToken = useMemo(() => {
    if (preferredContact === 'phone') {
      return contactPhone.trim() || contactEmail.trim();
    }
    return contactEmail.trim() || contactPhone.trim();
  }, [contactEmail, contactPhone, preferredContact]);

  const subjectPreview = useMemo(() => {
    const base = trimmedSummary ? `[DullyPDF][${issueLabel}] ${trimmedSummary}` : `[DullyPDF][${issueLabel}]`;
    if (includeContactInSubject && contactToken) {
      return `${base} | Contact: ${contactToken}`;
    }
    return base;
  }, [contactToken, includeContactInSubject, issueLabel, trimmedSummary]);

  const resetAfterSend = () => {
    setSummary('');
    setMessage('');
    setError(null);
    setIsSent(false);
  };

  const handleSubmit = async () => {
    if (isSubmitting) return;
    if (!trimmedSummary) {
      setError('Add a short summary so we can triage quickly.');
      return;
    }
    if (!trimmedMessage) {
      setError('Add details about the issue or question.');
      return;
    }
    if (!contactEmail.trim() && !contactPhone.trim()) {
      setError('Provide at least one contact method (email or phone).');
      return;
    }
    if (recaptchaRequired && !recaptchaSiteKey) {
      setError('reCAPTCHA is not configured yet.');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      let recaptchaToken: string | undefined;
      if (recaptchaSiteKey) {
        recaptchaToken = await getRecaptchaToken(recaptchaSiteKey, DEFAULT_ACTION);
      }

      const payload: ContactPayload = {
        issueType,
        summary: trimmedSummary,
        message: trimmedMessage,
        contactName: contactName.trim() || undefined,
        contactCompany: contactCompany.trim() || undefined,
        contactEmail: contactEmail.trim() || undefined,
        contactPhone: contactPhone.trim() || undefined,
        preferredContact: preferredContact.trim() || undefined,
        includeContactInSubject,
        recaptchaToken,
        recaptchaAction: DEFAULT_ACTION,
        pageUrl: typeof window !== 'undefined' ? window.location.href : undefined,
      };

      await ApiService.submitContact(payload);
      setIsSent(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('Something went wrong sending your message. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const footer = (
    <div className="contact-dialog__footer">
      {error || isSent ? (
        <div className="contact-dialog__footer-alerts">
          {error ? <Alert tone="error" variant="inline" message={error} /> : null}
          {isSent ? <Alert tone="success" variant="inline" message="Message sent. We will reply soon." /> : null}
        </div>
      ) : null}
      {recaptchaRequired && recaptchaSiteKey ? (
        <div className="contact-dialog__recaptcha-disclaimer">
          Protected by reCAPTCHA Enterprise. Google Privacy Policy and Terms of Service apply.
        </div>
      ) : null}
      <div className="contact-dialog__actions">
        <button className="ui-button ui-button--ghost" type="button" onClick={onClose}>
          Close
        </button>
        {isSent ? (
          <button className="ui-button ui-button--primary" type="button" onClick={resetAfterSend}>
            Send another
          </button>
        ) : (
          <button
            className="ui-button ui-button--primary"
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitDisabled}
          >
            {isSubmitting ? 'Sending...' : 'Send message'}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <Dialog
      open={open}
      title="Contact DullyPDF"
      description="Pick a request type, add details, and we will follow up. Bug reports get a free month of premium."
      onClose={onClose}
      className="contact-dialog"
      footer={footer}
    >
      <form
        className="contact-dialog__form"
        onSubmit={(event) => {
          event.preventDefault();
          handleSubmit();
        }}
      >
        <div className="contact-dialog__main">
          <div className="contact-dialog__grid">
            <label className="contact-dialog__field">
              <span>Issue type</span>
              <select
                className="contact-dialog__input"
                value={issueType}
                onChange={(event) => setIssueType(event.target.value)}
                disabled={isLocked}
              >
                {ISSUE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="contact-dialog__field">
              <span>Short summary</span>
              <input
                className="contact-dialog__input"
                value={summary}
                onChange={(event) => setSummary(event.target.value)}
                placeholder="One-line subject"
                maxLength={160}
                disabled={isLocked}
              />
            </label>

            <label className="contact-dialog__field contact-dialog__field--full">
              <span>Message</span>
              <textarea
                className="contact-dialog__input contact-dialog__textarea"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Give us the details, context, and any links."
                maxLength={4000}
                rows={5}
                disabled={isLocked}
              />
            </label>
          </div>
        </div>

        <div className="contact-dialog__sidebar">
          <div className="contact-dialog__section">
            <div className="contact-dialog__section-title">Contact me</div>
            <div className="contact-dialog__grid">
              <label className="contact-dialog__field">
                <span>Name</span>
                <input
                  className="contact-dialog__input"
                  value={contactName}
                  onChange={(event) => setContactName(event.target.value)}
                  placeholder="Full name"
                  disabled={isLocked}
                />
              </label>
              <label className="contact-dialog__field">
                <span>Company</span>
                <input
                  className="contact-dialog__input"
                  value={contactCompany}
                  onChange={(event) => setContactCompany(event.target.value)}
                  placeholder="Company or org"
                  disabled={isLocked}
                />
              </label>
              <label className="contact-dialog__field">
                <span>Email</span>
                <input
                  type="email"
                  className="contact-dialog__input"
                  value={contactEmail}
                  onChange={(event) => setContactEmail(event.target.value)}
                  placeholder="you@company.com"
                  disabled={isLocked}
                />
              </label>
              <label className="contact-dialog__field">
                <span>Phone</span>
                <input
                  type="tel"
                  className="contact-dialog__input"
                  value={contactPhone}
                  onChange={(event) => setContactPhone(event.target.value)}
                  placeholder="+1 (555) 555-5555"
                  disabled={isLocked}
                />
              </label>
              <label className="contact-dialog__field">
                <span>Preferred contact</span>
                <select
                  className="contact-dialog__input"
                  value={preferredContact}
                  onChange={(event) => setPreferredContact(event.target.value)}
                  disabled={isLocked}
                >
                  <option value="email">Email</option>
                  <option value="phone">Phone</option>
                </select>
              </label>
              <label className="contact-dialog__field contact-dialog__checkbox">
                <span>Add contact to subject</span>
                <input
                  type="checkbox"
                  checked={includeContactInSubject}
                  onChange={(event) => setIncludeContactInSubject(event.target.checked)}
                  disabled={isLocked}
                />
              </label>
            </div>
          </div>

          <div className="contact-dialog__section">
            <div className="contact-dialog__section-title">Email preview</div>
            <div className="contact-dialog__preview">
              <div className="contact-dialog__preview-row">
                <span className="contact-dialog__preview-label">Subject</span>
                <span className="contact-dialog__preview-value">{subjectPreview}</span>
              </div>
              <div className="contact-dialog__preview-row">
                <span className="contact-dialog__preview-label">Body</span>
                <span className="contact-dialog__preview-value">
                  {trimmedMessage || 'Your message will appear here.'}
                </span>
              </div>
            </div>
            {recaptchaSiteKey || !recaptchaRequired ? null : (
              <p className="contact-dialog__recaptcha-note">
                reCAPTCHA is required but not configured for this environment.
              </p>
            )}
          </div>
        </div>
      </form>
    </Dialog>
  );
}
