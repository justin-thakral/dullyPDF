import { useCallback, useEffect, useMemo } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type {
  BannerNotice,
  CheckboxHint,
  CheckboxRule,
  PdfField,
  TextTransformRule,
} from '../types';
import type {
  FillLinkGroupTemplatePayload,
  FillLinkResponse,
  FillLinkSummary,
  FillLinkTemplateFieldPayload,
  ProfileLimits,
  SavedFormSummary,
} from '../services/api';
import type { FillLinkManagerDialogProps } from '../components/features/FillLinkManagerDialog';
import { useFillLinks } from './useFillLinks';
import {
  buildFillLinkPublishFingerprint,
  buildFillLinkResponseRows,
  buildFillLinkTemplateFields,
  FILL_LINK_RESPONSE_ID_KEY,
  FILL_LINK_RESPONDENT_LABEL_KEY,
  fillLinkRespondentPdfDownloadEnabled,
} from '../utils/fillLinks';

type SearchFillPresetState = {
  query: string;
  searchKey?: string;
  searchMode?: 'contains' | 'equals';
  autoRun?: boolean;
  autoFillOnSearch?: boolean;
  highlightResult?: boolean;
  token: number;
} | null;

type GroupTemplateSnapshot = {
  fields: PdfField[];
  checkboxRules: CheckboxRule[];
};

type StructuredDataSourcePayload = {
  kind: 'respondent';
  label: string;
  rows: Array<Record<string, unknown>>;
  columns: string[];
  identifierKey: string;
};

type UseWorkspaceFillLinksDeps = {
  verifiedUser: unknown;
  profileLimits: ProfileLimits;
  managerOpen: boolean;
  setManagerOpen: Dispatch<SetStateAction<boolean>>;
  setBannerNotice: (notice: BannerNotice | null) => void;
  activeTemplateId: string | null;
  activeTemplateName: string | null;
  activeGroupId: string | null;
  activeGroupName: string | null;
  activeGroupTemplates: SavedFormSummary[];
  fields: PdfField[];
  checkboxRules: CheckboxRule[];
  checkboxHints: CheckboxHint[];
  textTransformRules: TextTransformRule[];
  savedFillLinkPublishFingerprint: string | null;
  resolveGroupTemplateDirtyNames: () => string[];
  ensureGroupTemplateSnapshot: (formId: string, templateNameHint?: string | null) => Promise<GroupTemplateSnapshot>;
  applyStructuredDataSource: (payload: StructuredDataSourcePayload) => void;
  clearFieldValues: () => void;
  setSearchFillPreset: Dispatch<SetStateAction<SearchFillPresetState>>;
  setShowSearchFill: Dispatch<SetStateAction<boolean>>;
  bumpSearchFillSession: () => void;
};

type SearchFillLink = Pick<FillLinkSummary, 'id' | 'responseCount' | 'scopeType' | 'groupName' | 'templateName'> | null;

