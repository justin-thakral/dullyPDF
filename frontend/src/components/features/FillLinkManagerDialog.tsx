import { useEffect, useMemo, useRef, useState } from 'react';
import { Dialog } from '../ui/Dialog';
import { ApiService } from '../../services/api';
import type {
  FillLinkQuestion,
  FillLinkResponse,
  FillLinkSigningConfig,
  FillLinkSummary,
  FillLinkWebFormConfig,
} from '../../services/api';
import {
  buildFallbackFillLinkWebFormConfigFromPublishedQuestions,
  buildFillLinkWebFormConfig,
  buildPublishedFillLinkQuestions,
  createCustomFillLinkQuestion,
  fillLinkQuestionIsSigningCeremonyManaged,
  fillLinkQuestionLooksLikeEmail,
  fillLinkQuestionIsBoolean,
  fillLinkQuestionSupportsOptions,
  fillLinkQuestionSupportsTextLimit,
  normalizeFillLinkQuestionType,
  sortFillLinkQuestions,
  validateFillLinkWebForm,
} from '../../utils/fillLinkWebForm';
import {
  fillLinkRespondentPdfDownloadEnabled,
  fillLinkRespondentPdfEditableEnabled,
} from '../../utils/fillLinks';
import './FillLinkManagerDialog.css';

export type FillLinkPublishOptions = {
  title?: string;
  requireAllFields?: boolean;
  allowRespondentPdfDownload?: boolean;
  allowRespondentEditablePdfDownload?: boolean;
  webFormConfig?: FillLinkWebFormConfig;
  signingConfig?: FillLinkSigningConfig;
};

export type FillLinkManagerDialogProps = {
  open: boolean;
  onClose: () => void;
  templateName: string | null;
  hasActiveTemplate: boolean;
  templateSourceQuestions?: FillLinkQuestion[];
  templateBuilderLoading?: boolean;
  groupName: string | null;
  hasActiveGroup: boolean;
  groupSourceQuestions?: FillLinkQuestion[];
  groupBuilderLoading?: boolean;
  templateLink: FillLinkSummary | null;
  templateResponses: FillLinkResponse[];
  templateLoadingLink?: boolean;
  templatePublishing?: boolean;
  templateClosing?: boolean;
  templateLoadingResponses?: boolean;
  templateError?: string | null;
  onPublishTemplate: (options?: FillLinkPublishOptions) => void;
  onRefreshTemplate: (search?: string) => void;
  onSearchTemplateResponses: (search: string) => void;
  onCloseTemplateLink: (options?: FillLinkPublishOptions) => void;
  onApplyTemplateResponse: (response: FillLinkResponse) => void;
  onUseTemplateResponsesAsSearchFill: () => void;
  groupLink: FillLinkSummary | null;
  groupResponses: FillLinkResponse[];
  groupLoadingLink?: boolean;
  groupPublishing?: boolean;
  groupClosing?: boolean;
  groupLoadingResponses?: boolean;
  groupError?: string | null;
  onPublishGroup: (options?: FillLinkPublishOptions) => void;
  onRefreshGroup: (search?: string) => void;
  onSearchGroupResponses: (search: string) => void;
  onCloseGroupLink: (options?: FillLinkPublishOptions) => void;
  onApplyGroupResponse: (response: FillLinkResponse) => void;
  onUseGroupResponsesAsSearchFill: () => void;
};

type ScopeKind = 'template' | 'group';
type ScopeTab = 'builder' | 'preview' | 'responses';
type QuestionFilter = 'all' | 'linked' | 'custom' | 'required';

type FillLinkScopePanelProps = {
  open: boolean;
  onClose: () => void;
  kind: ScopeKind;
  heading: string;
  scopeName: string | null;
  sourceQuestions: FillLinkQuestion[];
  sourceLoading: boolean;
  allowCustomQuestions: boolean;
  showRespondentPdfDownloadToggle?: boolean;
  link: FillLinkSummary | null;
  responses: FillLinkResponse[];
  loadingLink: boolean;
  publishing: boolean;
  closing: boolean;
  loadingResponses: boolean;
  error: string | null;
  onPublish: (options?: FillLinkPublishOptions) => void;
  onRefresh: (search?: string) => void;
  onSearchResponses: (search: string) => void;
  onCloseLink: (options?: FillLinkPublishOptions) => void;
  onApplyResponse: (response: FillLinkResponse) => void;
  onUseResponsesAsSearchFill: () => void;
};

function formatDateLabel(value?: string | null): string {
  if (!value) return 'Unknown date';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Unknown date';
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function resolveResponseSigningLabel(response: FillLinkResponse): string | null {
  const linked = response.linkedSigning;
  if (!linked?.status) return null;
  if (linked.manualFallbackRequestedAt) return 'Manual fallback';
  if (linked.status === 'completed') return 'Signed';
  if (linked.inviteDeliveryStatus === 'failed') return 'Signing email failed';
  if (linked.inviteDeliveryStatus === 'skipped') return 'Signing email unavailable';
  if (linked.inviteDeliveryStatus === 'sent') return 'Invite emailed';
  if (linked.status === 'sent') return 'Waiting for signature';
  if (linked.status === 'invalidated') return 'Signing invalidated';
  return 'Signing prepared';
}

function resolvePublicUrl(link: FillLinkSummary | null): string | null {
  if (!link?.publicPath) return null;
  if (typeof window === 'undefined') return link.publicPath;
  return `${window.location.origin}${link.publicPath}`;
}

function truncateDisplayedTitle(value: string | null | undefined): string {
  const normalized = String(value || '').trim();
  if (!normalized) return '';
  if (normalized.length <= 10) return normalized;
  return `${normalized.slice(0, 10)}...`;
}

function formatQuestionType(type: FillLinkQuestion['type']): string {
  const normalized = normalizeFillLinkQuestionType(type);
  switch (normalized) {
    case 'multi_select':
      return 'Multi select';
    case 'textarea':
      return 'Textarea';
    default:
      return normalized.slice(0, 1).toUpperCase() + normalized.slice(1);
  }
}

function formatSourceType(sourceType: FillLinkQuestion['sourceType']): string {
  const normalized = String(sourceType || '').replace(/_/g, ' ').trim();
  if (!normalized) return 'Field';
  return normalized.slice(0, 1).toUpperCase() + normalized.slice(1);
}

const QUESTION_FILTER_OPTIONS: Array<{ value: QuestionFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'linked', label: 'Linked' },
  { value: 'custom', label: 'Custom' },
  { value: 'required', label: 'Required' },
];

const SIGNING_MODE_OPTIONS: Array<{ value: NonNullable<FillLinkSigningConfig['signatureMode']>; label: string }> = [
  { value: 'business', label: 'Business' },
  { value: 'consumer', label: 'Consumer' },
];

const SIGNING_CATEGORY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'ordinary_business_form', label: 'Ordinary business form' },
  { value: 'client_intake_form', label: 'Client intake form' },
  { value: 'authorization_consent_form', label: 'Authorization or consent form' },
  { value: 'acknowledgment_receipt', label: 'Acknowledgment or receipt' },
  { value: 'vendor_service_agreement', label: 'Vendor or service agreement' },
  { value: 'employment_internal_form', label: 'Internal employment form' },
];

function normalizeBuilderQuestion(question: FillLinkQuestion): FillLinkQuestion {
  return {
    ...question,
    visible: true,
  };
}

