import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  BannerNotice,
  CheckboxRule,
  PdfField,
  TextTransformRule,
} from '../types';
import {
  ApiService,
  type FillLinkGroupTemplatePayload,
  type FillLinkResponse,
  type FillLinkSigningConfig,
  type FillLinkSummary,
  type FillLinkTemplateFieldPayload,
  type FillLinkWebFormConfig,
} from '../services/api';
import { buildFillLinkTemplateFields } from '../utils/fillLinks';

type UseFillLinksDeps = {
  verifiedUser: unknown;
  enabled?: boolean;
  scopeType: 'template' | 'group';
  scopeId: string | null;
  scopeName: string | null;
  fields: PdfField[];
  checkboxRules: CheckboxRule[];
  setBannerNotice: (notice: BannerNotice | null) => void;
};

const DEFAULT_FILL_LINK_RESPONSE_LIMIT = 100;
const SEARCH_FILL_LINK_RESPONSE_LIMIT = 200;
const MAX_FILL_LINK_RESPONSE_LIMIT = 10000;

export function useFillLinks(deps: UseFillLinksDeps) {
  const [currentLink, setCurrentLink] = useState<FillLinkSummary | null>(null);
  const [responses, setResponses] = useState<FillLinkResponse[]>([]);
  const [loadingLink, setLoadingLink] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [closing, setClosing] = useState(false);
  const [loadingResponses, setLoadingResponses] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scopeLabel = deps.scopeType === 'group' ? 'group' : 'template';
  const scopeKeyRef = useRef(`${deps.scopeType}:${deps.scopeId ?? ''}`);
  const currentLinkRef = useRef<FillLinkSummary | null>(null);
  const responsesRef = useRef<FillLinkResponse[]>([]);
  const scopeRequestVersionRef = useRef(0);
  const responsesRequestVersionRef = useRef(0);
  const mountedRef = useRef(true);

  const canManageFillLinks = useMemo(
    () => Boolean(deps.verifiedUser && deps.scopeId),
    [deps.scopeId, deps.verifiedUser],
  );

  useEffect(() => {
    currentLinkRef.current = currentLink;
  }, [currentLink]);

  useEffect(() => {
    responsesRef.current = responses;
  }, [responses]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      scopeRequestVersionRef.current += 1;
      responsesRequestVersionRef.current += 1;
    };
  }, []);

  const reset = useCallback(() => {
    scopeRequestVersionRef.current += 1;
    responsesRequestVersionRef.current += 1;
    currentLinkRef.current = null;
    responsesRef.current = [];
    setCurrentLink(null);
    setResponses([]);
    setLoadingLink(false);
    setPublishing(false);
    setClosing(false);
    setLoadingResponses(false);
    setError(null);
  }, []);

  const fetchResponsesForLink = useCallback(async (
    linkId: string,
    options?: { search?: string; limit?: number },
  ) => {
    const requestVersion = responsesRequestVersionRef.current + 1;
    responsesRequestVersionRef.current = requestVersion;
    setLoadingResponses(true);
    setError(null);
    try {
      const payload = await ApiService.getFillLinkResponses(linkId, {
        search: options?.search,
        limit: Math.min(options?.limit ?? DEFAULT_FILL_LINK_RESPONSE_LIMIT, MAX_FILL_LINK_RESPONSE_LIMIT),
      });
      if (!mountedRef.current || responsesRequestVersionRef.current !== requestVersion) {
        return responsesRef.current;
      }
      currentLinkRef.current = payload.link;
      responsesRef.current = payload.responses;
      setCurrentLink(payload.link);
      setResponses(payload.responses);
      return payload.responses;
    } finally {
      if (mountedRef.current && responsesRequestVersionRef.current === requestVersion) {
        setLoadingResponses(false);
      }
    }
  }, []);

  const loadResponses = useCallback(
    async (options?: { search?: string; limit?: number }) => {
      if (!currentLink?.id) {
        setResponses([]);
        return [];
      }
      try {
        return await fetchResponsesForLink(currentLink.id, options);
      } catch (nextError) {
        const message = nextError instanceof Error ? nextError.message : 'Failed to load respondent responses.';
        setError(message);
        deps.setBannerNotice({ tone: 'error', message });
        return [];
      }
    },
    [currentLink?.id, deps.setBannerNotice, fetchResponsesForLink],
  );

  const loadCurrentScopeLink = useCallback(async () => {
    if (!deps.verifiedUser || !deps.scopeId) {
      reset();
      return null;
    }
    const requestVersion = scopeRequestVersionRef.current + 1;
    scopeRequestVersionRef.current = requestVersion;
    setLoadingLink(true);
    setError(null);
    try {
      const links = await ApiService.getFillLinks(
        deps.scopeType === 'group'
          ? { groupId: deps.scopeId, scopeType: 'group' }
          : { templateId: deps.scopeId, scopeType: 'template' },
      );
      if (!mountedRef.current || scopeRequestVersionRef.current !== requestVersion) {
        return currentLinkRef.current;
      }
      const nextLink = links[0] ?? null;
      currentLinkRef.current = nextLink;
      setCurrentLink(nextLink);
      if (!nextLink) {
        responsesRef.current = [];
        setResponses([]);
        return null;
      }
      if (nextLink.id) {
        void fetchResponsesForLink(nextLink.id).catch((responseError) => {
          if (!mountedRef.current || scopeRequestVersionRef.current !== requestVersion) {
            return;
          }
          const message = responseError instanceof Error ? responseError.message : 'Failed to load respondent responses.';
          setError(message);
          deps.setBannerNotice({ tone: 'error', message });
        });
      }
      return nextLink;
    } catch (nextError) {
      if (!mountedRef.current || scopeRequestVersionRef.current !== requestVersion) {
        return currentLinkRef.current;
      }
      const message = nextError instanceof Error ? nextError.message : `Failed to load ${scopeLabel} Fill By Link.`;
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
      return null;
    } finally {
      if (mountedRef.current && scopeRequestVersionRef.current === requestVersion) {
        setLoadingLink(false);
      }
    }
  }, [deps.scopeId, deps.scopeType, deps.setBannerNotice, deps.verifiedUser, fetchResponsesForLink, reset, scopeLabel]);

  const refreshForScope = useCallback(async () => {
    return loadCurrentScopeLink();
  }, [loadCurrentScopeLink]);

  const publishCurrentScope = useCallback(async () => {
    if (!deps.verifiedUser) {
      deps.setBannerNotice({ tone: 'error', message: 'Sign in to publish Fill By Link.' });
      return null;
    }
    if (!deps.scopeId) {
      deps.setBannerNotice({ tone: 'error', message: `Open a saved ${scopeLabel} before publishing Fill By Link.` });
      return null;
    }
    if (!deps.fields.length) {
      deps.setBannerNotice({ tone: 'error', message: `The current ${scopeLabel} has no fields to publish.` });
      return null;
    }
    setPublishing(true);
    setError(null);
    try {
      const nextLink = await ApiService.createFillLink({
        scopeType: deps.scopeType,
        templateId: deps.scopeType === 'template' ? deps.scopeId : undefined,
        templateName: deps.scopeType === 'template' ? (deps.scopeName || undefined) : undefined,
        groupId: deps.scopeType === 'group' ? deps.scopeId : undefined,
        groupName: deps.scopeType === 'group' ? (deps.scopeName || undefined) : undefined,
        title: deps.scopeName || undefined,
        requireAllFields: false,
        fields: buildFillLinkTemplateFields(deps.fields),
        checkboxRules: deps.checkboxRules,
      });
      setCurrentLink(nextLink);
      if (nextLink.id) {
        await fetchResponsesForLink(nextLink.id);
      }
      deps.setBannerNotice({
        tone: 'success',
        message: nextLink.status === 'active' ? 'Fill By Link is live.' : 'Fill By Link was updated.',
        autoDismissMs: 6000,
      });
      return nextLink;
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : 'Failed to publish Fill By Link.';
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
      return null;
    } finally {
      setPublishing(false);
    }
  }, [
    deps.checkboxRules,
    deps.fields,
    deps.scopeId,
    deps.scopeName,
    deps.scopeType,
    deps.setBannerNotice,
    deps.verifiedUser,
    fetchResponsesForLink,
    scopeLabel,
  ]);

  const publish = useCallback(async (payload: {
    scopeType?: 'template' | 'group';
    templateId?: string;
    templateName?: string | null;
    groupId?: string;
    groupName?: string | null;
    title?: string | null;
    requireAllFields?: boolean;
    allowRespondentPdfDownload?: boolean;
    allowRespondentEditablePdfDownload?: boolean;
    webFormConfig?: FillLinkWebFormConfig;
    signingConfig?: FillLinkSigningConfig;
    fields: FillLinkTemplateFieldPayload[];
    checkboxRules?: Array<Record<string, unknown>>;
    textTransformRules?: TextTransformRule[];
    groupTemplates?: FillLinkGroupTemplatePayload[];
  }) => {
    setPublishing(true);
    setError(null);
    try {
      const nextLink = await ApiService.createFillLink({
        scopeType: payload.scopeType,
        templateId: payload.templateId,
        templateName: payload.templateName || undefined,
        groupId: payload.groupId,
        groupName: payload.groupName || undefined,
        title: payload.title || undefined,
        requireAllFields: payload.requireAllFields,
        allowRespondentPdfDownload: payload.allowRespondentPdfDownload,
        allowRespondentEditablePdfDownload: payload.allowRespondentEditablePdfDownload,
        webFormConfig: payload.webFormConfig,
        signingConfig: payload.signingConfig,
        fields: payload.fields,
        checkboxRules: payload.checkboxRules,
        textTransformRules: payload.textTransformRules,
        groupTemplates: payload.groupTemplates,
      });
      setCurrentLink(nextLink);
      if (nextLink.id) {
        await fetchResponsesForLink(nextLink.id);
      }
      return nextLink;
    } finally {
      setPublishing(false);
    }
  }, [fetchResponsesForLink]);

  const closeCurrentLink = useCallback(async () => {
    if (!currentLink?.id) return null;
    setClosing(true);
    setError(null);
    try {
      const nextLink = await ApiService.closeFillLink(currentLink.id);
      setCurrentLink(nextLink);
      deps.setBannerNotice({
        tone: 'warning',
        message: 'Fill By Link has been closed.',
        autoDismissMs: 6000,
      });
      return nextLink;
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : 'Failed to close Fill By Link.';
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
      return null;
    } finally {
      setClosing(false);
    }
  }, [currentLink?.id, deps.setBannerNotice]);

  const closeLink = useCallback(async (linkId: string) => {
    setClosing(true);
    setError(null);
    try {
      const nextLink = await ApiService.closeFillLink(linkId);
      setCurrentLink(nextLink);
      return nextLink;
    } finally {
      setClosing(false);
    }
  }, []);

  const reopenLink = useCallback(async (
    linkId: string,
    payload: {
      title?: string;
      groupName?: string;
      requireAllFields?: boolean;
      allowRespondentPdfDownload?: boolean;
      allowRespondentEditablePdfDownload?: boolean;
      webFormConfig?: FillLinkWebFormConfig;
      signingConfig?: FillLinkSigningConfig;
      fields?: FillLinkTemplateFieldPayload[];
      checkboxRules?: Array<Record<string, unknown>>;
      textTransformRules?: TextTransformRule[];
      groupTemplates?: FillLinkGroupTemplatePayload[];
    },
  ) => {
    setPublishing(true);
    setError(null);
    try {
      const nextLink = await ApiService.updateFillLink(linkId, {
        ...payload,
        status: 'active',
      });
      setCurrentLink(nextLink);
      if (nextLink.id) {
        await fetchResponsesForLink(nextLink.id);
      }
      return nextLink;
    } finally {
      setPublishing(false);
    }
  }, [fetchResponsesForLink]);

  const refreshResponses = useCallback(async (
    linkId: string,
    options?: { search?: string; limit?: number },
  ) => {
    return fetchResponsesForLink(linkId, options);
  }, [fetchResponsesForLink]);

  const searchResponses = useCallback(async (query: string) => {
    const trimmed = query.trim();
    if (!currentLink?.id) {
      setResponses([]);
      return [];
    }
    return refreshResponses(currentLink.id, {
      search: trimmed || undefined,
      limit: trimmed ? SEARCH_FILL_LINK_RESPONSE_LIMIT : DEFAULT_FILL_LINK_RESPONSE_LIMIT,
    });
  }, [currentLink?.id, refreshResponses]);

  const loadAllResponses = useCallback(async (limitHint?: number) => {
    if (!currentLink?.id) {
      setResponses([]);
      return [];
    }
    const nextLimit = Math.min(
      Math.max(limitHint ?? currentLink.responseCount ?? DEFAULT_FILL_LINK_RESPONSE_LIMIT, DEFAULT_FILL_LINK_RESPONSE_LIMIT),
      MAX_FILL_LINK_RESPONSE_LIMIT,
    );
    return refreshResponses(currentLink.id, { limit: nextLimit });
  }, [currentLink?.id, currentLink?.responseCount, refreshResponses]);

  useEffect(() => {
    const nextScopeKey = `${deps.scopeType}:${deps.scopeId ?? ''}`;
    if (scopeKeyRef.current === nextScopeKey) return;
    scopeKeyRef.current = nextScopeKey;
    reset();
  }, [deps.scopeId, deps.scopeType, reset]);

  useEffect(() => {
    if (!deps.enabled) return;
    void loadCurrentScopeLink();
  }, [deps.enabled, loadCurrentScopeLink]);

  return {
    currentLink,
    activeLink: currentLink,
    responses,
    loading: loadingLink,
    loadingLink,
    publishing,
    closing,
    responsesLoading: loadingResponses,
    loadingResponses,
    error,
    canManageFillLinks,
    publishCurrentScope,
    publish,
    closeCurrentLink,
    closeLink,
    reopenLink,
    refreshForScope,
    refreshResponses,
    searchResponses,
    loadAllResponses,
    loadCurrentScopeLink,
    loadResponses,
    reset,
    clear: reset,
  };
}