export function useWorkspaceFillLinks(deps: UseWorkspaceFillLinksDeps) {
  const {
    verifiedUser,
    profileLimits,
    managerOpen,
    setManagerOpen,
    setBannerNotice,
    activeTemplateId,
    activeTemplateName,
    activeGroupId,
    activeGroupName,
    activeGroupTemplates,
    fields,
    checkboxRules,
    checkboxHints,
    textTransformRules,
    savedFillLinkPublishFingerprint,
    resolveGroupTemplateDirtyNames,
    ensureGroupTemplateSnapshot,
    applyStructuredDataSource,
    clearFieldValues,
    setSearchFillPreset,
    setShowSearchFill,
    bumpSearchFillSession,
  } = deps;

  const hasActiveTemplateScope = Boolean(activeTemplateId && fields.length > 0);
  const hasActiveGroupScope = Boolean(activeGroupId && activeGroupTemplates.length > 0);
  const canManageFillLink = Boolean(verifiedUser && (hasActiveTemplateScope || hasActiveGroupScope));

  const templateFillLinks = useFillLinks({
    verifiedUser,
    enabled: managerOpen,
    scopeType: 'template',
    scopeId: activeTemplateId,
    scopeName: activeTemplateName,
    fields,
    checkboxRules,
    setBannerNotice,
  });
  const groupFillLinks = useFillLinks({
    verifiedUser,
    enabled: managerOpen && Boolean(activeGroupId),
    scopeType: 'group',
    scopeId: activeGroupId,
    scopeName: activeGroupName,
    fields,
    checkboxRules,
    setBannerNotice,
  });
  const {
    activeLink: activeTemplateLink,
    responses: templateResponses,
    loading: templateLoadingLink,
    publishing: templatePublishing,
    closing: templateClosing,
    responsesLoading: templateResponsesLoading,
    error: templateError,
    clear: clearTemplateFillLinks,
    refreshForScope: refreshTemplateLinkScope,
    publish: publishTemplateLink,
    closeLink: closeTemplateLink,
    reopenLink: reopenTemplateLink,
    refreshResponses: refreshTemplateLinkResponses,
    searchResponses: searchTemplateLinkResponses,
    loadAllResponses: loadAllTemplateResponses,
  } = templateFillLinks;
  const {
    activeLink: activeGroupLink,
    responses: groupResponses,
    loading: groupLoadingLink,
    publishing: groupPublishing,
    closing: groupClosing,
    responsesLoading: groupResponsesLoading,
    error: groupError,
    clear: clearGroupFillLinks,
    refreshForScope: refreshGroupLinkScope,
    publish: publishGroupLink,
    closeLink: closeGroupLink,
    reopenLink: reopenGroupLink,
    refreshResponses: refreshGroupLinkResponses,
    searchResponses: searchGroupLinkResponses,
    loadAllResponses: loadAllGroupResponses,
  } = groupFillLinks;

  const fillLinkSchemaDirty = useMemo(() => {
    if (!activeTemplateId || savedFillLinkPublishFingerprint === null) {
      return false;
    }
    return buildFillLinkPublishFingerprint(fields, checkboxRules) !== savedFillLinkPublishFingerprint;
  }, [activeTemplateId, checkboxRules, fields, savedFillLinkPublishFingerprint]);

  const serializeCurrentFillLinkFields = useCallback(
    (): FillLinkTemplateFieldPayload[] => buildFillLinkTemplateFields(fields),
    [fields],
  );

  useEffect(() => {
    if (!managerOpen) {
      clearTemplateFillLinks();
      return;
    }
    if (!verifiedUser || (!activeTemplateId && !hasActiveGroupScope)) {
      clearTemplateFillLinks();
      setManagerOpen(false);
      return;
    }
    if (!activeTemplateId) {
      clearTemplateFillLinks();
      return;
    }
    void refreshTemplateLinkScope().catch((error) => {
      const message = error instanceof Error ? error.message : 'Failed to load Fill By Link details.';
      setBannerNotice({ tone: 'error', message });
    });
  }, [
    activeTemplateId,
    clearTemplateFillLinks,
    hasActiveGroupScope,
    managerOpen,
    refreshTemplateLinkScope,
    setBannerNotice,
    setManagerOpen,
    verifiedUser,
  ]);

  useEffect(() => {
    if (!managerOpen) {
      clearGroupFillLinks();
      return;
    }
    if (!verifiedUser || !activeGroupId) {
      clearGroupFillLinks();
      return;
    }
    void refreshGroupLinkScope().catch((error) => {
      const message = error instanceof Error ? error.message : 'Failed to load group Fill By Link details.';
      setBannerNotice({ tone: 'error', message });
    });
  }, [
    activeGroupId,
    clearGroupFillLinks,
    managerOpen,
    refreshGroupLinkScope,
    setBannerNotice,
    verifiedUser,
  ]);

  const guardDirtyTemplateSchema = useCallback(() => {
    if (!fillLinkSchemaDirty) return false;
    setBannerNotice({
      tone: 'error',
      message: 'Save this template before publishing or refreshing Fill By Link.',
      autoDismissMs: 7000,
    });
    return true;
  }, [fillLinkSchemaDirty, setBannerNotice]);

  const guardDirtyGroupSchema = useCallback(() => {
    const dirtyTemplateNames = resolveGroupTemplateDirtyNames();
    if (dirtyTemplateNames.length === 0) return false;
    setBannerNotice({
      tone: 'error',
      message: 'Save every edited template in this group before publishing or refreshing Group Fill By Link.',
      autoDismissMs: 7000,
    });
    return true;
  }, [resolveGroupTemplateDirtyNames, setBannerNotice]);

  const buildGroupFillLinkTemplateSources = useCallback(async (): Promise<FillLinkGroupTemplatePayload[]> => {
    if (!activeGroupId || activeGroupTemplates.length === 0) {
      throw new Error('Open a group before publishing Group Fill By Link.');
    }
    const groupTemplateSources: FillLinkGroupTemplatePayload[] = [];
    for (const template of activeGroupTemplates) {
      if (template.id === activeTemplateId) {
        groupTemplateSources.push({
          templateId: template.id,
          templateName: template.name,
          fields: serializeCurrentFillLinkFields(),
          checkboxRules: checkboxRules as Array<Record<string, unknown>>,
        });
        continue;
      }
      const snapshot = await ensureGroupTemplateSnapshot(template.id, template.name);
      groupTemplateSources.push({
        templateId: template.id,
        templateName: template.name,
        fields: buildFillLinkTemplateFields(snapshot.fields),
        checkboxRules: snapshot.checkboxRules as Array<Record<string, unknown>>,
      });
    }
    return groupTemplateSources;
  }, [
    activeGroupId,
    activeGroupTemplates,
    activeTemplateId,
    checkboxRules,
    ensureGroupTemplateSnapshot,
    serializeCurrentFillLinkFields,
  ]);

  const handleOpenFillLinkManager = useCallback(() => {
    if (!verifiedUser) {
      setBannerNotice({ tone: 'error', message: 'Sign in to use Fill By Link.' });
      return;
    }
    if (!hasActiveTemplateScope && !hasActiveGroupScope) {
      setBannerNotice({ tone: 'error', message: 'Load a saved form or open a group before publishing Fill By Link.' });
      return;
    }
    setManagerOpen(true);
  }, [hasActiveGroupScope, hasActiveTemplateScope, setBannerNotice, setManagerOpen, verifiedUser]);

  const handlePublishTemplate = useCallback(async (options?: {
    requireAllFields?: boolean;
    allowRespondentPdfDownload?: boolean;
  }) => {
    if (!activeTemplateId) return;
    if (guardDirtyTemplateSchema()) return;
    try {
      await publishTemplateLink({
        scopeType: 'template',
        templateId: activeTemplateId,
        templateName: activeTemplateName,
        title: activeTemplateName || 'Fill By Link',
        requireAllFields: Boolean(options?.requireAllFields),
        allowRespondentPdfDownload: Boolean(options?.allowRespondentPdfDownload),
        fields: serializeCurrentFillLinkFields(),
        checkboxRules: checkboxRules as Array<Record<string, unknown>>,
        checkboxHints: checkboxHints as CheckboxHint[],
        textTransformRules: textTransformRules as TextTransformRule[],
      });
      setBannerNotice({
        tone: 'success',
        message: 'Fill By Link is live. Share the public link with respondents.',
        autoDismissMs: 6000,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to publish Fill By Link.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [
    activeTemplateId,
    activeTemplateName,
    checkboxHints,
    checkboxRules,
    guardDirtyTemplateSchema,
    publishTemplateLink,
    serializeCurrentFillLinkFields,
    setBannerNotice,
    textTransformRules,
  ]);

  const handlePublishGroup = useCallback(async (options?: { requireAllFields?: boolean }) => {
    if (!activeGroupId) return;
    if (guardDirtyGroupSchema()) return;
    try {
      const groupTemplates = await buildGroupFillLinkTemplateSources();
      await publishGroupLink({
        scopeType: 'group',
        groupId: activeGroupId,
        groupName: activeGroupName,
        title: activeGroupName || 'Group Fill By Link',
        requireAllFields: Boolean(options?.requireAllFields),
        fields: [],
        groupTemplates,
      });
      setBannerNotice({
        tone: 'success',
        message: 'Group Fill By Link is live. Share the public link with respondents.',
        autoDismissMs: 6000,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to publish Group Fill By Link.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [
    activeGroupId,
    activeGroupName,
    buildGroupFillLinkTemplateSources,
    guardDirtyGroupSchema,
    publishGroupLink,
    setBannerNotice,
  ]);

  const handleCloseTemplate = useCallback(async () => {
    const linkId = activeTemplateLink?.id;
    if (!linkId) return;
    try {
      await closeTemplateLink(linkId);
      setBannerNotice({ tone: 'info', message: 'Fill By Link closed.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to close Fill By Link.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [activeTemplateLink, closeTemplateLink, setBannerNotice]);

  const handleReopenTemplate = useCallback(async (options?: {
    requireAllFields?: boolean;
    allowRespondentPdfDownload?: boolean;
  }) => {
    const activeLink = activeTemplateLink;
    const linkId = activeLink?.id;
    if (!activeLink || !linkId) return;
    if (guardDirtyTemplateSchema()) return;
    try {
      await reopenTemplateLink(linkId, {
        title: activeTemplateName || activeLink.title || undefined,
        requireAllFields: options?.requireAllFields ?? activeLink.requireAllFields,
        allowRespondentPdfDownload:
          options?.allowRespondentPdfDownload
          ?? fillLinkRespondentPdfDownloadEnabled(activeLink),
        fields: serializeCurrentFillLinkFields(),
        checkboxRules: checkboxRules as Array<Record<string, unknown>>,
        checkboxHints: checkboxHints as CheckboxHint[],
        textTransformRules: textTransformRules as TextTransformRule[],
      });
      setBannerNotice({ tone: 'success', message: 'Fill By Link reopened.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to reopen Fill By Link.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [
    activeTemplateLink,
    activeTemplateName,
    checkboxHints,
    checkboxRules,
    guardDirtyTemplateSchema,
    reopenTemplateLink,
    serializeCurrentFillLinkFields,
    setBannerNotice,
    textTransformRules,
  ]);

  const handleCloseGroup = useCallback(async () => {
    const linkId = activeGroupLink?.id;
    if (!linkId) return;
    try {
      await closeGroupLink(linkId);
      setBannerNotice({ tone: 'info', message: 'Group Fill By Link closed.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to close Group Fill By Link.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [activeGroupLink, closeGroupLink, setBannerNotice]);

  const handleReopenGroup = useCallback(async (options?: { requireAllFields?: boolean }) => {
    const activeLink = activeGroupLink;
    const linkId = activeLink?.id;
    if (!activeLink || !linkId || !activeGroupId) return;
    if (guardDirtyGroupSchema()) return;
    try {
      const groupTemplates = await buildGroupFillLinkTemplateSources();
      await reopenGroupLink(linkId, {
        title: activeGroupName || activeLink.title || undefined,
        groupName: activeGroupName || undefined,
        requireAllFields: options?.requireAllFields ?? activeLink.requireAllFields,
        groupTemplates,
      });
      setBannerNotice({ tone: 'success', message: 'Group Fill By Link reopened.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to reopen Group Fill By Link.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [
    activeGroupId,
    activeGroupLink,
    activeGroupName,
    buildGroupFillLinkTemplateSources,
    guardDirtyGroupSchema,
    reopenGroupLink,
    setBannerNotice,
  ]);

  const handleRefreshTemplateResponses = useCallback(async (search?: string) => {
    const linkId = activeTemplateLink?.id;
    if (!linkId) return;
    try {
      await refreshTemplateLinkResponses(linkId, {
        search: search?.trim() || undefined,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to refresh Fill By Link responses.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [activeTemplateLink, refreshTemplateLinkResponses, setBannerNotice]);

  const handleRefreshGroupResponses = useCallback(async (search?: string) => {
    const linkId = activeGroupLink?.id;
    if (!linkId) return;
    try {
      await refreshGroupLinkResponses(linkId, {
        search: search?.trim() || undefined,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to refresh Group Fill By Link responses.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [activeGroupLink, refreshGroupLinkResponses, setBannerNotice]);

  const handleSearchTemplateResponses = useCallback(async (search: string) => {
    try {
      await searchTemplateLinkResponses(search);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to search Fill By Link responses.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [searchTemplateLinkResponses, setBannerNotice]);

  const handleSearchGroupResponses = useCallback(async (search: string) => {
    try {
      await searchGroupLinkResponses(search);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to search Group Fill By Link responses.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [searchGroupLinkResponses, setBannerNotice]);

  const applyFillLinkResponsesAsDataSource = useCallback((responses: FillLinkResponse[], link: SearchFillLink) => {
    const responseRows = buildFillLinkResponseRows(responses);
    const responseColumns = Array.from(new Set(responseRows.flatMap((row) => Object.keys(row))));
    const sourceLabel = link?.scopeType === 'group'
      ? `Group Fill By Link respondents: ${link.groupName || activeGroupName || 'saved group'}`
      : `Fill By Link respondents: ${link?.templateName || activeTemplateName || 'saved template'}`;
    applyStructuredDataSource({
      kind: 'respondent',
      label: sourceLabel,
      rows: responseRows,
      columns: responseColumns,
      identifierKey: FILL_LINK_RESPONDENT_LABEL_KEY,
    });
  }, [activeGroupName, activeTemplateName, applyStructuredDataSource]);

  const resolveResponsesForSearchFill = useCallback(async (
    link: Pick<FillLinkSummary, 'id' | 'responseCount'> | null,
    existingResponses: FillLinkResponse[],
    loadAllResponses: (limitHint?: number) => Promise<FillLinkResponse[]>,
  ) => {
    if (!link?.id) {
      return existingResponses;
    }
    const requestedLimit = Math.max(
      existingResponses.length,
      link.responseCount ?? existingResponses.length,
      1,
    );
    return loadAllResponses(Math.min(requestedLimit, profileLimits.fillLinkResponsesMax));
  }, [profileLimits.fillLinkResponsesMax]);

  const openResponsesInSearchFill = useCallback(async (
    response: FillLinkResponse | null,
    link: SearchFillLink,
    existingResponses: FillLinkResponse[],
    loadAllResponses: (limitHint?: number) => Promise<FillLinkResponse[]>,
  ) => {
    try {
      const searchFillResponses = await resolveResponsesForSearchFill(link, existingResponses, loadAllResponses);
      clearFieldValues();
      applyFillLinkResponsesAsDataSource(searchFillResponses, link);
      setSearchFillPreset(response ? {
        query: response.id,
        searchKey: FILL_LINK_RESPONSE_ID_KEY,
        searchMode: 'equals',
        autoRun: true,
        autoFillOnSearch: true,
        token: Date.now(),
      } : null);
      setManagerOpen(false);
      bumpSearchFillSession();
      setShowSearchFill(true);
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : 'Failed to load Fill By Link respondents for Search & Fill.';
      setBannerNotice({ tone: 'error', message });
    }
  }, [
    applyFillLinkResponsesAsDataSource,
    bumpSearchFillSession,
    clearFieldValues,
    resolveResponsesForSearchFill,
    setBannerNotice,
    setManagerOpen,
    setSearchFillPreset,
    setShowSearchFill,
  ]);

  const handleApplyTemplateResponse = useCallback(async (response: FillLinkResponse) => {
    await openResponsesInSearchFill(response, activeTemplateLink, templateResponses, loadAllTemplateResponses);
  }, [activeTemplateLink, loadAllTemplateResponses, openResponsesInSearchFill, templateResponses]);

  const handleUseTemplateResponsesAsSearchFill = useCallback(async () => {
    if (!templateResponses.length) return;
    await openResponsesInSearchFill(null, activeTemplateLink, templateResponses, loadAllTemplateResponses);
  }, [activeTemplateLink, loadAllTemplateResponses, openResponsesInSearchFill, templateResponses]);

  const handleApplyGroupResponse = useCallback(async (response: FillLinkResponse) => {
    await openResponsesInSearchFill(response, activeGroupLink, groupResponses, loadAllGroupResponses);
  }, [activeGroupLink, groupResponses, loadAllGroupResponses, openResponsesInSearchFill]);

  const handleUseGroupResponsesAsSearchFill = useCallback(async () => {
    if (!groupResponses.length) return;
    await openResponsesInSearchFill(null, activeGroupLink, groupResponses, loadAllGroupResponses);
  }, [activeGroupLink, groupResponses, loadAllGroupResponses, openResponsesInSearchFill]);

  const clearAllFillLinks = useCallback(() => {
    clearTemplateFillLinks();
    clearGroupFillLinks();
  }, [clearGroupFillLinks, clearTemplateFillLinks]);

  const dialogProps: FillLinkManagerDialogProps = useMemo(() => ({
    open: managerOpen,
    onClose: () => setManagerOpen(false),
    templateName: activeTemplateName,
    hasActiveTemplate: hasActiveTemplateScope,
    groupName: activeGroupName,
    hasActiveGroup: hasActiveGroupScope,
    limits: profileLimits,
    templateLink: activeTemplateLink,
    templateResponses,
    templateLoadingLink,
    templatePublishing,
    templateClosing,
    templateLoadingResponses: templateResponsesLoading,
    templateError,
    onPublishTemplate: handlePublishTemplate,
    onRefreshTemplate: handleRefreshTemplateResponses,
    onSearchTemplateResponses: handleSearchTemplateResponses,
    onCloseTemplateLink: activeTemplateLink?.status === 'active' ? handleCloseTemplate : handleReopenTemplate,
    onApplyTemplateResponse: handleApplyTemplateResponse,
    onUseTemplateResponsesAsSearchFill: handleUseTemplateResponsesAsSearchFill,
    groupLink: activeGroupLink,
    groupResponses,
    groupLoadingLink,
    groupPublishing,
    groupClosing,
    groupLoadingResponses: groupResponsesLoading,
    groupError,
    onPublishGroup: handlePublishGroup,
    onRefreshGroup: handleRefreshGroupResponses,
    onSearchGroupResponses: handleSearchGroupResponses,
    onCloseGroupLink: activeGroupLink?.status === 'active' ? handleCloseGroup : handleReopenGroup,
    onApplyGroupResponse: handleApplyGroupResponse,
    onUseGroupResponsesAsSearchFill: handleUseGroupResponsesAsSearchFill,
  }), [
    activeGroupLink,
    activeGroupName,
    activeTemplateLink,
    activeTemplateName,
    groupClosing,
    groupError,
    groupLoadingLink,
    groupPublishing,
    groupResponses,
    groupResponsesLoading,
    handleApplyGroupResponse,
    handleApplyTemplateResponse,
    handleCloseGroup,
    handleCloseTemplate,
    handlePublishGroup,
    handlePublishTemplate,
    handleRefreshGroupResponses,
    handleRefreshTemplateResponses,
    handleReopenGroup,
    handleReopenTemplate,
    handleSearchGroupResponses,
    handleSearchTemplateResponses,
    handleUseGroupResponsesAsSearchFill,
    handleUseTemplateResponsesAsSearchFill,
    hasActiveGroupScope,
    hasActiveTemplateScope,
    managerOpen,
    profileLimits,
    setManagerOpen,
    templateClosing,
    templateError,
    templateLoadingLink,
    templatePublishing,
    templateResponses,
    templateResponsesLoading,
  ]);

  return {
    canManageFillLink,
    handleOpenFillLinkManager,
    clearAllFillLinks,
    dialogProps,
  };
}
