import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import {
  ApiService,
  type CreditPricingConfig,
  type ProfileLimits,
  type SavedFormSummary,
  type TemplateGroupSummary,
} from '../services/api';
import type {
  BannerNotice,
  CheckboxHint,
  CheckboxRule,
  ConfirmDialogOptions,
  DataSourceKind,
  PageSize,
  PdfField,
  ProcessingMode,
  SchemaPayload,
  TextTransformRule,
} from '../types';
import { buildTemplateFields, clearFieldValues } from '../utils/fields';
import { applyRenamePayloadToFields } from '../utils/openAiFields';
import { resolveGroupTemplates, useGroupTemplateCache } from './useGroupTemplateCache';
import type { SavedFormSessionResume } from './useDetection';
import { useGroupUploadModal } from './useGroupUploadModal';

type SearchFillPresetState = {
  query: string;
  searchKey?: string;
  searchMode?: 'contains' | 'equals';
  autoRun?: boolean;
  autoFillOnSearch?: boolean;
  highlightResult?: boolean;
  token: number;
} | null;

type GroupContext = {
  id: string;
  name: string;
  templateIds: string[];
};

type PdfStateBridge = {
  setPdfDoc: Dispatch<SetStateAction<PDFDocumentProxy | null>>;
  setPageSizes: Dispatch<SetStateAction<Record<number, PageSize>>>;
  setPageCount: Dispatch<SetStateAction<number>>;
  setCurrentPage: Dispatch<SetStateAction<number>>;
  setScale: Dispatch<SetStateAction<number>>;
  setPendingPageJump: Dispatch<SetStateAction<number | null>>;
};

type DialogController = {
  setBannerNotice: (notice: BannerNotice | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean>;
};

type GroupsController = {
  groups: TemplateGroupSummary[];
  groupsLoading: boolean;
  groupsCreating: boolean;
  updatingGroupId: string | null;
  deletingGroupId: string | null;
  selectedGroupFilterId: string;
  setSelectedGroupFilterId: Dispatch<SetStateAction<string>>;
  refreshGroups: (options?: { throwOnError?: boolean }) => Promise<TemplateGroupSummary[]>;
  createGroup: (
    payload: { name: string; templateIds: string[] },
    options?: { signal?: AbortSignal },
  ) => Promise<TemplateGroupSummary>;
  updateExistingGroup: (
    groupId: string,
    payload: { name: string; templateIds: string[] },
  ) => Promise<TemplateGroupSummary>;
  deleteGroup: (groupId: string) => Promise<void>;
};

type SavedFormsController = {
  savedForms: SavedFormSummary[];
  activeSavedFormId: string | null;
  activeSavedFormName: string | null;
  setActiveSavedFormId: Dispatch<SetStateAction<string | null>>;
  setActiveSavedFormName: Dispatch<SetStateAction<string | null>>;
  deleteSavedFormById: (
    formId: string,
    options?: {
      preserveActiveSelection?: boolean;
      afterDelete?: () => void;
    },
  ) => Promise<boolean>;
  handleSavedFormsLimitDelete: (
    formId: string,
    options?: {
      preserveActiveSelection?: boolean;
      afterDelete?: () => void;
    },
  ) => Promise<boolean>;
  refreshSavedForms: (opts?: { allowRetry?: boolean; throwOnError?: boolean }) => Promise<SavedFormSummary[]>;
};

type DetectionController = {
  handleSelectSavedForm: (
    formId: string,
    pdfState: PdfStateBridge,
    options?: {
      source?: 'saved-form' | 'saved-group';
      preferredSession?: SavedFormSessionResume | null;
    },
  ) => Promise<boolean>;
  handleFillableUpload: (
    file: File,
    options: { isDemo?: boolean; skipExistingFields?: boolean },
    pdfState: PdfStateBridge,
  ) => Promise<void>;
  runDetectUpload: (
    file: File,
    options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null },
    pdfState: PdfStateBridge,
  ) => Promise<void>;
  isProcessing: boolean;
  detectSessionId: string | null;
  mappingSessionId: string | null;
  setDetectSessionId: Dispatch<SetStateAction<string | null>>;
  setMappingSessionId: Dispatch<SetStateAction<string | null>>;
  setIsProcessing: Dispatch<SetStateAction<boolean>>;
  setProcessingMode: Dispatch<SetStateAction<ProcessingMode>>;
};

