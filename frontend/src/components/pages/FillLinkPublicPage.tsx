import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiService,
  type FillLinkQuestion,
  type FillLinkSummary,
  type PublicFillLinkSubmitResult,
} from '../../services/api';
import { ApiError } from '../../services/apiConfig';
import {
  fillLinkRespondentPdfDownloadEnabled,
  fillLinkResponseDownloadEnabled,
} from '../../utils/fillLinks';
import { getRecaptchaToken, loadRecaptcha } from '../../utils/recaptcha';
import { Alert } from '../ui/Alert';
import '../../styles/ui-buttons.css';
import './FillLinkPublicPage.css';

type FillLinkPublicPageProps = {
  token: string;
};

function isRecaptchaRequired(): boolean {
  const raw = typeof import.meta.env.VITE_FILL_LINK_REQUIRE_RECAPTCHA === 'string'
    ? import.meta.env.VITE_FILL_LINK_REQUIRE_RECAPTCHA.trim().toLowerCase()
    : '';
  if (raw) {
    return !['0', 'false', 'no'].includes(raw);
  }
  return true;
}

function getRecaptchaSiteKey(): string {
  return typeof import.meta.env.VITE_RECAPTCHA_SITE_KEY === 'string'
    ? import.meta.env.VITE_RECAPTCHA_SITE_KEY.trim()
    : '';
}

function toFieldValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

function buildFillLinkSubmitAttemptId(): string {
  const cryptoApi =
    typeof globalThis !== 'undefined' && typeof globalThis.crypto !== 'undefined'
      ? globalThis.crypto
      : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  const randomSuffix = Math.random().toString(36).slice(2, 12);
  return `fill_link_${Date.now()}_${randomSuffix}`;
}

function isLinkClosed(link: FillLinkSummary | null): boolean {
  if (!link) return false;
  return link.status !== 'active';
}

function renderQuestionLabel(question: FillLinkQuestion): string {
  return question.label || question.key;
}

function isQuestionRequired(link: FillLinkSummary | null): boolean {
  return Boolean(link?.requireAllFields);
}

function seedAnswers(questions: FillLinkQuestion[] | undefined): Record<string, unknown> {
  const seededAnswers: Record<string, unknown> = {};
  for (const question of questions || []) {
    if (question.type === 'multi_select') {
      seededAnswers[question.key] = [];
    } else if (question.type === 'boolean') {
      seededAnswers[question.key] = false;
    } else {
      seededAnswers[question.key] = '';
    }
  }
  return seededAnswers;
}

function sanitizeAnswerForQuestion(question: FillLinkQuestion, value: unknown): unknown {
  if (question.type === 'boolean') {
    return typeof value === 'boolean' ? value : false;
  }
  if (question.type === 'multi_select') {
    if (!Array.isArray(value)) return [];
    const normalized = value.map((entry) => String(entry ?? '').trim()).filter(Boolean);
    const allowed = new Set((question.options || []).map((option) => option.key).filter(Boolean));
    if (!allowed.size) return normalized;
    return normalized.filter((entry) => allowed.has(entry));
  }
  if (question.type === 'radio') {
    const normalized = String(value ?? '').trim();
    if (!normalized) return '';
    const allowed = new Set((question.options || []).map((option) => option.key).filter(Boolean));
    if (allowed.size && !allowed.has(normalized)) return '';
    return normalized;
  }
  return value;
}

function reconcileAnswers(
  questions: FillLinkQuestion[] | undefined,
  previous: Record<string, unknown>,
): Record<string, unknown> {
  const nextAnswers = seedAnswers(questions);
  for (const question of questions || []) {
    if (!(question.key in previous)) continue;
    nextAnswers[question.key] = sanitizeAnswerForQuestion(question, previous[question.key]);
  }
  return nextAnswers;
}

function isQuestionAnswered(question: FillLinkQuestion, value: unknown): boolean {
  if (question.type === 'boolean') {
    return typeof value === 'boolean';
  }
  if (question.type === 'multi_select') {
    return Array.isArray(value) && value.length > 0;
  }
  if (Array.isArray(value)) {
    return value.some((entry) => String(entry ?? '').trim().length > 0);
  }
  return String(value ?? '').trim().length > 0;
}