function renderPreviewInput(question: FillLinkQuestion) {
  const label = question.label || question.key;
  const normalizedType = normalizeFillLinkQuestionType(question.type);
  if (normalizedType === 'textarea') {
    return <textarea disabled rows={4} placeholder={question.placeholder || ''} aria-label={label} />;
  }
  if (normalizedType === 'date') {
    return <input disabled type="date" aria-label={label} />;
  }
  if (normalizedType === 'select') {
    return (
      <select disabled aria-label={label} defaultValue="">
        <option value="" disabled>
          Select one
        </option>
        {(question.options || []).map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }
  if (fillLinkQuestionIsBoolean(normalizedType)) {
    return (
      <label className="fill-link-dialog__preview-check">
        <input disabled type="checkbox" />
        <span>Check if yes</span>
      </label>
    );
  }
  if (fillLinkQuestionSupportsOptions(normalizedType)) {
    const inputType = normalizedType === 'multi_select' ? 'checkbox' : 'radio';
    return (
      <div className="fill-link-dialog__preview-options">
        {(question.options || []).map((option) => (
          <label key={option.key} className="fill-link-dialog__preview-option">
            <input disabled type={inputType} name={question.key} />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    );
  }
  const inputType = normalizedType === 'email' ? 'email' : normalizedType === 'phone' ? 'tel' : 'text';
  return (
    <input
      disabled
      type={inputType}
      placeholder={question.placeholder || ''}
      maxLength={question.maxLength ?? undefined}
      aria-label={label}
    />
  );
}

function QuestionPreview({ questions }: { questions: FillLinkQuestion[] }) {
  if (!questions.length) {
    return (
      <div className="fill-link-dialog__preview-empty">
        Add at least one question to preview the published web form.
      </div>
    );
  }
  return (
    <div className="fill-link-dialog__preview-list">
      {questions.map((question) => (
        <div key={question.id || question.key} className="fill-link-dialog__preview-field">
          <div className="fill-link-dialog__preview-label">
            <span>{question.label || question.key}</span>
            {question.required ? <em>Required</em> : null}
          </div>
          {question.helpText ? <p className="fill-link-dialog__preview-help">{question.helpText}</p> : null}
          {renderPreviewInput(question)}
          {question.maxLength ? (
            <p className="fill-link-dialog__preview-meta">{question.maxLength} character limit</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function ResponsesPanel({
  open,
  link,
  responses,
  loadingResponses,
  onRefresh,
  onSearchResponses,
  onApplyResponse,
  onUseResponsesAsSearchFill,
}: {
  open: boolean;
  link: FillLinkSummary | null;
  responses: FillLinkResponse[];
  loadingResponses: boolean;
  onRefresh: (search?: string) => void;
  onSearchResponses: (search: string) => void;
  onApplyResponse: (response: FillLinkResponse) => void;
  onUseResponsesAsSearchFill: () => void;
}) {
  const [query, setQuery] = useState('');
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);
  const previousQueryRef = useRef('');
  const skipNextQueryEffectRef = useRef(false);
  const onRefreshRef = useRef(onRefresh);
  const onSearchResponsesRef = useRef(onSearchResponses);

  useEffect(() => {
    onRefreshRef.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    onSearchResponsesRef.current = onSearchResponses;
  }, [onSearchResponses]);

  useEffect(() => {
    if (!open) {
      skipNextQueryEffectRef.current = true;
      setQuery('');
      setDownloadError(null);
      setDownloadingPath(null);
      previousQueryRef.current = '';
      return;
    }
    skipNextQueryEffectRef.current = true;
    previousQueryRef.current = '';
    setQuery('');
  }, [link?.id, open]);

  async function handleArtifactDownload(downloadPath: string, fallbackFilename: string) {
    setDownloadError(null);
    setDownloadingPath(downloadPath);
    try {
      await ApiService.downloadAuthenticatedFile(downloadPath, { filename: fallbackFilename });
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : 'Failed to download file.');
    } finally {
      setDownloadingPath((current) => (current === downloadPath ? null : current));
    }
  }

  useEffect(() => {
    if (!open) {
      previousQueryRef.current = '';
      return;
    }
    const trimmedQuery = query.trim();
    if (skipNextQueryEffectRef.current) {
      skipNextQueryEffectRef.current = false;
      previousQueryRef.current = trimmedQuery;
      return;
    }
    const previousQuery = previousQueryRef.current;
    previousQueryRef.current = trimmedQuery;
    if (!trimmedQuery && !previousQuery) return;
    const timeoutId = window.setTimeout(() => {
      if (trimmedQuery) {
        onSearchResponsesRef.current(trimmedQuery);
        return;
      }
      onRefreshRef.current();
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [open, query]);

  return (
    <div className="fill-link-dialog__responses-panel">
      <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
        <div>
          <h3>Responses</h3>
          <p>Search stored respondents and send one into Search &amp; Fill.</p>
        </div>
        <div className="fill-link-dialog__actions">
          <button
            type="button"
            className="ui-button ui-button--ghost"
            onClick={() => onRefresh(query.trim() || undefined)}
            disabled={loadingResponses || !link}
          >
            {loadingResponses ? 'Refreshing…' : 'Refresh responses'}
          </button>
          <button
            type="button"
            className="ui-button ui-button--ghost"
            onClick={onUseResponsesAsSearchFill}
            disabled={responses.length === 0}
          >
            Open Search &amp; Fill
          </button>
        </div>
      </div>

      <label className="fill-link-dialog__search">
        <span>Search respondents</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Name, email, phone, or answer"
        />
      </label>

      {downloadError ? (
        <p className="fill-link-dialog__error">{downloadError}</p>
      ) : null}

      {loadingResponses ? (
        <p className="fill-link-dialog__loading">Loading responses…</p>
      ) : responses.length === 0 ? (
        <p className="fill-link-dialog__loading">
          {query.trim() ? 'No respondents match your search.' : 'No one has responded yet.'}
        </p>
      ) : (
        <div className="fill-link-dialog__responses">
          {responses.map((response) => (
            <div key={response.id} className="fill-link-dialog__response-card">
              <div className="fill-link-dialog__response-meta">
                <div className="fill-link-dialog__response-copy">
                  <strong>{response.respondentLabel}</strong>
                  <p>{response.respondentSecondaryLabel || formatDateLabel(response.submittedAt)}</p>
                </div>
                {resolveResponseSigningLabel(response) ? (
                  <div className="fill-link-dialog__response-badges">
                    <span className="fill-link-dialog__response-badge">
                      {resolveResponseSigningLabel(response)}
                    </span>
                    {response.linkedSigning?.completedAt ? (
                      <span className="fill-link-dialog__response-badge fill-link-dialog__response-badge--muted">
                        {formatDateLabel(response.linkedSigning.completedAt)}
                      </span>
                    ) : response.linkedSigning?.inviteSentAt ? (
                      <span className="fill-link-dialog__response-badge fill-link-dialog__response-badge--muted">
                        {formatDateLabel(response.linkedSigning.inviteSentAt)}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
              {response.linkedSigning?.inviteDeliveryError && response.linkedSigning?.status !== 'completed' ? (
                <p className="fill-link-dialog__loading">{response.linkedSigning.inviteDeliveryError}</p>
              ) : null}
              <div className="fill-link-dialog__response-actions">
                {response.linkedSigning?.artifacts?.signedPdf?.downloadPath ? (
                  <button
                    type="button"
                    className="ui-button ui-button--primary ui-button--compact"
                    onClick={() => {
                      void handleArtifactDownload(
                        response.linkedSigning!.artifacts!.signedPdf!.downloadPath!,
                        `${response.respondentLabel || 'signed-response'}-signed.pdf`,
                      );
                    }}
                    disabled={downloadingPath === response.linkedSigning.artifacts.signedPdf.downloadPath}
                  >
                    {downloadingPath === response.linkedSigning.artifacts.signedPdf.downloadPath
                      ? 'Downloading…'
                      : 'Download signed PDF'}
                  </button>
                ) : null}
                {response.linkedSigning?.artifacts?.auditReceipt?.downloadPath ? (
                  <button
                    type="button"
                    className="ui-button ui-button--ghost ui-button--compact"
                    onClick={() => {
                      void handleArtifactDownload(
                        response.linkedSigning!.artifacts!.auditReceipt!.downloadPath!,
                        `${response.respondentLabel || 'signed-response'}-audit-receipt.pdf`,
                      );
                    }}
                    disabled={downloadingPath === response.linkedSigning.artifacts.auditReceipt.downloadPath}
                  >
                    {downloadingPath === response.linkedSigning.artifacts.auditReceipt.downloadPath
                      ? 'Downloading…'
                      : 'Audit receipt'}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="ui-button ui-button--primary ui-button--compact"
                  onClick={() => onApplyResponse(response)}
                >
                  Apply to PDF
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FillLinkScopePanel({
  open,
  onClose,
  kind,
  heading,
  scopeName,
  sourceQuestions,
  sourceLoading,
  allowCustomQuestions,
  showRespondentPdfDownloadToggle = false,
  link,
  responses,
  loadingLink,
  publishing,
  closing,
  loadingResponses,
  error,
  onPublish,
  onRefresh,
  onSearchResponses,
  onCloseLink,
  onApplyResponse,
  onUseResponsesAsSearchFill,
}: FillLinkScopePanelProps) {
  void kind;
  const [activeTab, setActiveTab] = useState<ScopeTab>('builder');
  const [builderSearch, setBuilderSearch] = useState('');
  const [builderFilter, setBuilderFilter] = useState<QuestionFilter>('all');
  const [title, setTitle] = useState('');
  const [introText, setIntroText] = useState('');
  const [defaultTextMaxLength, setDefaultTextMaxLength] = useState('');
  const [requireAllFields, setRequireAllFields] = useState(false);
  const [allowRespondentPdfDownload, setAllowRespondentPdfDownload] = useState(false);
  const [allowRespondentEditablePdfDownload, setAllowRespondentEditablePdfDownload] = useState(false);
  const [signAfterSubmitEnabled, setSignAfterSubmitEnabled] = useState(false);
  const [signatureMode, setSignatureMode] = useState<NonNullable<FillLinkSigningConfig['signatureMode']>>('business');
  const [documentCategory, setDocumentCategory] = useState('ordinary_business_form');
  const [esignEligibilityConfirmed, setEsignEligibilityConfirmed] = useState(false);
  const [manualFallbackEnabled, setManualFallbackEnabled] = useState(true);
  const [consumerPaperCopyProcedure, setConsumerPaperCopyProcedure] = useState('');
  const [consumerPaperCopyFeeDescription, setConsumerPaperCopyFeeDescription] = useState('');
  const [consumerWithdrawalProcedure, setConsumerWithdrawalProcedure] = useState('');
  const [consumerWithdrawalConsequences, setConsumerWithdrawalConsequences] = useState('');
  const [consumerContactUpdateProcedure, setConsumerContactUpdateProcedure] = useState('');
  const [consumerConsentScopeDescription, setConsumerConsentScopeDescription] = useState('');
  const [signerNameQuestionKey, setSignerNameQuestionKey] = useState('');
  const [signerEmailQuestionKey, setSignerEmailQuestionKey] = useState('');
  const [questions, setQuestions] = useState<FillLinkQuestion[]>([]);
  const [selectedQuestionId, setSelectedQuestionId] = useState<string | null>(null);
  const ensureSigningEmailQuestion = (questionList: FillLinkQuestion[]) => {
    const existingQuestion = questionList.find((question) => question.key === 'signer_email');
    if (existingQuestion) {
      const nextQuestions = questionList.map((question) => {
        if ((question.id || question.key) !== (existingQuestion.id || existingQuestion.key)) {
          return question;
        }
        return {
          ...question,
          key: 'signer_email',
          label: question.label || 'Signer Email',
          type: 'email',
          sourceType: 'custom',
          required: true,
          visible: true,
          placeholder: question.placeholder || 'name@example.com',
          helpText: question.helpText || 'Used to continue into the signing step after form submit.',
        };
      });
      return {
        questions: sortFillLinkQuestions(nextQuestions.map(normalizeBuilderQuestion)),
        questionKey: 'signer_email',
        questionId: existingQuestion.id || existingQuestion.key || 'signer_email',
      };
    }
    const nextQuestion = {
      ...createCustomFillLinkQuestion('email'),
      id: 'custom:signer_email',
      key: 'signer_email',
      label: 'Signer Email',
      type: 'email' as const,
      sourceType: 'custom' as const,
      required: true,
      visible: true,
      placeholder: 'name@example.com',
      helpText: 'Used to continue into the signing step after form submit.',
      order: questionList.length,
    };
    return {
      questions: sortFillLinkQuestions([...questionList, nextQuestion].map(normalizeBuilderQuestion)),
      questionKey: 'signer_email',
      questionId: nextQuestion.id || nextQuestion.key || 'signer_email',
    };
  };

  const publicUrl = useMemo(() => resolvePublicUrl(link), [link]);
  const builderFallbackConfig = useMemo(
    () => link?.webFormConfig || buildFallbackFillLinkWebFormConfigFromPublishedQuestions(link?.questions),
    [link?.questions, link?.webFormConfig],
  );
  const baseConfig = useMemo(() => {
    const fallbackQuestions = sourceQuestions.length
      ? sourceQuestions
      : builderFallbackConfig.questions || link?.questions || [];
    return buildFillLinkWebFormConfig(fallbackQuestions, builderFallbackConfig);
  }, [builderFallbackConfig, link?.questions, sourceQuestions]);

  const initialTitle = link?.title || scopeName || heading;
  const stateSignature = useMemo(() => JSON.stringify({
    linkId: link?.id || 'draft',
    title: initialTitle,
    introText: baseConfig.introText || '',
    defaultTextMaxLength: baseConfig.defaultTextMaxLength || null,
    requireAllFields: link?.requireAllFields || false,
    allowRespondentPdfDownload: fillLinkRespondentPdfDownloadEnabled(link),
    allowRespondentEditablePdfDownload: fillLinkRespondentPdfEditableEnabled(link),
    signingConfig: link?.signingConfig || null,
    sourceQuestionCount: sourceQuestions.length,
    sourceLoading,
    questions: baseConfig.questions || [],
  }), [
    baseConfig.defaultTextMaxLength,
    baseConfig.introText,
    baseConfig.questions,
    heading,
    initialTitle,
    link,
    scopeName,
    sourceLoading,
    sourceQuestions.length,
  ]);
  const resetState = useMemo(() => JSON.parse(stateSignature) as {
    title: string;
    introText: string;
    defaultTextMaxLength: number | null;
    requireAllFields: boolean;
    allowRespondentPdfDownload: boolean;
    allowRespondentEditablePdfDownload: boolean;
    signingConfig: FillLinkSigningConfig | null;
    questions: FillLinkQuestion[];
  }, [stateSignature]);

  useEffect(() => {
    if (!open) {
      setActiveTab('builder');
      setBuilderSearch('');
      setBuilderFilter('all');
      return;
    }
    setTitle(resetState.title);
    setIntroText(resetState.introText || '');
    setDefaultTextMaxLength(
      resetState.defaultTextMaxLength ? String(resetState.defaultTextMaxLength) : '',
    );
    setRequireAllFields(Boolean(resetState.requireAllFields));
    setAllowRespondentPdfDownload(Boolean(resetState.allowRespondentPdfDownload));
    setAllowRespondentEditablePdfDownload(Boolean(resetState.allowRespondentEditablePdfDownload));
    setSignAfterSubmitEnabled(Boolean(resetState.signingConfig?.enabled));
    setSignatureMode(resetState.signingConfig?.signatureMode === 'consumer' ? 'consumer' : 'business');
    setDocumentCategory(resetState.signingConfig?.documentCategory || 'ordinary_business_form');
    setEsignEligibilityConfirmed(
      Boolean(
        resetState.signingConfig?.esignEligibilityConfirmed
        || resetState.signingConfig?.esignEligibilityConfirmedAt,
      ),
    );
    setManualFallbackEnabled(resetState.signingConfig?.manualFallbackEnabled ?? true);
    setConsumerPaperCopyProcedure(resetState.signingConfig?.consumerPaperCopyProcedure || '');
    setConsumerPaperCopyFeeDescription(resetState.signingConfig?.consumerPaperCopyFeeDescription || '');
    setConsumerWithdrawalProcedure(resetState.signingConfig?.consumerWithdrawalProcedure || '');
    setConsumerWithdrawalConsequences(resetState.signingConfig?.consumerWithdrawalConsequences || '');
    setConsumerContactUpdateProcedure(resetState.signingConfig?.consumerContactUpdateProcedure || '');
    setConsumerConsentScopeDescription(resetState.signingConfig?.consumerConsentScopeDescription || '');
    setSignerNameQuestionKey(resetState.signingConfig?.signerNameQuestionKey || '');
    setSignerEmailQuestionKey(resetState.signingConfig?.signerEmailQuestionKey || '');
    const nextQuestions = sortFillLinkQuestions((resetState.questions || []).map(normalizeBuilderQuestion));
    setQuestions(nextQuestions);
    setSelectedQuestionId(nextQuestions[0]?.id || nextQuestions[0]?.key || null);
    setBuilderSearch('');
    setBuilderFilter('all');
  }, [open, resetState]);

  const orderedQuestions = useMemo(() => sortFillLinkQuestions(questions), [questions]);
  const currentConfig = useMemo<FillLinkWebFormConfig>(() => ({
    schemaVersion: baseConfig.schemaVersion || 2,
    introText: introText.trim() || null,
    defaultTextMaxLength: (() => {
      const numeric = Number(defaultTextMaxLength);
      return Number.isFinite(numeric) && numeric > 0 ? Math.round(numeric) : null;
    })(),
    questions: orderedQuestions.map(normalizeBuilderQuestion),
  }), [baseConfig.schemaVersion, defaultTextMaxLength, introText, orderedQuestions]);
  const publishedQuestions = useMemo(
    () => buildPublishedFillLinkQuestions(currentConfig, { requireAllFields }),
    [currentConfig, requireAllFields],
  );
  const publicQuestions = useMemo(
    () => (
      signAfterSubmitEnabled
        ? publishedQuestions.filter((question) => !fillLinkQuestionIsSigningCeremonyManaged(question))
        : publishedQuestions
    ),
    [publishedQuestions, signAfterSubmitEnabled],
  );
  const visibleSigningQuestions = useMemo(
    () => publicQuestions.filter((question) => question.visible !== false),
    [publicQuestions],
  );
  const emailSigningQuestions = useMemo(
    () => visibleSigningQuestions.filter((question) => fillLinkQuestionLooksLikeEmail(question)),
    [visibleSigningQuestions],
  );
  const consumerDisclosureError = useMemo(() => {
    if (!signAfterSubmitEnabled || signatureMode !== 'consumer') return null;
    if (!consumerPaperCopyProcedure.trim()) return 'Consumer post-submit signing requires a paper-copy or offline procedure.';
    if (!consumerPaperCopyFeeDescription.trim()) return 'Consumer post-submit signing requires a paper-copy fee disclosure.';
    if (!consumerWithdrawalProcedure.trim()) return 'Consumer post-submit signing requires a withdrawal procedure.';
    if (!consumerWithdrawalConsequences.trim()) return 'Consumer post-submit signing requires withdrawal consequences.';
    if (!consumerContactUpdateProcedure.trim()) return 'Consumer post-submit signing requires contact-update instructions.';
    return null;
  }, [
    consumerContactUpdateProcedure,
    consumerPaperCopyFeeDescription,
    consumerPaperCopyProcedure,
    consumerWithdrawalConsequences,
    consumerWithdrawalProcedure,
    signAfterSubmitEnabled,
    signatureMode,
  ]);
  const signingConfigError = useMemo(() => {
    if (!signAfterSubmitEnabled) return null;
    if (!visibleSigningQuestions.length) {
      return 'Add at least one visible question before enabling post-submit signing.';
    }
    if (!emailSigningQuestions.length) {
      return 'Add a visible email question before enabling post-submit signing.';
    }
    if (!esignEligibilityConfirmed) {
      if (link?.id) {
        return 'This signing-enabled link needs a U.S. e-sign eligibility confirmation before you can update it.';
      }
      return 'Confirm the document is eligible for DullyPDF’s U.S. e-sign flow before enabling post-submit signing.';
    }
    if (!signerNameQuestionKey) {
      return 'Choose which visible question supplies the signer name.';
    }
    if (!signerEmailQuestionKey) {
      return 'Choose which visible question supplies the signer email.';
    }
    if (!emailSigningQuestions.some((question) => question.key === signerEmailQuestionKey)) {
      return 'Choose a visible email question for the signer email mapping.';
    }
    if (consumerDisclosureError) {
      return consumerDisclosureError;
    }
    return null;
  }, [
    consumerDisclosureError,
    emailSigningQuestions,
    esignEligibilityConfirmed,
    link?.id,
    signAfterSubmitEnabled,
    signerEmailQuestionKey,
    signerNameQuestionKey,
    visibleSigningQuestions.length,
  ]);
  const builderError = useMemo(
    () => (sourceLoading ? null : validateFillLinkWebForm(currentConfig, publicQuestions)),
    [currentConfig, publicQuestions, sourceLoading],
  );
  const publishError = builderError || signingConfigError;
  const builderEmpty = !orderedQuestions.length && !sourceLoading;
  const filteredQuestions = useMemo(() => {
    const normalizedQuery = builderSearch.trim().toLowerCase();
    return orderedQuestions.filter((question) => {
      const matchesFilter = (() => {
        switch (builderFilter) {
          case 'linked':
            return question.sourceType !== 'custom';
          case 'custom':
            return question.sourceType === 'custom';
          case 'required':
            return Boolean(requireAllFields || question.required);
          default:
            return true;
        }
      })();
      if (!matchesFilter) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      const haystack = [
        question.label,
        question.key,
        question.sourceField,
        question.groupKey,
        question.sourceType,
        question.type,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [builderFilter, builderSearch, orderedQuestions, requireAllFields]);

  const defaultQuestionMap = useMemo(() => {
    const questionMap = new Map<string, FillLinkQuestion>();
    for (const question of sourceQuestions) {
      const questionId = question.id || question.key;
      questionMap.set(questionId, question);
    }
    return questionMap;
  }, [sourceQuestions]);

  const selectedQuestion = useMemo(() => {
    if (!selectedQuestionId) return null;
    return orderedQuestions.find((question) => (question.id || question.key) === selectedQuestionId) || null;
  }, [orderedQuestions, selectedQuestionId]);

  useEffect(() => {
    if (!selectedQuestionId) return;
    if (!selectedQuestion && filteredQuestions[0]) {
      setSelectedQuestionId(filteredQuestions[0].id || filteredQuestions[0].key);
    }
  }, [filteredQuestions, selectedQuestion, selectedQuestionId]);

  useEffect(() => {
    if (!signAfterSubmitEnabled || !visibleSigningQuestions.length) {
      return;
    }
    if (!signerNameQuestionKey) {
      setSignerNameQuestionKey(visibleSigningQuestions[0]?.key || '');
    }
    if (!signerEmailQuestionKey && emailSigningQuestions.length) {
      setSignerEmailQuestionKey(emailSigningQuestions[0]?.key || '');
    }
  }, [
    emailSigningQuestions,
    signAfterSubmitEnabled,
    signerEmailQuestionKey,
    signerNameQuestionKey,
    visibleSigningQuestions,
  ]);

  useEffect(() => {
    if (!signAfterSubmitEnabled || emailSigningQuestions.length) {
      return;
    }
    const ensured = ensureSigningEmailQuestion(orderedQuestions);
    setQuestions(ensured.questions);
    setSignerEmailQuestionKey(ensured.questionKey);
    if (!selectedQuestionId) {
      setSelectedQuestionId(ensured.questionId);
    }
  }, [emailSigningQuestions.length, orderedQuestions, selectedQuestionId, signAfterSubmitEnabled]);

  useEffect(() => {
    if (signAfterSubmitEnabled && allowRespondentEditablePdfDownload) {
      setAllowRespondentEditablePdfDownload(false);
    }
  }, [allowRespondentEditablePdfDownload, signAfterSubmitEnabled]);

  const updateQuestions = (nextQuestions: FillLinkQuestion[]) => {
    const normalizedQuestions = sortFillLinkQuestions(nextQuestions.map(normalizeBuilderQuestion));
    setQuestions(normalizedQuestions);
  };

  const updateQuestion = (questionId: string, updater: (question: FillLinkQuestion) => FillLinkQuestion) => {
    updateQuestions(
      orderedQuestions.map((question) => {
        if ((question.id || question.key) !== questionId) return question;
        return updater(question);
      }),
    );
  };

  const addCustomQuestion = () => {
    const nextQuestion = createCustomFillLinkQuestion('text');
    nextQuestion.order = orderedQuestions.length;
    const nextQuestions = sortFillLinkQuestions([...orderedQuestions, nextQuestion]);
    setQuestions(nextQuestions);
    setSelectedQuestionId(nextQuestion.id || nextQuestion.key);
  };

  const removeQuestion = (questionId: string) => {
    const nextQuestions = orderedQuestions.filter((question) => (question.id || question.key) !== questionId);
    updateQuestions(nextQuestions);
    const nextSelection = nextQuestions[0];
    setSelectedQuestionId(nextSelection ? (nextSelection.id || nextSelection.key) : null);
  };

  const restoreQuestionDefaults = (questionId: string) => {
    const defaultQuestion = defaultQuestionMap.get(questionId);
    if (!defaultQuestion) {
      return;
    }
    updateQuestion(questionId, () => ({
      ...defaultQuestion,
      order: orderedQuestions.find((question) => (question.id || question.key) === questionId)?.order ?? defaultQuestion.order,
    }));
  };

  const moveQuestion = (questionId: string, direction: -1 | 1) => {
    const currentIndex = orderedQuestions.findIndex((question) => (question.id || question.key) === questionId);
    if (currentIndex < 0) return;
    const nextIndex = currentIndex + direction;
    if (nextIndex < 0 || nextIndex >= orderedQuestions.length) return;
    const nextQuestions = [...orderedQuestions];
    const [moved] = nextQuestions.splice(currentIndex, 1);
    nextQuestions.splice(nextIndex, 0, moved);
    updateQuestions(nextQuestions.map((question, index) => ({ ...question, order: index })));
  };

  const handleCopyLink = async () => {
    if (!publicUrl || typeof navigator === 'undefined' || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(publicUrl);
    } catch {
      // Best-effort clipboard support only.
    }
  };

  const handlePublish = () => {
    if (publishError) return;
    onPublish({
      title: title.trim() || initialTitle,
      requireAllFields,
      allowRespondentPdfDownload,
      allowRespondentEditablePdfDownload: signAfterSubmitEnabled ? false : allowRespondentEditablePdfDownload,
      webFormConfig: currentConfig,
      signingConfig: signAfterSubmitEnabled
        ? {
          enabled: true,
          signatureMode,
          documentCategory,
          esignEligibilityConfirmed,
          manualFallbackEnabled,
          consumerPaperCopyProcedure: consumerPaperCopyProcedure.trim() || undefined,
          consumerPaperCopyFeeDescription: consumerPaperCopyFeeDescription.trim() || undefined,
          consumerWithdrawalProcedure: consumerWithdrawalProcedure.trim() || undefined,
          consumerWithdrawalConsequences: consumerWithdrawalConsequences.trim() || undefined,
          consumerContactUpdateProcedure: consumerContactUpdateProcedure.trim() || undefined,
          consumerConsentScopeDescription: consumerConsentScopeDescription.trim() || undefined,
          signerNameQuestionKey,
          signerEmailQuestionKey,
        }
        : { enabled: false },
    });
  };

  const currentQuestionId = selectedQuestion ? (selectedQuestion.id || selectedQuestion.key) : null;
  const publishButtonLabel = publishing ? 'Publishing…' : (link ? 'Update link' : 'Publish link');
  const closeButtonLabel = closing
    ? (link?.status === 'active' ? 'Closing…' : 'Reopening…')
    : (link?.status === 'active' ? 'Close link' : 'Reopen link');
  const resolvedTitle = title.trim() || link?.title || initialTitle;
  const renderQuestionEditorRow = (question: FillLinkQuestion) => {
    const questionId = question.id || question.key;
    const isSelected = questionId === currentQuestionId;

    return (
      <article
        key={questionId}
        className={`fill-link-dialog__question-editor-row ${isSelected ? 'fill-link-dialog__question-editor-row--selected' : ''}`}
      >
        <div className="fill-link-dialog__question-row-shell">
          <button
            type="button"
            className={`fill-link-dialog__question-row ${isSelected ? 'fill-link-dialog__question-row--selected' : ''}`}
            onClick={() => setSelectedQuestionId(isSelected ? null : questionId)}
          >
            <div className="fill-link-dialog__question-row-main">
              <strong>{question.label || question.key}</strong>
              <p>{question.key}</p>
            </div>
            <div className="fill-link-dialog__question-chips">
              <span>{formatQuestionType(question.type)}</span>
              <span>{formatSourceType(question.sourceType)}</span>
              {requireAllFields || question.required ? <span>Required</span> : null}
            </div>
          </button>
          <div className="fill-link-dialog__question-row-actions">
            <button
              type="button"
              className="ui-button ui-button--ghost ui-button--compact"
              onClick={() => moveQuestion(questionId, -1)}
            >
              Up
            </button>
            <button
              type="button"
              className="ui-button ui-button--ghost ui-button--compact"
              onClick={() => moveQuestion(questionId, 1)}
            >
              Down
            </button>
            {defaultQuestionMap.has(questionId) ? (
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={() => restoreQuestionDefaults(questionId)}
              >
                Restore
              </button>
            ) : null}
            {question.sourceType === 'custom' ? (
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={() => removeQuestion(questionId)}
              >
                Remove
              </button>
            ) : null}
          </div>
        </div>

        {isSelected ? (
          <div className="fill-link-dialog__question-inline-editor">
            <div className="fill-link-dialog__question-inline-grid">
              <label className="fill-link-dialog__field fill-link-dialog__field--wide">
                <span>Question label</span>
                <input
                  type="text"
                  value={question.label || ''}
                  onChange={(event) => updateQuestion(questionId, (entry) => ({
                    ...entry,
                    label: event.target.value,
                  }))}
                  maxLength={200}
                />
              </label>

              {question.sourceType === 'custom' ? (
                <label className="fill-link-dialog__field">
                  <span>Question type</span>
                  <select
                    value={normalizeFillLinkQuestionType(question.type)}
                    onChange={(event) => {
                      const nextType = normalizeFillLinkQuestionType(event.target.value);
                      updateQuestion(questionId, (entry) => ({
                        ...entry,
                        type: nextType,
                        options: fillLinkQuestionSupportsOptions(nextType)
                          ? (entry.options?.length ? entry.options : [{ key: 'option_1', label: 'Option 1' }])
                          : undefined,
                        maxLength: fillLinkQuestionSupportsTextLimit(nextType) ? entry.maxLength : null,
                      }));
                    }}
                  >
                    <option value="text">Text</option>
                    <option value="textarea">Textarea</option>
                    <option value="date">Date</option>
                    <option value="boolean">Checkbox</option>
                    <option value="radio">Radio</option>
                    <option value="select">Select</option>
                    <option value="email">Email</option>
                    <option value="phone">Phone</option>
                  </select>
                </label>
              ) : null}

              {fillLinkQuestionSupportsTextLimit(question.type) ? (
                <label className="fill-link-dialog__field">
                  <span>Character limit</span>
                  <input
                    type="number"
                    min={1}
                    max={4000}
                    value={question.maxLength ?? ''}
                    onChange={(event) => updateQuestion(questionId, (entry) => ({
                      ...entry,
                      maxLength: event.target.value ? Number(event.target.value) : null,
                    }))}
                    placeholder={currentConfig.defaultTextMaxLength ? `Default ${currentConfig.defaultTextMaxLength}` : 'Use global default'}
                  />
                </label>
              ) : null}

              {fillLinkQuestionSupportsTextLimit(question.type) ? (
                <label className="fill-link-dialog__field fill-link-dialog__field--wide">
                  <span>Placeholder</span>
                  <input
                    type="text"
                    value={question.placeholder || ''}
                    onChange={(event) => updateQuestion(questionId, (entry) => ({
                      ...entry,
                      placeholder: event.target.value,
                    }))}
                    maxLength={200}
                  />
                </label>
              ) : null}

              <label className="fill-link-dialog__inline-check">
                <span>Required</span>
                <input
                  type="checkbox"
                  checked={Boolean(requireAllFields || question.required)}
                  onChange={(event) => updateQuestion(questionId, (entry) => ({
                    ...entry,
                    required: event.target.checked,
                  }))}
                  disabled={requireAllFields}
                />
              </label>
            </div>

            <label className="fill-link-dialog__field fill-link-dialog__field--full">
              <span>Help text</span>
              <textarea
                rows={2}
                value={question.helpText || ''}
                onChange={(event) => updateQuestion(questionId, (entry) => ({
                  ...entry,
                  helpText: event.target.value,
                }))}
                maxLength={400}
              />
            </label>

            {fillLinkQuestionSupportsOptions(question.type) ? (
              <div className="fill-link-dialog__options-editor">
                <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
                  <div>
                    <h3>Options</h3>
                    <p>Respondents will choose from these values.</p>
                  </div>
                  <button
                    type="button"
                    className="ui-button ui-button--ghost ui-button--compact"
                    onClick={() => updateQuestion(questionId, (entry) => ({
                      ...entry,
                      options: [
                        ...(entry.options || []),
                        {
                          key: `option_${(entry.options?.length || 0) + 1}`,
                          label: `Option ${(entry.options?.length || 0) + 1}`,
                        },
                      ],
                    }))}
                  >
                    Add option
                  </button>
                </div>
                <div className="fill-link-dialog__option-list">
                  {(question.options || []).map((option, index) => (
                    <div key={`${option.key}-${index}`} className="fill-link-dialog__option-row">
                      <input
                        type="text"
                        value={option.label}
                        onChange={(event) => updateQuestion(questionId, (entry) => ({
                          ...entry,
                          options: (entry.options || []).map((optionEntry, optionIndex) => (
                            optionIndex === index
                              ? { ...optionEntry, label: event.target.value }
                              : optionEntry
                          )),
                        }))}
                        maxLength={200}
                      />
                      <button
                        type="button"
                        className="ui-button ui-button--ghost ui-button--compact"
                        onClick={() => updateQuestion(questionId, (entry) => ({
                          ...entry,
                          options: (entry.options || []).filter((_, optionIndex) => optionIndex !== index),
                        }))}
                        disabled={(question.options?.length || 0) <= 1}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </article>
    );
  };

  return (
    <section className="fill-link-dialog__scope">
      <div className="fill-link-dialog__topbar">
        <div className="fill-link-dialog__headline">
          <strong className="fill-link-dialog__headline-title">Fill By Web Form Link + Sign:</strong>
          <span className="fill-link-dialog__headline-copy">
            Build a DullyPDF-hosted web form, collect respondent answers, and optionally route them into signature.
          </span>
        </div>

        <div className="fill-link-dialog__tabs">
          <button
            type="button"
            className={`fill-link-dialog__tab ${activeTab === 'builder' ? 'fill-link-dialog__tab--active' : ''}`}
            onClick={() => setActiveTab('builder')}
          >
            Builder
          </button>
          <button
            type="button"
            className={`fill-link-dialog__tab ${activeTab === 'preview' ? 'fill-link-dialog__tab--active' : ''}`}
            onClick={() => setActiveTab('preview')}
          >
            Preview
          </button>
          <button
            type="button"
            className={`fill-link-dialog__tab ${activeTab === 'responses' ? 'fill-link-dialog__tab--active' : ''}`}
            onClick={() => setActiveTab('responses')}
          >
            Responses
          </button>
        </div>

        <div className="fill-link-dialog__actions">
          <button
            type="button"
            className="ui-button ui-button--primary ui-button--compact"
            onClick={handlePublish}
            disabled={publishing || loadingLink || Boolean(publishError) || sourceLoading}
          >
            {publishButtonLabel}
          </button>
          <button
            type="button"
            className="ui-button ui-button--ghost ui-button--compact"
            onClick={() => onCloseLink({
              title: title.trim() || initialTitle,
              requireAllFields,
              allowRespondentPdfDownload,
              webFormConfig: currentConfig,
              signingConfig: signAfterSubmitEnabled
                ? {
                  enabled: true,
                  signatureMode,
                  documentCategory,
                  esignEligibilityConfirmed,
                  manualFallbackEnabled,
                  consumerPaperCopyProcedure: consumerPaperCopyProcedure.trim() || undefined,
                  consumerPaperCopyFeeDescription: consumerPaperCopyFeeDescription.trim() || undefined,
                  consumerWithdrawalProcedure: consumerWithdrawalProcedure.trim() || undefined,
                  consumerWithdrawalConsequences: consumerWithdrawalConsequences.trim() || undefined,
                  consumerContactUpdateProcedure: consumerContactUpdateProcedure.trim() || undefined,
                  consumerConsentScopeDescription: consumerConsentScopeDescription.trim() || undefined,
                  signerNameQuestionKey,
                  signerEmailQuestionKey,
                }
                : { enabled: false },
            })}
            disabled={closing || (!link && !loadingLink)}
          >
            {closeButtonLabel}
          </button>
          {publicUrl ? (
            <>
              <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={handleCopyLink}>
                Copy link
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={() => window.open(publicUrl, '_blank', 'noopener,noreferrer')}
              >
                Open link
              </button>
            </>
          ) : null}
        </div>
        <button
          type="button"
          className="fill-link-dialog__close-button"
          onClick={onClose}
          aria-label="Close Fill By Web Form Link + Sign"
        >
          ×
        </button>
      </div>

      {error ? <p className="fill-link-dialog__error">{error}</p> : null}
      {publishError ? <p className="fill-link-dialog__error fill-link-dialog__error--topbar">{publishError}</p> : null}

      {activeTab === 'responses' ? (
        <section className="fill-link-dialog__section fill-link-dialog__section--surface fill-link-dialog__section--responses">
          <ResponsesPanel
            open={open}
            link={link}
            responses={responses}
            loadingResponses={loadingResponses}
            onRefresh={onRefresh}
            onSearchResponses={onSearchResponses}
            onApplyResponse={onApplyResponse}
            onUseResponsesAsSearchFill={onUseResponsesAsSearchFill}
          />
        </section>
      ) : activeTab === 'preview' ? (
        <section className="fill-link-dialog__section fill-link-dialog__section--surface fill-link-dialog__section--preview-page">
          <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
            <div>
              <h3>Live preview</h3>
              <p>This is the respondent-facing form based on the current builder state.</p>
            </div>
          </div>
          <div className="fill-link-dialog__preview-shell fill-link-dialog__preview-shell--page">
            <div className="fill-link-dialog__preview-head">
              <strong title={resolvedTitle || initialTitle}>
                {truncateDisplayedTitle(resolvedTitle || initialTitle) || initialTitle}
              </strong>
              {introText.trim() ? <p>{introText.trim()}</p> : null}
            </div>
            <QuestionPreview questions={publicQuestions} />
          </div>
        </section>
      ) : (
        <div className="fill-link-dialog__builder-stack">
          <section className="fill-link-dialog__section fill-link-dialog__section--surface fill-link-dialog__section--settings">
            <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
              <p className="fill-link-dialog__section-inline-copy">
                <strong>Global settings:</strong> These apply across the published web form for this link. Publish right after setting up Global Settings for a Quick Form.
              </p>
            </div>

            <div className="fill-link-dialog__settings-grid">
              <label className="fill-link-dialog__field">
                <span>Form title</span>
                <input
                  type="text"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={initialTitle}
                  maxLength={200}
                />
              </label>

              <label className="fill-link-dialog__field">
                <span>Intro text</span>
                <textarea
                  rows={3}
                  value={introText}
                  onChange={(event) => setIntroText(event.target.value)}
                  placeholder="Short instructions or context for respondents."
                  maxLength={2000}
                />
              </label>

              <label className="fill-link-dialog__field">
                <span>Default text char limit</span>
                <input
                  type="number"
                  min={1}
                  max={4000}
                  value={defaultTextMaxLength}
                  onChange={(event) => setDefaultTextMaxLength(event.target.value)}
                  placeholder="No default limit"
                />
              </label>

              <div className="fill-link-dialog__toggle-row">
                <label className="fill-link-dialog__toggle fill-link-dialog__toggle--compact">
                  <input
                    type="checkbox"
                    checked={requireAllFields}
                    onChange={(event) => setRequireAllFields(event.target.checked)}
                  />
                  <div>
                    <strong>Require all</strong>
                    <p>Every visible question must be answered.</p>
                  </div>
                </label>

                {showRespondentPdfDownloadToggle ? (
                  <label className="fill-link-dialog__toggle fill-link-dialog__toggle--compact">
                    <input
                      type="checkbox"
                      checked={allowRespondentPdfDownload}
                      onChange={(event) => {
                        const enabled = event.target.checked;
                        setAllowRespondentPdfDownload(enabled);
                        if (!enabled) {
                          setAllowRespondentEditablePdfDownload(false);
                        }
                      }}
                    />
                    <div>
                      <strong>Allow PDF download</strong>
                      <p>Respondents can download a flat PDF after submit.</p>
                    </div>
                  </label>
                ) : null}

                {showRespondentPdfDownloadToggle ? (
                  <label className="fill-link-dialog__toggle fill-link-dialog__toggle--compact">
                    <input
                      type="checkbox"
                      checked={allowRespondentEditablePdfDownload}
                      onChange={(event) => setAllowRespondentEditablePdfDownload(event.target.checked)}
                      disabled={!allowRespondentPdfDownload || signAfterSubmitEnabled}
                    />
                    <div>
                      <strong>Download editable PDF</strong>
                      <p>{signAfterSubmitEnabled ? 'Signed flows always stay flat.' : 'Overrides the flat default and preserves fields.'}</p>
                    </div>
                  </label>
                ) : null}

                {showRespondentPdfDownloadToggle ? (
                  <label className="fill-link-dialog__toggle fill-link-dialog__toggle--compact">
                    <input
                      type="checkbox"
                      checked={signAfterSubmitEnabled}
                      onChange={(event) => {
                        const enabled = event.target.checked;
                        setSignAfterSubmitEnabled(enabled);
                        if (enabled) {
                          setAllowRespondentEditablePdfDownload(false);
                        }
                        if (!enabled || emailSigningQuestions.length) {
                          return;
                        }
                        const ensured = ensureSigningEmailQuestion(orderedQuestions);
                        setQuestions(ensured.questions);
                        setSignerEmailQuestionKey(ensured.questionKey);
                        setSelectedQuestionId(ensured.questionId);
                      }}
                    />
                    <div>
                      <strong>Require signature</strong>
                      <p>Respondents continue into the frozen signing flow.</p>
                    </div>
                  </label>
                ) : null}
              </div>
              {showRespondentPdfDownloadToggle && signAfterSubmitEnabled ? (
                <div className="fill-link-dialog__signing-settings">
                  <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
                    <div>
                      <h3>Post-submit signing</h3>
                      <p>Choose how the public Fill By Link response hands off into the signing ceremony.</p>
                    </div>
                  </div>

                  <div className="fill-link-dialog__settings-grid fill-link-dialog__settings-grid--nested">
                    <label className="fill-link-dialog__field">
                      <span>Signature mode</span>
                      <select
                        value={signatureMode}
                        onChange={(event) => setSignatureMode(event.target.value === 'consumer' ? 'consumer' : 'business')}
                      >
                        {SIGNING_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="fill-link-dialog__field">
                      <span>Document category</span>
                      <select
                        value={documentCategory}
                        onChange={(event) => setDocumentCategory(event.target.value)}
                      >
                        {SIGNING_CATEGORY_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="fill-link-dialog__toggle fill-link-dialog__field--full">
                      <input
                        type="checkbox"
                        checked={esignEligibilityConfirmed}
                        onChange={(event) => setEsignEligibilityConfirmed(event.target.checked)}
                      />
                      <div>
                        <strong>Confirm U.S. e-sign eligibility</strong>
                        <p>I reviewed the blocked-category list, including court, family-law, UCC-excluded, recall/safety, and primary-residence notice categories, and confirm this document is eligible for DullyPDF&apos;s U.S. e-sign flow.</p>
                      </div>
                    </label>

                    <label className="fill-link-dialog__field">
                      <span>Signer name question</span>
                      <select
                        value={signerNameQuestionKey}
                        onChange={(event) => setSignerNameQuestionKey(event.target.value)}
                      >
                        <option value="">Choose a visible question</option>
                        {visibleSigningQuestions.map((question) => (
                          <option key={`signer-name-${question.key}`} value={question.key}>
                            {question.label || question.key}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="fill-link-dialog__field">
                      <span>Signer email question</span>
                      <select
                        value={signerEmailQuestionKey}
                        onChange={(event) => setSignerEmailQuestionKey(event.target.value)}
                        disabled={!emailSigningQuestions.length}
                      >
                        <option value="">{emailSigningQuestions.length ? 'Choose a visible email question' : 'Add an email question first'}</option>
                        {emailSigningQuestions.map((question) => (
                          <option key={`signer-email-${question.key}`} value={question.key}>
                            {question.label || question.key}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="fill-link-dialog__toggle fill-link-dialog__field--full">
                      <input
                        type="checkbox"
                        checked={manualFallbackEnabled}
                        onChange={(event) => setManualFallbackEnabled(event.target.checked)}
                      />
                      <div>
                        <strong>Allow paper/manual fallback</strong>
                        <p>Respondents can opt out of e-signing and ask the sender for an offline copy.</p>
                      </div>
                    </label>
                    {signatureMode === 'consumer' ? (
                      <>
                        <label className="fill-link-dialog__field fill-link-dialog__field--full">
                          <span>Paper-copy or offline procedure</span>
                          <textarea
                            value={consumerPaperCopyProcedure}
                            onChange={(event) => setConsumerPaperCopyProcedure(event.target.value)}
                            placeholder="Explain exactly how the respondent requests paper delivery or offline processing."
                          />
                        </label>
                        <label className="fill-link-dialog__field fill-link-dialog__field--full">
                          <span>Paper-copy fee disclosure</span>
                          <textarea
                            value={consumerPaperCopyFeeDescription}
                            onChange={(event) => setConsumerPaperCopyFeeDescription(event.target.value)}
                            placeholder="State any paper-copy, courier, or handling fee, or say no fee is charged."
                          />
                        </label>
                        <label className="fill-link-dialog__field fill-link-dialog__field--full">
                          <span>Withdrawal procedure</span>
                          <textarea
                            value={consumerWithdrawalProcedure}
                            onChange={(event) => setConsumerWithdrawalProcedure(event.target.value)}
                            placeholder="Explain how the respondent withdraws e-consent before signing completes."
                          />
                        </label>
                        <label className="fill-link-dialog__field fill-link-dialog__field--full">
                          <span>Withdrawal consequences</span>
                          <textarea
                            value={consumerWithdrawalConsequences}
                            onChange={(event) => setConsumerWithdrawalConsequences(event.target.value)}
                            placeholder="Explain what happens to this response after consent is withdrawn."
                          />
                        </label>
                        <label className="fill-link-dialog__field fill-link-dialog__field--full">
                          <span>Contact-update procedure</span>
                          <textarea
                            value={consumerContactUpdateProcedure}
                            onChange={(event) => setConsumerContactUpdateProcedure(event.target.value)}
                            placeholder="Explain how the respondent updates email or contact information before completion."
                          />
                        </label>
                        <label className="fill-link-dialog__field fill-link-dialog__field--full">
                          <span>Consent scope override (optional)</span>
                          <textarea
                            value={consumerConsentScopeDescription}
                            onChange={(event) => setConsumerConsentScopeDescription(event.target.value)}
                            placeholder="Leave blank to scope consent to this signing request only."
                          />
                        </label>
                      </>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section className="fill-link-dialog__section fill-link-dialog__section--surface fill-link-dialog__section--questions">
            <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
              <p className="fill-link-dialog__section-inline-copy">
                <strong>Questions:</strong> Search, reorder, and configure the respondent-facing questions. Give each question custom configuration.
              </p>
              {allowCustomQuestions ? (
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={addCustomQuestion}
                >
                  Add custom
                </button>
              ) : null}
            </div>

            <div className="fill-link-dialog__questions-toolbar">
              <label className="fill-link-dialog__search">
                <span>Search questions</span>
                <input
                  type="search"
                  value={builderSearch}
                  onChange={(event) => setBuilderSearch(event.target.value)}
                  placeholder="Field name, label, source, or type"
                />
              </label>

              <div className="fill-link-dialog__filter-row" role="tablist" aria-label="Question filters">
                {QUESTION_FILTER_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={`fill-link-dialog__filter-chip ${builderFilter === option.value ? 'fill-link-dialog__filter-chip--active' : ''}`}
                    onClick={() => setBuilderFilter(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {sourceLoading ? (
              <p className="fill-link-dialog__loading">Loading fields…</p>
            ) : builderEmpty ? (
              <div className="fill-link-dialog__empty">
                <p>
                  {allowCustomQuestions
                    ? 'No source questions are available yet. Add a custom question to build the web form.'
                    : 'No merged group questions are available for this packet yet.'}
                </p>
              </div>
            ) : filteredQuestions.length === 0 ? (
              <p className="fill-link-dialog__loading">No questions match your search.</p>
            ) : (
              <div className="fill-link-dialog__question-list fill-link-dialog__question-list--editor" role="list">
                {filteredQuestions.map((question) => renderQuestionEditorRow(question))}
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

export function FillLinkManagerDialog({
  open,
  onClose,
  templateName,
  hasActiveTemplate,
  templateSourceQuestions = [],
  templateBuilderLoading = false,
  groupName,
  hasActiveGroup,
  groupSourceQuestions = [],
  groupBuilderLoading = false,
  templateLink,
  templateResponses,
  templateLoadingLink = false,
  templatePublishing = false,
  templateClosing = false,
  templateLoadingResponses = false,
  templateError = null,
  onPublishTemplate,
  onRefreshTemplate,
  onSearchTemplateResponses,
  onCloseTemplateLink,
  onApplyTemplateResponse,
  onUseTemplateResponsesAsSearchFill,
  groupLink,
  groupResponses,
  groupLoadingLink = false,
  groupPublishing = false,
  groupClosing = false,
  groupLoadingResponses = false,
  groupError = null,
  onPublishGroup,
  onRefreshGroup,
  onSearchGroupResponses,
  onCloseGroupLink,
  onApplyGroupResponse,
  onUseGroupResponsesAsSearchFill,
}: FillLinkManagerDialogProps) {
  const availableScopes = useMemo<ScopeKind[]>(() => {
    const scopes: ScopeKind[] = [];
    if (hasActiveTemplate) scopes.push('template');
    if (hasActiveGroup) scopes.push('group');
    return scopes;
  }, [hasActiveGroup, hasActiveTemplate]);
  const [activeScope, setActiveScope] = useState<ScopeKind>(availableScopes[0] || 'template');

  useEffect(() => {
    if (!open) return;
    if (availableScopes.includes(activeScope)) return;
    setActiveScope(availableScopes[0] || 'template');
  }, [activeScope, availableScopes, open]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Fill By Web Form Link + Sign"
      description={(
        <span className="fill-link-dialog__intro">
          Build a DullyPDF-hosted web form, collect respondent answers, and optionally route them into signature.
        </span>
      )}
      className="fill-link-dialog"
    >
      <div className="fill-link-dialog__body">
        {!availableScopes.length ? (
          <div className="fill-link-dialog__empty">
            <p>Load a saved template or open a group in the workspace, then publish Fill By Web Form Link + Sign from here.</p>
          </div>
        ) : null}

        {availableScopes.length > 1 ? (
          <div className="fill-link-dialog__scope-tabs">
            {availableScopes.map((scope) => (
              <button
                key={scope}
                type="button"
                className={`fill-link-dialog__scope-tab ${activeScope === scope ? 'fill-link-dialog__scope-tab--active' : ''}`}
                onClick={() => setActiveScope(scope)}
              >
                {scope === 'template' ? 'Template' : 'Group'}
              </button>
            ))}
          </div>
        ) : null}

        {hasActiveTemplate && activeScope === 'template' ? (
          <FillLinkScopePanel
            open={open}
            onClose={onClose}
            kind="template"
            heading="Template Web Form Link"
            scopeName={templateName}
            sourceQuestions={templateSourceQuestions}
            sourceLoading={templateBuilderLoading}
            allowCustomQuestions
            showRespondentPdfDownloadToggle
            link={templateLink}
            responses={templateResponses}
            loadingLink={templateLoadingLink}
            publishing={templatePublishing}
            closing={templateClosing}
            loadingResponses={templateLoadingResponses}
            error={templateError}
            onPublish={onPublishTemplate}
            onRefresh={onRefreshTemplate}
            onSearchResponses={onSearchTemplateResponses}
            onCloseLink={onCloseTemplateLink}
            onApplyResponse={onApplyTemplateResponse}
            onUseResponsesAsSearchFill={onUseTemplateResponsesAsSearchFill}
          />
        ) : null}

        {hasActiveGroup && activeScope === 'group' ? (
          <FillLinkScopePanel
            open={open}
            onClose={onClose}
            kind="group"
            heading="Group Web Form Link"
            scopeName={groupName}
            sourceQuestions={groupSourceQuestions}
            sourceLoading={groupBuilderLoading}
            allowCustomQuestions={false}
            link={groupLink}
            responses={groupResponses}
            loadingLink={groupLoadingLink}
            publishing={groupPublishing}
            closing={groupClosing}
            loadingResponses={groupLoadingResponses}
            error={groupError}
            onPublish={onPublishGroup}
            onRefresh={onRefreshGroup}
            onSearchResponses={onSearchGroupResponses}
            onCloseLink={onCloseGroupLink}
            onApplyResponse={onApplyGroupResponse}
            onUseResponsesAsSearchFill={onUseGroupResponsesAsSearchFill}
          />
        ) : null}
      </div>
    </Dialog>
  );
}

export default FillLinkManagerDialog;