type OpenAiController = {
  renameInProgress: boolean;
  mappingInProgress: boolean;
  mapSchemaInProgress: boolean;
  hasRenamedFields: boolean;
  hasMappedSchema: boolean;
  checkboxRules: CheckboxRule[];
  checkboxHints: CheckboxHint[];
  textTransformRules: TextTransformRule[];
  setRenameInProgress: Dispatch<SetStateAction<boolean>>;
  setMappingInProgress: Dispatch<SetStateAction<boolean>>;
  setHasRenamedFields: Dispatch<SetStateAction<boolean>>;
  setHasMappedSchema: Dispatch<SetStateAction<boolean>>;
  setCheckboxRules: Dispatch<SetStateAction<CheckboxRule[]>>;
  setCheckboxHints: Dispatch<SetStateAction<CheckboxHint[]>>;
  setTextTransformRules: Dispatch<SetStateAction<TextTransformRule[]>>;
  setOpenAiError: Dispatch<SetStateAction<string | null>>;
};

type DocumentController = {
  pdfDoc: PDFDocumentProxy | null;
  sourceFile: File | null;
  sourceFileName: string | null;
  pageSizes: Record<number, PageSize>;
  pageCount: number;
  currentPage: number;
  scale: number;
  setLoadError: Dispatch<SetStateAction<string | null>>;
  setShowHomepage: Dispatch<SetStateAction<boolean>>;
  setShowSearchFill: Dispatch<SetStateAction<boolean>>;
  bumpSearchFillSession: () => void;
  setSearchFillPreset: Dispatch<SetStateAction<SearchFillPresetState>>;
  setShowFillLinkManager: Dispatch<SetStateAction<boolean>>;
  setSourceFile: Dispatch<SetStateAction<File | null>>;
  setSourceFileName: Dispatch<SetStateAction<string | null>>;
  setSourceFileIsDemo: Dispatch<SetStateAction<boolean>>;
  setPdfDoc: Dispatch<SetStateAction<PDFDocumentProxy | null>>;
  setPageSizes: Dispatch<SetStateAction<Record<number, PageSize>>>;
  setPageCount: Dispatch<SetStateAction<number>>;
  setCurrentPage: Dispatch<SetStateAction<number>>;
  setScale: Dispatch<SetStateAction<number>>;
  setPendingPageJump: Dispatch<SetStateAction<number | null>>;
};

type FieldHistoryController = {
  fields: PdfField[];
  fieldsRef: React.MutableRefObject<PdfField[]>;
  historyRef: React.MutableRefObject<{ undo: PdfField[][]; redo: PdfField[][] }>;
  historyTick: number;
  restoreState: (
    nextFields: PdfField[],
    history?: {
      undo?: PdfField[][];
      redo?: PdfField[][];
    } | null,
  ) => void;
};

type FieldSelectionController = {
  selectedFieldId: string | null;
  setSelectedFieldId: Dispatch<SetStateAction<string | null>>;
  handleFieldsChange: (nextFields: PdfField[]) => void;
};

type DisplayController = {
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  transformMode: boolean;
  setShowFields: Dispatch<SetStateAction<boolean>>;
  setShowFieldNames: Dispatch<SetStateAction<boolean>>;
  setShowFieldInfo: Dispatch<SetStateAction<boolean>>;
  setTransformMode: Dispatch<SetStateAction<boolean>>;
};

type DataSourceController = {
  schemaId: string | null;
  schemaUploadInProgress: boolean;
  pendingSchemaPayload: unknown;
  persistSchemaPayload: (payload: SchemaPayload) => Promise<string | null>;
  setSchemaUploadInProgress: (value: boolean) => void;
  dataColumns: string[];
  dataSourceKind: DataSourceKind;
  resolveSchemaForMapping: (mode: 'map' | 'renameAndMap') => Promise<string | null>;
};

type UseWorkspaceGroupCoordinatorDeps = {
  verifiedUser: User | null;
  userProfile: {
    role?: string | null;
    availableCredits?: number | null;
    creditsRemaining?: number | null;
    creditPricing?: CreditPricingConfig | null;
  } | null;
  loadUserProfile: () => Promise<unknown>;
  profileLimits: ProfileLimits;
  dialog: DialogController;
  groups: GroupsController;
  savedForms: SavedFormsController;
  detection: DetectionController;
  openAi: OpenAiController;
  document: DocumentController;
  pdfState: PdfStateBridge;
  fieldHistory: FieldHistoryController;
  fieldSelection: FieldSelectionController;
  display: DisplayController;
  dataSource: DataSourceController;
  markSavedFillLinkSnapshot: (fields: PdfField[], checkboxRules: CheckboxRule[]) => void;
};

function buildFallbackActiveGroup(
  activeGroupId: string | null,
  activeGroupName: string | null,
  activeGroupTemplateIds: string[],
): TemplateGroupSummary | null {
  if (!activeGroupId || !activeGroupName) {
    return null;
  }
  return {
    id: activeGroupId,
    name: activeGroupName,
    templateIds: activeGroupTemplateIds,
    templateCount: activeGroupTemplateIds.length,
    templates: [],
  };
}