function listMissingRequiredQuestionLabels(
  link: FillLinkSummary | null,
  questions: FillLinkQuestion[] | undefined,
  answers: Record<string, unknown>,
): string[] {
  const missing: string[] = [];
  for (const question of questions || []) {
    if (!isQuestionRequired(link)) continue;
    if (isQuestionAnswered(question, answers[question.key])) continue;
    missing.push(renderQuestionLabel(question));
  }
  return missing;
}

function hasRespondentIdentityAnswer(
  questions: FillLinkQuestion[] | undefined,
  answers: Record<string, unknown>,
): boolean {
  for (const question of questions || []) {
    if (!question.requiredForRespondentIdentity) continue;
    if (question.type === 'boolean') continue;
    if (isQuestionAnswered(question, answers[question.key])) {
      return true;
    }
  }
  return false;
}

function formatMissingRequiredQuestionMessage(labels: string[]): string {
  if (!labels.length) return 'All fields are required for this form.';
  if (labels.length <= 3) {
    return `All fields are required. Missing: ${labels.join(', ')}.`;
  }
  return `All fields are required. Missing: ${labels.slice(0, 3).join(', ')}, and ${labels.length - 3} more.`;
}

export default function FillLinkPublicPage({ token }: FillLinkPublicPageProps) {
  const [link, setLink] = useState<FillLinkSummary | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [downloadInProgress, setDownloadInProgress] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submittedResponseId, setSubmittedResponseId] = useState<string | null>(null);
  const [submittedDownloadPath, setSubmittedDownloadPath] = useState<string | null>(null);
  const [submittedDownloadAvailable, setSubmittedDownloadAvailable] = useState(false);
  const alertRef = useRef<HTMLDivElement | null>(null);
  const submitAttemptIdRef = useRef<string | null>(null);

  const recaptchaSiteKey = useMemo(getRecaptchaSiteKey, []);
  const recaptchaRequired = useMemo(isRecaptchaRequired, []);
  const linkClosed = isLinkClosed(link);
  const respondentPdfDownloadAvailable = fillLinkRespondentPdfDownloadEnabled(link);
  const canDownloadSubmittedPdf = Boolean(
    submittedDownloadAvailable
    && (submittedResponseId || submittedDownloadPath),
  );

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);
    setSuccess(null);
    setSubmittedResponseId(null);
    setSubmittedDownloadPath(null);
    setSubmittedDownloadAvailable(false);
    ApiService.getPublicFillLink(token)
      .then((payload) => {
        if (!isMounted) return;
        setLink(payload);
        setAnswers(seedAnswers(payload.questions));
        submitAttemptIdRef.current = null;
      })
      .catch((nextError) => {
        if (!isMounted) return;
        setError(nextError instanceof Error ? nextError.message : 'Unable to load this Fill By Link.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [token]);

  useEffect(() => {
    if (!recaptchaRequired || !recaptchaSiteKey) return;
    loadRecaptcha(recaptchaSiteKey).catch(() => {});
  }, [recaptchaRequired, recaptchaSiteKey]);

  useEffect(() => {
    if (!error && !success) return;
    if (typeof window === 'undefined') return;
    const scrollToAlert = () => {
      alertRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(scrollToAlert);
      return;
    }
    scrollToAlert();
  }, [error, success]);

  const clearSubmitFeedback = useCallback(() => {
    setSuccess(null);
    setSubmittedResponseId(null);
    setSubmittedDownloadPath(null);
    setSubmittedDownloadAvailable(false);
  }, []);

  const handleAnswerChange = (question: FillLinkQuestion, value: unknown) => {
    clearSubmitFeedback();
    submitAttemptIdRef.current = null;
    setAnswers((prev) => ({
      ...prev,
      [question.key]: value,
    }));
  };

  const handleMultiSelectChange = (question: FillLinkQuestion, optionKey: string, checked: boolean) => {
    clearSubmitFeedback();
    submitAttemptIdRef.current = null;
    setAnswers((prev) => {
      const existing = Array.isArray(prev[question.key]) ? prev[question.key] as string[] : [];
      const next = checked
        ? Array.from(new Set([...existing, optionKey]))
        : existing.filter((entry) => entry !== optionKey);
      return {
        ...prev,
        [question.key]: next,
      };
    });
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!link) return;
    setError(null);
    clearSubmitFeedback();
    {
      if (link.requireAllFields) {
        const missingLabels = listMissingRequiredQuestionLabels(link, link.questions, answers);
        if (missingLabels.length > 0) {
          setError(formatMissingRequiredQuestionMessage(missingLabels));
          return;
        }
      } else if (!hasRespondentIdentityAnswer(link.questions, answers)) {
        setError('Enter a respondent name or ID before submitting.');
        return;
      }
    }
    setSubmitting(true);
    try {
      const attemptId = submitAttemptIdRef.current || buildFillLinkSubmitAttemptId();
      submitAttemptIdRef.current = attemptId;
      let recaptchaToken: string | undefined;
      if (recaptchaRequired) {
        if (!recaptchaSiteKey) {
          throw new Error('reCAPTCHA is not configured for this form.');
        }
        recaptchaToken = await getRecaptchaToken(recaptchaSiteKey, 'fill_link_submit');
      }
      const payload = await ApiService.submitPublicFillLink(token, {
        answers,
        recaptchaToken,
        recaptchaAction: 'fill_link_submit',
        attemptId,
      });
      const submitResult = payload as PublicFillLinkSubmitResult;
      setLink(payload.link);
      setAnswers(seedAnswers(payload.link.questions));
      submitAttemptIdRef.current = null;
      setSubmittedResponseId(payload.responseId ?? null);
      setSubmittedDownloadPath(submitResult.responseDownloadPath?.trim() || null);
      setSubmittedDownloadAvailable(fillLinkResponseDownloadEnabled(submitResult));
      setSuccess(payload.respondentLabel ? `Thanks, ${payload.respondentLabel}. Your response was submitted.` : 'Your response was submitted.');
    } catch (submitError) {
      if (submitError instanceof ApiError && submitError.status === 409) {
        try {
          const latestLink = await ApiService.getPublicFillLink(token);
          setLink(latestLink);
          setAnswers((prev) => reconcileAnswers(latestLink.questions, prev));
          submitAttemptIdRef.current = null;
        } catch {
          // Best-effort recovery only. The original submit error remains visible.
        }
      }
      setError(submitError instanceof Error ? submitError.message : 'Unable to submit this response.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDownloadSubmittedPdf = useCallback(async () => {
    if (!canDownloadSubmittedPdf || !token || (!submittedResponseId && !submittedDownloadPath)) {
      return;
    }
    const resolvedResponseId = submittedResponseId || 'response';
    setDownloadInProgress(true);
    setError(null);
    try {
      const { blob, filename } = await ApiService.downloadPublicFillLinkResponsePdf(
        token,
        resolvedResponseId,
        { downloadPath: submittedDownloadPath },
      );
      const objectUrl = URL.createObjectURL(blob);
      const linkNode = document.createElement('a');
      linkNode.href = objectUrl;
      linkNode.download = filename || `submitted-${resolvedResponseId}.pdf`;
      document.body.append(linkNode);
      linkNode.click();
      linkNode.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : 'Unable to download the submitted PDF.');
    } finally {
      setDownloadInProgress(false);
    }
  }, [canDownloadSubmittedPdf, submittedDownloadPath, submittedResponseId, token]);

  return (
    <div className="fill-link-public-page">
      <div className="fill-link-public-page__shell">
        <div className="fill-link-public-page__hero">
          <div className="fill-link-public-page__brand-row">
            <div>
              <p className="fill-link-public-page__eyebrow">DullyPDF Fill By Link</p>
              <h1>Fill out this form</h1>
            </div>
            <span className="fill-link-public-page__hero-badge">
              Mobile-friendly respondent form
            </span>
          </div>
          <p className="fill-link-public-page__summary">
            {respondentPdfDownloadAvailable
              ? 'Complete this DullyPDF-hosted form. If the owner enabled it, you can download a PDF copy after you submit.'
              : 'Complete this DullyPDF-hosted form. The owner will review your answers in the workspace and generate the final PDF later.'}
          </p>
          {!linkClosed ? (
            <div className="fill-link-public-page__hero-meta">
              <span>A respondent name or ID is required on every submission.</span>
              {link?.requireAllFields ? <span>Every question must be answered</span> : null}
              {respondentPdfDownloadAvailable ? <span>PDF copy available after submit</span> : null}
            </div>
          ) : null}
        </div>

        <div className="fill-link-public-page__card">
          {loading ? (
            <p className="fill-link-public-page__status">Loading form…</p>
          ) : null}
          <div ref={alertRef} className="fill-link-public-page__alerts">
            {error ? (
              <Alert
                tone="error"
                variant="inline"
                message={error}
                onDismiss={() => setError(null)}
              />
            ) : null}
            {success ? (
              <Alert
                tone="success"
                variant="inline"
                message={success}
                onDismiss={() => setSuccess(null)}
              />
            ) : null}
          </div>

        {canDownloadSubmittedPdf ? (
          <section className="fill-link-public-page__post-submit" aria-label="Submitted PDF download">
            <div className="fill-link-public-page__post-submit-copy">
              <h2>Download your submitted PDF</h2>
              <p>Keep a copy of the template you just submitted. The owner still keeps the stored response in DullyPDF.</p>
            </div>
            <button
              type="button"
              className="ui-button ui-button--primary fill-link-public-page__download"
              onClick={handleDownloadSubmittedPdf}
              disabled={downloadInProgress}
            >
              {downloadInProgress ? 'Preparing download…' : 'Download submitted PDF'}
            </button>
          </section>
        ) : null}

        {link && !loading ? (
          <>
            {!linkClosed ? (
              link.requireAllFields ? (
                <div className="fill-link-public-page__required-note">
                  Every question on this form must be answered before DullyPDF accepts the submission.
                </div>
              ) : (
                <div className="fill-link-public-page__required-note">
                  DullyPDF always requires a respondent name or ID, even when partial answers are allowed.
                </div>
              )
            ) : null}

            {linkClosed ? (
              <div className="fill-link-public-page__closed">
                <h2>This form is closed</h2>
                <p>{link.statusMessage || (link.closedReason === 'response_limit' ? 'This link already reached its response limit.' : 'This link is no longer accepting responses.')}</p>
              </div>
            ) : (
              <form className="fill-link-public-page__form" onSubmit={handleSubmit}>
                {(link.questions || []).map((question) => (
                  <label key={question.key} className="fill-link-public-page__field">
                    <span className="fill-link-public-page__field-label">
                      {renderQuestionLabel(question)}
                      {isQuestionRequired(link) ? <em>Required</em> : null}
                    </span>
                    {question.type === 'date' ? (
                      <input
                        type="date"
                        aria-label={renderQuestionLabel(question)}
                        aria-required={isQuestionRequired(link)}
                        value={toFieldValue(answers[question.key])}
                        onChange={(event) => handleAnswerChange(question, event.target.value)}
                      />
                    ) : question.type === 'boolean' ? (
                      <div className="fill-link-public-page__boolean">
                        <input
                          type="checkbox"
                          aria-label={renderQuestionLabel(question)}
                          checked={Boolean(answers[question.key])}
                          onChange={(event) => handleAnswerChange(question, event.target.checked)}
                        />
                        <span>Check if yes</span>
                      </div>
                    ) : question.type === 'radio' ? (
                      <div className="fill-link-public-page__options">
                        {(question.options || []).map((option) => (
                          <label key={option.key} className="fill-link-public-page__option">
                            <input
                              type="radio"
                              name={question.key}
                              aria-required={isQuestionRequired(link)}
                              checked={answers[question.key] === option.key}
                              onChange={() => handleAnswerChange(question, option.key)}
                            />
                            <span>{option.label}</span>
                          </label>
                        ))}
                      </div>
                    ) : question.type === 'multi_select' ? (
                      <div className="fill-link-public-page__options">
                        {(question.options || []).map((option) => (
                          <label key={option.key} className="fill-link-public-page__option">
                            <input
                              type="checkbox"
                              checked={Array.isArray(answers[question.key]) && (answers[question.key] as string[]).includes(option.key)}
                              onChange={(event) => handleMultiSelectChange(question, option.key, event.target.checked)}
                            />
                            <span>{option.label}</span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <input
                        type="text"
                        aria-label={renderQuestionLabel(question)}
                        aria-required={isQuestionRequired(link)}
                        value={toFieldValue(answers[question.key])}
                        onChange={(event) => handleAnswerChange(question, event.target.value)}
                      />
                    )}
                  </label>
                ))}

                <button className="ui-button ui-button--primary fill-link-public-page__submit" type="submit" disabled={submitting}>
                  {submitting ? 'Submitting…' : 'Submit response'}
                </button>
              </form>
            )}
          </>
        ) : null}
        </div>
      </div>
    </div>
  );
}
