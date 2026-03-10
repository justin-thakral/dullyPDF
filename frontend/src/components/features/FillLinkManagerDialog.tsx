import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import { Dialog } from '../ui/Dialog';
import type { FillLinkResponse, FillLinkSummary, ProfileLimits } from '../../services/api';
import { fillLinkRespondentPdfDownloadEnabled } from '../../utils/fillLinks';
import './FillLinkManagerDialog.css';

type FillLinkPublishOptions = {
  requireAllFields?: boolean;
  allowRespondentPdfDownload?: boolean;
};

export type FillLinkManagerDialogProps = {
  open: boolean;
  onClose: () => void;
  templateName: string | null;
  hasActiveTemplate: boolean;
  groupName: string | null;
  hasActiveGroup: boolean;
  limits: ProfileLimits;
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

type FillLinkSectionConfig = {
  heading: string;
  summary: string;
  emptyMessage: string;
  link: FillLinkSummary | null;
  responses: FillLinkResponse[];
  loadingLink: boolean;
  publishing: boolean;
  closing: boolean;
  loadingResponses: boolean;
  error: string | null;
  query: string;
  requireAllFields: boolean;
  showRespondentPdfDownloadToggle?: boolean;
  allowRespondentPdfDownload?: boolean;
  onQueryChange: (value: string) => void;
  onRequireAllFieldsChange: (value: boolean) => void;
  onAllowRespondentPdfDownloadChange?: (value: boolean) => void;
  onPublish: (options?: FillLinkPublishOptions) => void;
  onRefresh: (search?: string) => void;
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

function resolvePublicUrl(link: FillLinkSummary | null): string | null {
  if (!link?.publicPath) return null;
  if (typeof window === 'undefined') return link.publicPath;
  return `${window.location.origin}${link.publicPath}`;
}

function FillLinkSection({
  heading,
  summary,
  emptyMessage,
  link,
  responses,
  loadingLink,
  publishing,
  closing,
  loadingResponses,
  error,
  query,
  requireAllFields,
  showRespondentPdfDownloadToggle = false,
  allowRespondentPdfDownload = false,
  onQueryChange,
  onRequireAllFieldsChange,
  onAllowRespondentPdfDownloadChange,
  onPublish,
  onRefresh,
  onCloseLink,
  onApplyResponse,
  onUseResponsesAsSearchFill,
}: FillLinkSectionConfig) {
  const publicUrl = useMemo(() => resolvePublicUrl(link), [link]);

  const handleCopyLink = async () => {
    if (!publicUrl || typeof navigator === 'undefined' || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(publicUrl);
    } catch {
      // Best-effort clipboard support only.
    }
  };

  return (
    <section className="fill-link-dialog__section">
      <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
        <div>
          <h3>{heading}</h3>
          <p>{summary}</p>
        </div>
      </div>

      {error ? <p className="fill-link-dialog__error">{error}</p> : null}

      <label className="fill-link-dialog__toggle">
        <input
          type="checkbox"
          checked={requireAllFields}
          onChange={(event) => onRequireAllFieldsChange(event.target.checked)}
        />
        <div>
          <strong>Require every field before submit</strong>
          <p>Off by default. When enabled, DullyPDF rejects submissions that leave any question blank.</p>
        </div>
      </label>

      {showRespondentPdfDownloadToggle ? (
        <label className="fill-link-dialog__toggle">
          <input
            type="checkbox"
            checked={allowRespondentPdfDownload}
            onChange={(event) => onAllowRespondentPdfDownloadChange?.(event.target.checked)}
          />
          <div>
            <strong>Allow respondents to download a PDF copy after submit</strong>
            <p>Template links only. The download button appears on the success screen after a valid submission.</p>
          </div>
        </label>
      ) : null}

      {!link && !loadingLink ? (
        <div className="fill-link-dialog__empty">
          <p>{emptyMessage}</p>
          <button
            type="button"
            className="ui-button ui-button--primary"
            onClick={() => onPublish({ requireAllFields, allowRespondentPdfDownload })}
            disabled={publishing}
          >
            {publishing ? 'Publishing…' : `Publish ${heading}`}
          </button>
        </div>
      ) : null}

      {loadingLink ? (
        <div className="fill-link-dialog__empty">
          <p>Loading {heading.toLowerCase()}…</p>
        </div>
      ) : null}

      {link ? (
        <div className="fill-link-dialog__content">
          <section className="fill-link-dialog__section">
            <div className="fill-link-dialog__section-header">
              <div>
                <h3>{link.title}</h3>
                <p>{link.status === 'active' ? 'Live respondent form' : 'Closed respondent form'}</p>
              </div>
              <span className={`fill-link-dialog__status fill-link-dialog__status--${link.status}`}>
                {link.status}
              </span>
            </div>
            <div className="fill-link-dialog__stats">
              <div>
                <span>Responses</span>
                <strong>{link.responseCount ?? 0} / {(link.maxResponses ?? 0).toLocaleString()}</strong>
              </div>
              <div>
                <span>Published</span>
                <strong>{formatDateLabel(link.publishedAt)}</strong>
              </div>
              <div>
                <span>Submit rule</span>
                <strong>{link.requireAllFields ? 'All fields required' : 'Partial responses allowed'}</strong>
              </div>
              {showRespondentPdfDownloadToggle ? (
                <div>
                  <span>Respondent PDF</span>
                  <strong>{fillLinkRespondentPdfDownloadEnabled(link) ? 'Download enabled' : 'Owner only'}</strong>
                </div>
              ) : null}
            </div>
            {publicUrl ? (
              <div className="fill-link-dialog__share-row">
                <input
                  className="fill-link-dialog__share-input"
                  type="text"
                  readOnly
                  value={publicUrl}
                  aria-label={`${heading} URL`}
                />
                <button type="button" className="ui-button ui-button--ghost" onClick={handleCopyLink}>
                  Copy
                </button>
              </div>
            ) : null}
            <div className="fill-link-dialog__actions">
              <button
                type="button"
                className="ui-button ui-button--primary"
                onClick={() => onPublish({ requireAllFields, allowRespondentPdfDownload })}
                disabled={publishing}
              >
                {publishing ? 'Refreshing…' : 'Refresh form schema'}
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => onRefresh(query)}
                disabled={loadingResponses || loadingLink}
              >
                {loadingResponses ? 'Refreshing responses…' : 'Refresh responses'}
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => onCloseLink({ requireAllFields, allowRespondentPdfDownload })}
                disabled={closing}
              >
                {closing ? (link.status === 'active' ? 'Closing…' : 'Reopening…') : (link.status === 'active' ? 'Close link' : 'Reopen link')}
              </button>
            </div>
          </section>

          <section className="fill-link-dialog__section">
            <div className="fill-link-dialog__section-header fill-link-dialog__section-header--compact">
              <div>
                <h3>Respondents</h3>
                <p>Choose a respondent, then apply their answers in Search &amp; Fill.</p>
              </div>
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={onUseResponsesAsSearchFill}
                disabled={responses.length === 0}
              >
                Open Search &amp; Fill
              </button>
            </div>
            <label className="fill-link-dialog__search">
              <span>Search respondents</span>
              <input
                type="search"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="Name, email, phone, or answer"
              />
            </label>
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
                    <div>
                      <strong>{response.respondentLabel}</strong>
                      <p>{response.respondentSecondaryLabel || formatDateLabel(response.submittedAt)}</p>
                    </div>
                    <button
                      type="button"
                      className="ui-button ui-button--primary ui-button--compact"
                      onClick={() => onApplyResponse(response)}
                    >
                      Apply to PDF
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}

export function FillLinkManagerDialog({
  open,
  onClose,
  templateName,
  hasActiveTemplate,
  groupName,
  hasActiveGroup,
  limits,
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
  const [templateQuery, setTemplateQuery] = useState('');
  const [groupQuery, setGroupQuery] = useState('');
  const [templateRequireAllFields, setTemplateRequireAllFields] = useState(false);
  const [templateAllowRespondentPdfDownload, setTemplateAllowRespondentPdfDownload] = useState(false);
  const [groupRequireAllFields, setGroupRequireAllFields] = useState(false);
  const previousTemplateQueryRef = useRef('');
  const previousGroupQueryRef = useRef('');
  const refreshTemplateResponses = useEffectEvent((search?: string) => {
    if (typeof search === 'undefined') {
      onRefreshTemplate();
      return;
    }
    onRefreshTemplate(search);
  });
  const searchTemplateResponses = useEffectEvent((search: string) => {
    onSearchTemplateResponses(search);
  });
  const refreshGroupResponses = useEffectEvent((search?: string) => {
    if (typeof search === 'undefined') {
      onRefreshGroup();
      return;
    }
    onRefreshGroup(search);
  });
  const searchGroupResponses = useEffectEvent((search: string) => {
    onSearchGroupResponses(search);
  });

  useEffect(() => {
    if (!open) return;
    setTemplateRequireAllFields(Boolean(templateLink?.requireAllFields));
    setTemplateAllowRespondentPdfDownload(fillLinkRespondentPdfDownloadEnabled(templateLink));
  }, [open, templateLink?.id, templateLink?.requireAllFields, templateLink?.allowRespondentPdfDownload, templateLink?.respondentPdfDownloadEnabled]);

  useEffect(() => {
    if (!open) return;
    setGroupRequireAllFields(Boolean(groupLink?.requireAllFields));
  }, [groupLink?.id, groupLink?.requireAllFields, open]);

  useEffect(() => {
    if (open) return;
    setTemplateQuery('');
    setGroupQuery('');
    previousTemplateQueryRef.current = '';
    previousGroupQueryRef.current = '';
  }, [open]);

  useEffect(() => {
    if (!open) return;
    previousTemplateQueryRef.current = '';
    setTemplateQuery('');
  }, [hasActiveTemplate, open, templateLink?.id, templateName]);

  useEffect(() => {
    if (!open) return;
    previousGroupQueryRef.current = '';
    setGroupQuery('');
  }, [groupLink?.id, groupName, hasActiveGroup, open]);

  useEffect(() => {
    if (!open) {
      previousTemplateQueryRef.current = '';
      return;
    }
    if (!hasActiveTemplate) return;
    const trimmedQuery = templateQuery.trim();
    const previousQuery = previousTemplateQueryRef.current;
    previousTemplateQueryRef.current = trimmedQuery;
    if (!trimmedQuery && !previousQuery) return;
    const timeoutId = window.setTimeout(() => {
      if (trimmedQuery) {
        searchTemplateResponses(trimmedQuery);
        return;
      }
      refreshTemplateResponses();
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [hasActiveTemplate, open, templateQuery]);

  useEffect(() => {
    if (!open) {
      previousGroupQueryRef.current = '';
      return;
    }
    if (!hasActiveGroup) return;
    const trimmedQuery = groupQuery.trim();
    const previousQuery = previousGroupQueryRef.current;
    previousGroupQueryRef.current = trimmedQuery;
    if (!trimmedQuery && !previousQuery) return;
    const timeoutId = window.setTimeout(() => {
      if (trimmedQuery) {
        searchGroupResponses(trimmedQuery);
        return;
      }
      refreshGroupResponses();
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [groupQuery, hasActiveGroup, open]);

  const description = hasActiveGroup
    ? `Publish a saved-template Fill By Link for ${templateName || 'the active template'} or publish one group form for ${groupName || 'the open group'} that merges every distinct field across the group.`
    : hasActiveTemplate
      ? `Publish a DullyPDF-hosted mobile form for ${templateName || 'the current template'}, collect respondent answers, then fill the PDF later from the response list or let respondents download their submitted template copy after submit.`
      : 'Open a saved template first. Fill By Link only publishes saved templates or open groups.';

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Fill By Link"
      description={description}
      className="fill-link-dialog"
    >
      <div className="fill-link-dialog__body">
        <div className="fill-link-dialog__limits">
          <div className="fill-link-dialog__limit-card">
            <span className="fill-link-dialog__limit-label">Active links</span>
            <strong>{limits.fillLinksActiveMax}</strong>
          </div>
          <div className="fill-link-dialog__limit-card">
            <span className="fill-link-dialog__limit-label">Responses per link</span>
            <strong>{limits.fillLinkResponsesMax.toLocaleString()}</strong>
          </div>
        </div>

        {!hasActiveTemplate && !hasActiveGroup ? (
          <div className="fill-link-dialog__empty">
            <p>Load a saved template or open a group in the workspace, then publish Fill By Link from here.</p>
          </div>
        ) : null}

        {hasActiveTemplate ? (
          <FillLinkSection
            heading="Template Fill By Link"
            summary={`Publish a link just for ${templateName || 'the active template'}.`}
            emptyMessage="No Fill By Link is live for this template yet."
            link={templateLink}
            responses={templateResponses}
            loadingLink={templateLoadingLink}
            publishing={templatePublishing}
            closing={templateClosing}
            loadingResponses={templateLoadingResponses}
            error={templateError}
            query={templateQuery}
            requireAllFields={templateRequireAllFields}
            showRespondentPdfDownloadToggle
            allowRespondentPdfDownload={templateAllowRespondentPdfDownload}
            onQueryChange={setTemplateQuery}
            onRequireAllFieldsChange={setTemplateRequireAllFields}
            onAllowRespondentPdfDownloadChange={setTemplateAllowRespondentPdfDownload}
            onPublish={onPublishTemplate}
            onRefresh={onRefreshTemplate}
            onCloseLink={onCloseTemplateLink}
            onApplyResponse={onApplyTemplateResponse}
            onUseResponsesAsSearchFill={onUseTemplateResponsesAsSearchFill}
          />
        ) : null}

        {hasActiveGroup ? (
          <FillLinkSection
            heading="Group Fill By Link"
            summary={`Publish one merged respondent form for ${groupName || 'the open group'} using every distinct field across the group.`}
            emptyMessage="No group Fill By Link is live for this group yet."
            link={groupLink}
            responses={groupResponses}
            loadingLink={groupLoadingLink}
            publishing={groupPublishing}
            closing={groupClosing}
            loadingResponses={groupLoadingResponses}
            error={groupError}
            query={groupQuery}
            requireAllFields={groupRequireAllFields}
            onQueryChange={setGroupQuery}
            onRequireAllFieldsChange={setGroupRequireAllFields}
            onPublish={onPublishGroup}
            onRefresh={onRefreshGroup}
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