export function useWorkspaceGroupCoordinator(deps: UseWorkspaceGroupCoordinatorDeps) {
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [activeGroupName, setActiveGroupName] = useState<string | null>(null);
  const [activeGroupTemplateIds, setActiveGroupTemplateIds] = useState<string[]>([]);
  const [pendingGroupTemplateId, setPendingGroupTemplateId] = useState<string | null>(null);
  const [groupRenameMapInProgress, setGroupRenameMapInProgress] = useState(false);
  const [groupRenameMapLabel, setGroupRenameMapLabel] = useState<string>('Rename + Map Group');

  const clearActiveGroupSelection = useCallback(() => {
    setActiveGroupId(null);
    setActiveGroupName(null);
    setActiveGroupTemplateIds([]);
    setPendingGroupTemplateId(null);
  }, []);

  const handleSelectSavedFormWithinGroup = useCallback(
    async (
      formId: string,
      groupContext?: GroupContext | null,
      options?: { preferredSession?: SavedFormSessionResume | null },
    ) => {
      if (groupContext) {
        setActiveGroupId(groupContext.id);
        setActiveGroupName(groupContext.name);
        setActiveGroupTemplateIds(groupContext.templateIds);
        setPendingGroupTemplateId(formId);
      } else {
        clearActiveGroupSelection();
      }
      try {
        return await deps.detection.handleSelectSavedForm(formId, deps.pdfState, {
          source: groupContext ? 'saved-group' : 'saved-form',
          preferredSession: options?.preferredSession ?? null,
        });
      } finally {
        if (groupContext) {
          setPendingGroupTemplateId((current) => (current === formId ? null : current));
        }
      }
    },
    [clearActiveGroupSelection, deps.detection, deps.pdfState],
  );

  const {
    activeGroupTemplates,
    groupTemplateStatusById,
    groupSwitchingTemplateId,
    clearGroupTemplateCache,
    captureActiveGroupTemplateSnapshot,
    ensureGroupTemplateSnapshot,
    resolveDirtyGroupTemplateRecords,
    resolveGroupTemplateDirtyNames,
    isActiveGroupTemplateDirty,
    markGroupTemplatesPersisted,
    handleSelectActiveGroupTemplate,
    handleFillSearchTargets,
  } = useGroupTemplateCache({
    verifiedUser: deps.verifiedUser,
    group: {
      groups: deps.groups.groups,
      groupsLoading: deps.groups.groupsLoading,
      activeGroupId,
      activeGroupName,
      activeGroupTemplateIds,
      setActiveGroupId,
      setActiveGroupName,
      setActiveGroupTemplateIds,
      groupRenameMapInProgress,
    },
    savedForms: {
      savedForms: deps.savedForms.savedForms,
      activeSavedFormId: deps.savedForms.activeSavedFormId,
      activeSavedFormName: deps.savedForms.activeSavedFormName,
      setActiveSavedFormId: deps.savedForms.setActiveSavedFormId,
      setActiveSavedFormName: deps.savedForms.setActiveSavedFormName,
      openSavedFormWithinGroup: handleSelectSavedFormWithinGroup,
    },
    document: deps.document,
    fieldHistory: deps.fieldHistory,
    fieldSelection: deps.fieldSelection,
    detection: {
      detectSessionId: deps.detection.detectSessionId,
      mappingSessionId: deps.detection.mappingSessionId,
      resetProcessing: () => {
        deps.detection.setIsProcessing(false);
        deps.detection.setProcessingMode(null);
      },
      setDetectSessionId: deps.detection.setDetectSessionId,
      setMappingSessionId: deps.detection.setMappingSessionId,
    },
    openAi: deps.openAi,
    searchFill: {
      dataSourceKind: deps.dataSource.dataSourceKind,
    },
    setBannerNotice: deps.dialog.setBannerNotice,
    markSavedFillLinkSnapshot: deps.markSavedFillLinkSnapshot,
  });

  const formatDirtyTemplateSummary = useCallback((dirtyTemplateNames: string[]) => {
    const listedNames = dirtyTemplateNames.slice(0, 3).map((name) => `"${name}"`).join(', ');
    const remainingCount = dirtyTemplateNames.length - Math.min(dirtyTemplateNames.length, 3);
    return remainingCount > 0
      ? `${listedNames}, and ${remainingCount} other template${remainingCount === 1 ? '' : 's'}`
      : listedNames;
  }, []);

  const confirmDiscardDirtyGroupChanges = useCallback(async (targetLabel: string) => {
    if (!activeGroupId) {
      return true;
    }
    const dirtyTemplateNames = resolveGroupTemplateDirtyNames();
    if (dirtyTemplateNames.length === 0) {
      return true;
    }
    return deps.dialog.requestConfirm({
      title: 'Discard unsaved group changes?',
      message: `You have unsaved changes in ${formatDirtyTemplateSummary(dirtyTemplateNames)}. Leave "${activeGroupName || 'this group'}" before ${targetLabel} and discard them?`,
      confirmLabel: 'Discard changes',
      cancelLabel: 'Stay',
      tone: 'danger',
    });
  }, [
    activeGroupId,
    activeGroupName,
    deps.dialog,
    formatDirtyTemplateSummary,
    resolveGroupTemplateDirtyNames,
  ]);

  const handleFillableUpload = useCallback(
    async (file: File, options: { isDemo?: boolean; skipExistingFields?: boolean } = {}) => {
      const confirmed = await confirmDiscardDirtyGroupChanges('loading another PDF');
      if (!confirmed) return;
      clearGroupTemplateCache();
      clearActiveGroupSelection();
      await deps.detection.handleFillableUpload(file, options, deps.pdfState);
    },
    [
      clearActiveGroupSelection,
      clearGroupTemplateCache,
      confirmDiscardDirtyGroupChanges,
      deps.detection,
      deps.pdfState,
    ],
  );

  const handleSelectSavedForm = useCallback(
    async (
      formId: string,
      options?: { preferredSession?: SavedFormSessionResume | null },
    ) => {
      const confirmed = await confirmDiscardDirtyGroupChanges('opening another saved form');
      if (!confirmed) return false;
      clearGroupTemplateCache();
      return handleSelectSavedFormWithinGroup(formId, null, {
        preferredSession: options?.preferredSession ?? null,
      });
    },
    [
      clearGroupTemplateCache,
      confirmDiscardDirtyGroupChanges,
      handleSelectSavedFormWithinGroup,
    ],
  );

  const handleCreateGroup = useCallback(
    async (
      payload: { name: string; templateIds: string[] },
      options?: { signal?: AbortSignal },
    ) => {
      try {
        const nextGroup = await deps.groups.createGroup(payload, options);
        deps.dialog.setBannerNotice({
          tone: 'success',
          message: `Created group "${payload.name}".`,
          autoDismissMs: 5000,
        });
        return nextGroup;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to create group.';
        deps.dialog.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
        throw error;
      }
    },
    [deps.dialog, deps.groups],
  );

  const handleUpdateGroup = useCallback(
    async (groupId: string, payload: { name: string; templateIds: string[] }) => {
      if (activeGroupId === groupId) {
        const removedTemplateIds = activeGroupTemplateIds.filter(
          (templateId) => !payload.templateIds.includes(templateId),
        );
        const dirtyRemovedTemplates = resolveDirtyGroupTemplateRecords(removedTemplateIds);
        if (dirtyRemovedTemplates.length > 0) {
          const confirmed = await deps.dialog.requestConfirm({
            title: 'Discard removed template changes?',
            message: `This update removes ${formatDirtyTemplateSummary(dirtyRemovedTemplates.map((entry) => entry.templateName))} from "${activeGroupName || 'this group'}". Their unsaved cached edits will be discarded. Continue?`,
            confirmLabel: 'Update group',
            cancelLabel: 'Cancel',
            tone: 'danger',
          });
          if (!confirmed) return;
        }
      }
      try {
        const previousGroup = deps.groups.groups.find((entry) => entry.id === groupId) ?? null;
        const updatedGroup = await deps.groups.updateExistingGroup(groupId, payload);
        if (activeGroupId === groupId) {
          const nextTemplates = resolveGroupTemplates(updatedGroup, deps.savedForms.savedForms);
          setActiveGroupName(updatedGroup.name);
          setActiveGroupTemplateIds(nextTemplates.map((entry) => entry.id));
        }
        deps.dialog.setBannerNotice({
          tone: 'success',
          message: previousGroup && previousGroup.name !== updatedGroup.name
            ? `Updated group "${previousGroup.name}" to "${updatedGroup.name}".`
            : `Updated group "${updatedGroup.name}".`,
          autoDismissMs: 5000,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to update group.';
        deps.dialog.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
        throw error;
      }
    },
    [
      activeGroupId,
      activeGroupName,
      activeGroupTemplateIds,
      deps.dialog,
      deps.groups,
      deps.savedForms.savedForms,
      formatDirtyTemplateSummary,
      resolveDirtyGroupTemplateRecords,
    ],
  );

  const confirmAndDeleteSavedForm = useCallback(
    async (
      formId: string,
      deleteAction: (
        targetFormId: string,
        options?: {
          preserveActiveSelection?: boolean;
          afterDelete?: () => void;
        },
      ) => Promise<boolean>,
    ) => {
      const target = deps.savedForms.savedForms.find((form) => form.id === formId) ?? null;
      const targetName = target?.name || deps.savedForms.activeSavedFormName || 'this saved form';
      const deletedDirtyTemplates = activeGroupId ? resolveDirtyGroupTemplateRecords([formId]) : [];
      const deletingActiveGroupTemplate = Boolean(
        activeGroupId && formId === deps.savedForms.activeSavedFormId,
      );
      const deletingDirtyActiveGroupTemplate = deletingActiveGroupTemplate && deletedDirtyTemplates.length > 0;
      const otherDirtyTemplates = deletingDirtyActiveGroupTemplate
        ? resolveDirtyGroupTemplateRecords().filter((entry) => entry.formId !== formId)
        : [];

      let message = `Delete "${targetName}"? This removes it from your saved forms.`;
      if (deletingDirtyActiveGroupTemplate) {
        const preservedMessage = `Delete "${targetName}"? This removes it from your saved forms. The open template will stay in the editor as an unsaved copy and "${activeGroupName || 'this group'}" will close so your current edits are preserved.`;
        message = otherDirtyTemplates.length > 0
          ? `${preservedMessage} Unsaved cached changes in ${formatDirtyTemplateSummary(otherDirtyTemplates.map((entry) => entry.templateName))} will be discarded.`
          : preservedMessage;
      } else if (deletedDirtyTemplates.length > 0) {
        message = `Delete "${targetName}"? This removes it from your saved forms and discards unsaved cached changes in ${formatDirtyTemplateSummary(deletedDirtyTemplates.map((entry) => entry.templateName))}.`;
      }

      const confirmDelete = await deps.dialog.requestConfirm({
        title: 'Delete saved form?',
        message,
        confirmLabel: 'Delete',
        cancelLabel: 'Cancel',
        tone: 'danger',
      });
      if (!confirmDelete) return;

      const removed = await deleteAction(
        formId,
        deletingDirtyActiveGroupTemplate
          ? {
              preserveActiveSelection: true,
              afterDelete: () => {
                clearGroupTemplateCache();
                clearActiveGroupSelection();
                deps.savedForms.setActiveSavedFormId(null);
                deps.savedForms.setActiveSavedFormName(targetName);
              },
            }
          : undefined,
      );
      if (!removed) return;

      if (deletingDirtyActiveGroupTemplate) {
        deps.dialog.setBannerNotice({
          tone: 'warning',
          message: `Deleted "${targetName}". The edited template remains open as an unsaved copy outside the group.`,
          autoDismissMs: 8000,
        });
      }
    },
    [
      activeGroupId,
      activeGroupName,
      clearActiveGroupSelection,
      clearGroupTemplateCache,
      deps.dialog,
      deps.savedForms,
      formatDirtyTemplateSummary,
      resolveDirtyGroupTemplateRecords,
    ],
  );

  const handleDeleteSavedForm = useCallback(
    async (formId: string) => {
      await confirmAndDeleteSavedForm(formId, deps.savedForms.deleteSavedFormById);
    },
    [confirmAndDeleteSavedForm, deps.savedForms.deleteSavedFormById],
  );

  const handleSavedFormsLimitDelete = useCallback(
    async (formId: string) => {
      await confirmAndDeleteSavedForm(formId, deps.savedForms.handleSavedFormsLimitDelete);
    },
    [confirmAndDeleteSavedForm, deps.savedForms.handleSavedFormsLimitDelete],
  );

  const handleDeleteGroup = useCallback(
    async (groupId: string) => {
      const targetGroup = deps.groups.groups.find((entry) => entry.id === groupId) ?? null;
      if (!targetGroup) {
        deps.dialog.setBannerNotice({
          tone: 'error',
          message: 'Group not found.',
          autoDismissMs: 7000,
        });
        return;
      }
      const confirmed = await deps.dialog.requestConfirm({
        title: 'Delete group?',
        message: `Delete "${targetGroup.name}"? Saved templates will remain in your account.`,
        confirmLabel: 'Delete group',
        cancelLabel: 'Cancel',
        tone: 'danger',
      });
      if (!confirmed) return;
      if (activeGroupId === groupId) {
        const discardConfirmed = await confirmDiscardDirtyGroupChanges('deleting this group');
        if (!discardConfirmed) return;
      }
      try {
        await deps.groups.deleteGroup(groupId);
        if (activeGroupId === groupId) {
          clearGroupTemplateCache();
          clearActiveGroupSelection();
        }
        deps.dialog.setBannerNotice({
          tone: 'success',
          message: `Deleted group "${targetGroup.name}".`,
          autoDismissMs: 5000,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to delete group.';
        deps.dialog.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
      }
    },
    [
      activeGroupId,
      clearActiveGroupSelection,
      clearGroupTemplateCache,
      confirmDiscardDirtyGroupChanges,
      deps.dialog,
      deps.groups,
    ],
  );

  const handleOpenGroup = useCallback(
    async (
      groupId: string,
      options?: {
        preferredTemplateId?: string | null;
        preferredSession?: SavedFormSessionResume | null;
      },
    ) => {
      try {
        const fallbackGroup = deps.groups.groups.find((entry) => entry.id === groupId) ?? null;
        let savedFormsList = deps.savedForms.savedForms;
        let group = fallbackGroup;
        let templates = resolveGroupTemplates(group, savedFormsList);

        if (!group || !templates.length) {
          const [refreshedGroups, refreshedSavedForms] = await Promise.all([
            deps.groups.refreshGroups({ throwOnError: true }),
            deps.savedForms.refreshSavedForms({ allowRetry: true, throwOnError: true }),
          ]);
          savedFormsList = refreshedSavedForms;
          group = refreshedGroups.find((entry) => entry.id === groupId) ?? group;
          templates = resolveGroupTemplates(group, savedFormsList);
        }

        if (!group) {
          group = await ApiService.getGroup(groupId);
          templates = resolveGroupTemplates(group, savedFormsList);
        }
        if (!templates.length) {
          deps.dialog.setBannerNotice({
            tone: 'error',
            message: 'This group has no available saved forms to open.',
            autoDismissMs: 7000,
          });
          return false;
        }
        if (
          activeGroupId === group.id &&
          deps.savedForms.activeSavedFormId &&
          templates.some((entry) => entry.id === deps.savedForms.activeSavedFormId)
        ) {
          return true;
        }
        const confirmed = await confirmDiscardDirtyGroupChanges(`opening "${group.name}"`);
        if (!confirmed) return false;
        const firstTemplate = options?.preferredTemplateId
          ? (templates.find((entry) => entry.id === options.preferredTemplateId) ?? templates[0])
          : templates[0];
        clearGroupTemplateCache();
        return handleSelectSavedFormWithinGroup(firstTemplate.id, {
          id: group.id,
          name: group.name,
          templateIds: templates.map((entry) => entry.id),
        }, {
          preferredSession: options?.preferredSession ?? null,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to open group.';
        deps.dialog.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
        return false;
      }
    },
    [
      activeGroupId,
      clearGroupTemplateCache,
      confirmDiscardDirtyGroupChanges,
      deps.dialog,
      deps.groups.groups,
      deps.savedForms.activeSavedFormId,
      deps.savedForms.savedForms,
      handleSelectSavedFormWithinGroup,
    ],
  );

  useEffect(() => {
    if (!activeGroupId || deps.detection.isProcessing) return;
    if (activeGroupTemplateIds.length === 0) return;
    if (
      deps.savedForms.activeSavedFormId &&
      activeGroupTemplateIds.includes(deps.savedForms.activeSavedFormId)
    ) {
      return;
    }
    if (deps.savedForms.activeSavedFormId && isActiveGroupTemplateDirty()) {
      clearActiveGroupSelection();
      deps.dialog.setBannerNotice({
        tone: 'warning',
        message: `"${deps.savedForms.activeSavedFormName || 'Current template'}" is no longer in "${activeGroupName || 'this group'}". The group was closed so your unsaved changes stay on the open template.`,
        autoDismissMs: 9000,
      });
      return;
    }
    const nextTemplate = activeGroupTemplates[0];
    if (!nextTemplate || !activeGroupName) {
      clearActiveGroupSelection();
      return;
    }
    deps.dialog.setBannerNotice({
      tone: 'info',
      message: deps.savedForms.activeSavedFormName
        ? `"${deps.savedForms.activeSavedFormName}" is no longer in "${activeGroupName}". Opening "${nextTemplate.name}" instead.`
        : `Opening "${nextTemplate.name}" in "${activeGroupName}".`,
      autoDismissMs: 7000,
    });
    void handleSelectSavedFormWithinGroup(nextTemplate.id, {
      id: activeGroupId,
      name: activeGroupName,
      templateIds: activeGroupTemplateIds,
    });
  }, [
    activeGroupId,
    activeGroupName,
    activeGroupTemplateIds,
    activeGroupTemplates,
    clearActiveGroupSelection,
    deps.detection.isProcessing,
    deps.dialog.setBannerNotice,
    deps.savedForms.activeSavedFormId,
    deps.savedForms.activeSavedFormName,
    handleSelectSavedFormWithinGroup,
    isActiveGroupTemplateDirty,
  ]);

  const runDetectUpload = useCallback(
    async (file: File, options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null } = {}) => {
      const confirmed = await confirmDiscardDirtyGroupChanges('running detection on another PDF');
      if (!confirmed) return;
      clearGroupTemplateCache();
      clearActiveGroupSelection();
      await deps.detection.runDetectUpload(file, options, deps.pdfState);
    },
    [
      clearActiveGroupSelection,
      clearGroupTemplateCache,
      confirmDiscardDirtyGroupChanges,
      deps.detection,
      deps.pdfState,
    ],
  );

  const groupUpload = useGroupUploadModal({
    verifiedUser: deps.verifiedUser,
    userProfile: deps.userProfile,
    loadUserProfile: deps.loadUserProfile,
    profileLimits: deps.profileLimits,
    savedFormsCount: deps.savedForms.savedForms.length,
    dataColumns: deps.dataSource.dataColumns,
    schemaId: deps.dataSource.schemaId,
    schemaUploadInProgress: deps.dataSource.schemaUploadInProgress,
    pendingSchemaPayload: deps.dataSource.pendingSchemaPayload,
    persistSchemaPayload: deps.dataSource.persistSchemaPayload,
    setSchemaUploadInProgress: deps.dataSource.setSchemaUploadInProgress,
    createGroup: deps.groups.createGroup,
    openGroup: handleOpenGroup,
    refreshSavedForms: deps.savedForms.refreshSavedForms,
    refreshProfile: deps.loadUserProfile,
    setBannerNotice: deps.dialog.setBannerNotice,
  });

  const resetGroupRuntime = useCallback(() => {
    clearGroupTemplateCache();
    clearActiveGroupSelection();
    groupUpload.reset();
    setGroupRenameMapInProgress(false);
    setGroupRenameMapLabel('Rename + Map Group');
  }, [clearActiveGroupSelection, clearGroupTemplateCache, groupUpload.reset]);

  const handleRenameAndMapGroup = useCallback(async () => {
    const resolvedGroup =
      deps.groups.groups.find((group) => group.id === activeGroupId) ??
      buildFallbackActiveGroup(activeGroupId, activeGroupName, activeGroupTemplateIds);
    const groupTemplatesForRun = resolveGroupTemplates(resolvedGroup, deps.savedForms.savedForms);

    if (!activeGroupId || !activeGroupName || groupTemplatesForRun.length === 0) {
      deps.dialog.setBannerNotice({
        tone: 'error',
        message: 'Open a group before running batch rename + map.',
      });
      return;
    }
    const resolvedSchemaId = await deps.dataSource.resolveSchemaForMapping('renameAndMap');
    if (!resolvedSchemaId) return;
    const confirmed = await deps.dialog.requestConfirm({
      title: 'Rename + Map entire group?',
      message: `DullyPDF will run Rename + Map on ${groupTemplatesForRun.length} saved template${groupTemplatesForRun.length === 1 ? '' : 's'} in "${activeGroupName}" and overwrite each saved form on success.`,
      confirmLabel: 'Run group action',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    setGroupRenameMapInProgress(true);
    deps.openAi.setOpenAiError(null);
    const successIds: string[] = [];
    const failedTemplates: Array<{ name: string; message: string }> = [];
    try {
      for (let index = 0; index < groupTemplatesForRun.length; index += 1) {
        const template = groupTemplatesForRun[index];
        setGroupRenameMapLabel(`Rename + Map ${index + 1}/${groupTemplatesForRun.length}`);
        try {
          const activeSnapshot = template.id === deps.savedForms.activeSavedFormId
            ? captureActiveGroupTemplateSnapshot()
            : null;
          const snapshot = activeSnapshot ?? await ensureGroupTemplateSnapshot(template.id, template.name);
          const blob = snapshot.sourceFile;
          const fields = snapshot.fields.map((field) => ({
            ...field,
            rect: { ...field.rect },
          }));
          if (!fields.length) {
            throw new Error('No embedded fields were found in this saved form.');
          }
          const templateFields = buildTemplateFields(fields);
          const sessionPayload = await ApiService.createSavedFormSession(template.id, {
            fields: templateFields,
            pageCount: snapshot.pageCount,
          });
          const renameResult = await ApiService.renameFields({
            sessionId: sessionPayload.sessionId,
            schemaId: resolvedSchemaId,
            templateFields,
          });
          const renamedFields = applyRenamePayloadToFields(
            fields,
            Array.isArray(renameResult?.fields) ? renameResult.fields : undefined,
          );
          if (!renameResult?.success || !renamedFields || renamedFields.length === 0) {
            throw new Error(renameResult?.error || 'Rename + Map did not return updated fields.');
          }
          const checkboxRules = Array.isArray(renameResult?.checkboxRules) ? renameResult.checkboxRules : [];
          const checkboxHints = Array.isArray(
            (renameResult as { checkboxHints?: CheckboxHint[] } | null)?.checkboxHints,
          )
            ? ((renameResult as { checkboxHints?: CheckboxHint[] }).checkboxHints ?? [])
            : [];
          const textTransformRules = Array.isArray(
            (renameResult as { textTransformRules?: TextTransformRule[] } | null)?.textTransformRules,
          )
            ? ((renameResult as { textTransformRules?: TextTransformRule[] }).textTransformRules ?? [])
            : [];
          const materializedBlob = await ApiService.materializeFormPdf(
            blob,
            clearFieldValues(renamedFields),
          );
          await ApiService.saveFormToProfile(
            materializedBlob,
            template.name,
            sessionPayload.sessionId,
            template.id,
            checkboxRules,
            checkboxHints,
            textTransformRules,
          );
          successIds.push(template.id);
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Group Rename + Map failed.';
          failedTemplates.push({ name: template.name, message });
        }
      }

      await Promise.allSettled([
        deps.savedForms.refreshSavedForms(),
        deps.groups.refreshGroups(),
        deps.loadUserProfile(),
      ]);
      clearGroupTemplateCache();

      if (deps.savedForms.activeSavedFormId && successIds.includes(deps.savedForms.activeSavedFormId)) {
        await handleSelectSavedFormWithinGroup(deps.savedForms.activeSavedFormId, {
          id: activeGroupId,
          name: activeGroupName,
          templateIds: activeGroupTemplateIds,
        });
      }

      if (failedTemplates.length === 0) {
        deps.dialog.setBannerNotice({
          tone: 'success',
          message: `Rename + Map completed for ${successIds.length} template${successIds.length === 1 ? '' : 's'} in "${activeGroupName}".`,
          autoDismissMs: 7000,
        });
        return;
      }

      const failureSummary = failedTemplates
        .slice(0, 2)
        .map((entry) => `${entry.name}: ${entry.message}`)
        .join(' | ');
      deps.dialog.setBannerNotice({
        tone: 'warning',
        message: `Group Rename + Map finished with ${successIds.length} success${successIds.length === 1 ? '' : 'es'} and ${failedTemplates.length} failure${failedTemplates.length === 1 ? '' : 's'}. ${failureSummary}`,
        autoDismissMs: 10000,
      });
    } finally {
      setGroupRenameMapLabel('Rename + Map Group');
      setGroupRenameMapInProgress(false);
    }
  }, [
    activeGroupId,
    activeGroupName,
    activeGroupTemplateIds,
    captureActiveGroupTemplateSnapshot,
    clearGroupTemplateCache,
    deps.dataSource,
    deps.dialog,
    deps.groups,
    deps.loadUserProfile,
    deps.openAi,
    deps.savedForms,
    ensureGroupTemplateSnapshot,
    handleSelectSavedFormWithinGroup,
  ]);

  const groupRenameMapDisabledReason = useMemo(() => {
    if (groupRenameMapInProgress) return 'Rename + Map Group is already running.';
    if (!deps.verifiedUser) return 'Sign in to run Rename + Map Group.';
    if (!activeGroupId || activeGroupTemplates.length === 0) return 'Open a group first.';
    if (
      deps.dataSource.dataSourceKind !== 'csv' &&
      deps.dataSource.dataSourceKind !== 'excel' &&
      deps.dataSource.dataSourceKind !== 'json' &&
      deps.dataSource.dataSourceKind !== 'txt'
    ) {
      return 'Connect a CSV, Excel, JSON, or TXT schema source first.';
    }
    if (
      (deps.dataSource.dataSourceKind === 'csv' ||
        deps.dataSource.dataSourceKind === 'excel' ||
        deps.dataSource.dataSourceKind === 'json' ||
        deps.dataSource.dataSourceKind === 'txt') &&
      deps.dataSource.dataColumns.length === 0
    ) {
      return 'Upload schema headers before mapping.';
    }
    return null;
  }, [
    activeGroupId,
    activeGroupTemplates.length,
    deps.dataSource.dataColumns.length,
    deps.dataSource.dataSourceKind,
    deps.verifiedUser,
    groupRenameMapInProgress,
  ]);

  return {
    groups: deps.groups,
    groupUpload,
    activeGroupId,
    activeGroupName,
    activeGroupTemplateIds,
    pendingGroupTemplateId,
    activeGroupTemplates,
    groupTemplateStatusById,
    groupSwitchingTemplateId,
    groupRenameMapInProgress,
    groupRenameMapLabel,
    groupRenameMapDisabledReason,
    clearGroupTemplateCache,
    captureActiveGroupTemplateSnapshot,
    ensureGroupTemplateSnapshot,
    resolveGroupTemplateDirtyNames,
    markGroupTemplatesPersisted,
    confirmDiscardDirtyGroupChanges,
    handleSelectSavedForm,
    handleCreateGroup,
    handleUpdateGroup,
    handleDeleteSavedForm,
    handleSavedFormsLimitDelete,
    handleDeleteGroup,
    handleOpenGroup,
    handleFillableUpload,
    runDetectUpload,
    handleRenameAndMapGroup,
    handleSelectActiveGroupTemplate,
    handleFillSearchTargets,
    resetGroupRuntime,
  };
}
