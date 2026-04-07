/**
 * Workspace runtime shell that orchestrates detection, mapping, and editor state.
 */
/* eslint-disable react-hooks/refs */
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import './App.css';
import type {
  BannerNotice,
  CheckboxRule,
  CreateTool,
  DataSourceKind,
  FieldType,
  PageSize,
  PdfField,
  RadioGroup,
  RadioGroupSuggestion,
  RadioToolDraft,
  TextTransformRule,
} from './types';
import { HeaderBar } from './components/layout/HeaderBar';
import LegacyHeader from './components/layout/LegacyHeader';
import { FieldInspectorPanel } from './components/panels/FieldInspectorPanel';
import { FieldListPanel, type FieldListDisplayPreset } from './components/panels/FieldListPanel';
import { PdfViewer } from './components/viewer/PdfViewer';
import { Alert } from './components/ui/Alert';
import { ConfirmDialog, PromptDialog, SavedFormsLimitDialog } from './components/ui/Dialog';
import {
  DEMO_ASSETS,
  DEMO_DISABLED_MESSAGE,
  DEMO_STEPS,
  PROCESSING_AD_POSTER_URL,
  PROCESSING_AD_VIDEO_URL,
} from './config/appConstants';

const DEMO_ASSET_NAME_SET = new Set(Object.values(DEMO_ASSETS));
import { useFieldHistory } from './hooks/useFieldHistory';
import { useFieldState } from './hooks/useFieldState';
import { useDialog } from './hooks/useDialog';
import { useAuth } from './hooks/useAuth';
import { useSavedForms } from './hooks/useSavedForms';
import { useGroups } from './hooks/useGroups';
import { useWorkspaceGroupCoordinator } from './hooks/useWorkspaceGroupCoordinator';
import { useWorkspaceFillLinks } from './hooks/useWorkspaceFillLinks';
import { useWorkspaceTemplateApi } from './hooks/useWorkspaceTemplateApi';
import { useDataSource } from './hooks/useDataSource';
import { useOpenAiPipeline } from './hooks/useOpenAiPipeline';
import { useDetection, type SavedFormSessionResume } from './hooks/useDetection';
import { useImageFill } from './hooks/useImageFill';
import { usePipelineModal } from './hooks/usePipelineModal';
import { useGroupDownload } from './hooks/useGroupDownload';
import { useDowngradeRetentionRuntime } from './hooks/useDowngradeRetentionRuntime';
import { useSaveDownload } from './hooks/useSaveDownload';
import { useDemo } from './hooks/useDemo';
import { useUploadBrowserViewModel } from './hooks/useUploadBrowserViewModel';
import { useWorkspaceSigning } from './hooks/useWorkspaceSigning';
import { useWorkspaceSessionDiagnostic } from './hooks/useWorkspaceSessionDiagnostic';
import { ApiService } from './services/api';
import { fetchDetectionStatus } from './services/detectionApi';
import { debugLog } from './utils/debug';
import { returnWorkspaceToHomepage } from './utils/returnWorkspaceToHomepage';
import { applyRouteSeo } from './utils/seo';
import {
  LazyDemoTour,
  LazyDowngradeRetentionDialog,
  LazyFillLinkManagerDialog,
  LazyApiFillManagerDialog,
  LazyGroupUploadDialog,
  LazyHomepage,
  LazyImageFillDialog,
  LazyLoginPage,
  LazyOnboardingPage,
  LazyProcessingView,
  LazyProfilePage,
  LazySearchFillModal,
  LazySignatureRequestDialog,
  LazyUploadView,
  LazyVerifyEmailPage,
} from './workspaceLazyComponents';
import { clampRectToPage } from './utils/coords';
import {
  createFieldWithRect,
  getMinFieldSize,
  normalizeRectForFieldType,
  prepareFieldsForMaterialize,
} from './utils/fields';
import {
  advanceRadioToolDraft,
  buildNextRadioToolDraft,
  buildRadioGroups,
  convertFieldsToRadioGroup,
  convertRadioFieldToType,
  createRadioFieldFromRect,
  dissolveRadioGroup,
  moveRadioFieldToGroup,
  renameRadioGroup,
  reorderRadioField,
  setRadioGroupSelectedValue,
  updateRadioFieldOption,
} from './utils/radioGroups';
import {
  applyRadioGroupSuggestions,
  applyRadioGroupSuggestion,
  buildRadioSuggestionFieldMap,
  isRadioGroupSuggestionApplied,
  shouldAutoApplyRadioGroupSuggestion,
} from './utils/radioGroupSuggestions';
import {
  DEFAULT_ARROW_KEY_MOVE_STEP,
  getFieldNudgeCommandFromKey,
  sanitizeArrowKeyMoveStep,
} from './utils/fieldMovement';
import { mapDetectionFields } from './utils/detection';
import {
  buildFillLinkPublishFingerprint,
  FILL_LINK_LINK_ID_KEY,
  FILL_LINK_RESPONSE_ID_KEY,
  FILL_LINK_RESPONDENT_LABEL_KEY,
} from './utils/fillLinks';
import type { ReviewedFillContext } from './utils/signing';
import {
  clearWorkspaceResumeState,
  findMatchingWorkspaceResumeState,
  writeWorkspaceResumeState,
} from './utils/workspaceResumeState';
import {
  prunePendingQuickRadioSelection,
  resolvePendingQuickRadioFields,
  resolveRadioToolDraftForToolChange,
  type PendingQuickRadioSelection,
} from './utils/createToolState';
import {
  areWorkspaceBrowserRoutesEqual,
  getWorkspaceBrowserRouteKey,
  type WorkspaceBrowserRoute,
} from './utils/workspaceRoutes';
import { shouldIgnoreWorkspaceHotkeys } from './utils/workspaceShortcuts';
import { consumeOnboardingPending, clearOnboardingPending } from './utils/onboardingState';

/**
 * Launch actions that can be requested by the lightweight homepage shell.
 */
export type WorkspaceLaunchIntent = 'workflow' | 'demo' | 'signin' | 'profile' | null;

type WorkspaceRuntimeProps = {
  initialShowHomepage?: boolean;
  launchIntent?: WorkspaceLaunchIntent;
  assumeAuthReady?: boolean;
  bootstrapHasVerifiedUser?: boolean;
  bootstrapAuthUser?: User | null;
  browserRoute?: WorkspaceBrowserRoute;
  onBrowserRouteChange?: (route: WorkspaceBrowserRoute, options?: { replace?: boolean }) => void;
};

type SearchFillPresetState = {
  query: string;
  searchKey?: string;
  searchMode?: 'contains' | 'equals';
  autoRun?: boolean;
  autoFillOnSearch?: boolean;
  highlightResult?: boolean;
  token: number;
} | null;

type CreateToolDisplayState = {
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  transformMode: boolean;
};

const WORKSPACE_ERROR_AUTO_DISMISS_MS = 5000;

type SavedFormsBridge = {
  clearSavedFormsRetry: () => void;
  clearSavedForms: () => void;
  refreshSavedForms: (opts?: { allowRetry?: boolean; throwOnError?: boolean }) => Promise<unknown>;
};

type OpenAiRenameOptions = {
  confirm?: boolean;
  allowDefer?: boolean;
  sessionId?: string | null;
  schemaId?: string | null;
};

type ApplySchemaMappingsOptions = {
  fieldsOverride?: PdfField[];
  schemaIdOverride?: string | null;
};

type OpenAiBridge = {
  runOpenAiRename: (opts?: OpenAiRenameOptions) => Promise<PdfField[] | null>;
  applySchemaMappings: (opts?: ApplySchemaMappingsOptions) => Promise<boolean>;
  handleMappingSuccess: () => void;
  setHasRenamedFields: (value: boolean) => void;
  setHasMappedSchema: (value: boolean) => void;
  setCheckboxRules: (rules: CheckboxRule[]) => void;
  setRadioGroupSuggestions: (suggestions: RadioGroupSuggestion[]) => void;
  setTextTransformRules: (rules: TextTransformRule[]) => void;
  setOpenAiError: (value: string | null) => void;
};

type OpenAiSetterBridge = {
  setMappingInProgress: (value: boolean) => void;
  setOpenAiError: (value: string | null) => void;
};

/**
 * Main workspace runtime component that coordinates auth, detection, and editing.
 */
function WorkspaceRuntime({
  initialShowHomepage = true,
  launchIntent = null,
  assumeAuthReady = false,
  bootstrapHasVerifiedUser = false,
  bootstrapAuthUser = null,
  browserRoute = { kind: 'homepage' },
  onBrowserRouteChange,
}: WorkspaceRuntimeProps) {
  // ── Ref bridges to break circular hook dependencies ────────────────
  const savedFormsBridge = useRef<SavedFormsBridge>({
    clearSavedFormsRetry: () => {},
    clearSavedForms: () => {},
    refreshSavedForms: async () => [],
  });
  const openAiBridge = useRef<OpenAiBridge>({
    runOpenAiRename: async () => null,
    applySchemaMappings: async () => false,
    handleMappingSuccess: () => {},
    setHasRenamedFields: () => {},
    setHasMappedSchema: () => {},
    setCheckboxRules: () => {},
    setRadioGroupSuggestions: () => {},
    setTextTransformRules: () => {},
    setOpenAiError: () => {},
  });
  const openAiSettersForDataSource = useRef<OpenAiSetterBridge>({
    setMappingInProgress: () => {},
    setOpenAiError: () => {},
  });
  const clearWorkspaceRef = useRef<() => void>(() => {});
  const demoBridgeRef = useRef({ demoActive: false, demoCompletionOpen: false });

  // ── Independent hooks ──────────────────────────────────────────────
  const fieldHistory = useFieldHistory();
  const fieldState = useFieldState(
    fieldHistory.fieldsRef,
    fieldHistory.fields,
    fieldHistory.updateFields,
    fieldHistory.updateFieldsWith,
  );
  const dialog = useDialog();

  // ── Auth (uses savedForms via bridge) ──────────────────────────────
  const auth = useAuth({
    clearSavedFormsRetry: () => savedFormsBridge.current.clearSavedFormsRetry(),
    clearSavedForms: () => savedFormsBridge.current.clearSavedForms(),
    refreshSavedForms: (opts) => savedFormsBridge.current.refreshSavedForms(opts),
  });

  const groups = useGroups({
    verifiedUser: auth.verifiedUser,
    setBannerNotice: dialog.setBannerNotice,
  });

  // ── Saved forms (uses auth) ────────────────────────────────────────
  const savedForms = useSavedForms({
    authUserRef: auth.authUserRef,
    setBannerNotice: dialog.setBannerNotice,
    requestConfirm: dialog.requestConfirm,
    refreshGroups: groups.refreshGroups,
    refreshProfile: () => auth.loadUserProfile(),
  });
  savedFormsBridge.current = {
    clearSavedFormsRetry: savedForms.clearSavedFormsRetry,
    clearSavedForms: savedForms.clearSavedForms,
    refreshSavedForms: savedForms.refreshSavedForms,
  };

  // ── App-level state ────────────────────────────────────────────────
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [pendingPageJump, setPendingPageJump] = useState<number | null>(null);
  const [showHomepage, setShowHomepage] = useState(initialShowHomepage);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [isMobileView, setIsMobileView] = useState(false);
  const [showSearchFill, setShowSearchFill] = useState(false);
  const [showFillLinkManager, setShowFillLinkManager] = useState(false);
  const [showTemplateApiManager, setShowTemplateApiManager] = useState(false);
  const [transformMode, setTransformMode] = useState(false);
  const [activeCreateTool, setActiveCreateTool] = useState<CreateTool | null>(null);
  const [manualRadioToolDraft, setManualRadioToolDraft] = useState<RadioToolDraft | null>(null);
  const [quickRadioToolDraft, setQuickRadioToolDraft] = useState<RadioToolDraft | null>(null);
  const [pendingQuickRadioSelection, setPendingQuickRadioSelection] =
    useState<PendingQuickRadioSelection>(null);
  const [dismissedRadioSuggestionIds, setDismissedRadioSuggestionIds] = useState<string[]>([]);
  const [arrowKeyMoveEnabled, setArrowKeyMoveEnabled] = useState(false);
  const [arrowKeyMoveStep, setArrowKeyMoveStep] = useState(DEFAULT_ARROW_KEY_MOVE_STEP);
  const [searchFillSessionId, setSearchFillSessionId] = useState(0);
  const [searchFillPreset, setSearchFillPreset] = useState<SearchFillPresetState>(null);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceFileName, setSourceFileName] = useState<string | null>(null);
  const [sourceFileIsDemo, setSourceFileIsDemo] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savedFillLinkPublishFingerprint, setSavedFillLinkPublishFingerprint] = useState<string | null>(null);
  const browserRouteKey = useMemo(() => getWorkspaceBrowserRouteKey(browserRoute), [browserRoute]);
  const [pendingBrowserRouteKey, setPendingBrowserRouteKey] = useState<string | null>(
    browserRoute.kind === 'homepage' ? null : browserRouteKey,
  );
  const routeRestoreInFlightKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (
      routeRestoreInFlightKeyRef.current !== null &&
      routeRestoreInFlightKeyRef.current !== pendingBrowserRouteKey
    ) {
      routeRestoreInFlightKeyRef.current = null;
    }
  }, [pendingBrowserRouteKey]);
  const createToolDisplayStateRef = useRef<CreateToolDisplayState | null>(null);
  const fieldClickPageChangeRef = useRef(false);

  useEffect(() => {
    applyRouteSeo({ kind: 'app' });
  }, []);

  useEffect(() => {
    if (browserRoute.kind === 'homepage') {
      setPendingBrowserRouteKey(null);
      return;
    }
    setPendingBrowserRouteKey((current) => (current === browserRouteKey ? current : browserRouteKey));
  }, [browserRoute.kind, browserRouteKey]);

  const pdfState = useMemo(() => ({
    setPdfDoc, setPageSizes, setPageCount, setCurrentPage, setScale, setPendingPageJump,
  }), []);

  const captureSavedFillLinkPublishFingerprint = useCallback(
    (nextFields: PdfField[], nextCheckboxRules: CheckboxRule[]) => {
      setSavedFillLinkPublishFingerprint(buildFillLinkPublishFingerprint(nextFields, nextCheckboxRules));
    },
    [],
  );

  // ── Data source (uses auth, dialog; openAi setters via bridge) ─────
  const dataSource = useDataSource({
    verifiedUser: auth.verifiedUser,
    hasDocument: !!pdfDoc,
    setBannerNotice: dialog.setBannerNotice,
    setMappingInProgress: (v) => openAiSettersForDataSource.current.setMappingInProgress(v),
    setOpenAiError: (v) => openAiSettersForDataSource.current.setOpenAiError(v),
  });

  // ── Detection (uses many deps; openAi callbacks via bridge) ────────
  const detection = useDetection({
    verifiedUser: auth.verifiedUser,
    profileLimits: auth.profileLimits,
    fieldsRef: fieldHistory.fieldsRef,
    historyRef: fieldHistory.historyRef,
    resetFieldHistory: fieldHistory.resetFieldHistory,
    updateFields: fieldHistory.updateFields,
    setSelectedFieldId: fieldState.setSelectedFieldId,
    clearWorkspace: () => clearWorkspaceRef.current(),
    setBannerNotice: dialog.setBannerNotice,
    setShowHomepage,
    setShowSearchFill,
    setSearchFillSessionId,
    setLoadError,
    markSavedFillLinkSnapshot: captureSavedFillLinkPublishFingerprint,
    setSourceFile,
    setSourceFileName,
    setSourceFileIsDemo,
    setActiveSavedFormId: savedForms.setActiveSavedFormId,
    setActiveSavedFormName: savedForms.setActiveSavedFormName,
    schemaId: dataSource.schemaId,
    setSchemaError: dataSource.setSchemaError,
    // openAi callbacks via bridge
    runOpenAiRename: (opts) => openAiBridge.current.runOpenAiRename(opts),
    applySchemaMappings: (opts) => openAiBridge.current.applySchemaMappings(opts),
    handleMappingSuccess: () => openAiBridge.current.handleMappingSuccess(),
    setHasRenamedFields: (v) => openAiBridge.current.setHasRenamedFields(v),
    setHasMappedSchema: (v) => openAiBridge.current.setHasMappedSchema(v),
    setCheckboxRules: (v) => openAiBridge.current.setCheckboxRules(v),
    setRadioGroupSuggestions: (v) => openAiBridge.current.setRadioGroupSuggestions(v),
    setTextTransformRules: (v) => openAiBridge.current.setTextTransformRules(v),
    setOpenAiError: (v) => openAiBridge.current.setOpenAiError(v),
    // Session keep-alive deps
    pdfDoc,
    sourceFileIsDemo,
    sourceFileName,
    demoStateRef: demoBridgeRef,
  });
  const workspaceSessionDiagnostic = useWorkspaceSessionDiagnostic({
    detectSessionId: detection.detectSessionId,
    pageCount,
    activeSavedFormId: savedForms.activeSavedFormId,
    activeSavedFormName: savedForms.activeSavedFormName,
    sourceFileName,
  });
  const [reviewedFillContext, setReviewedFillContext] = useState<ReviewedFillContext | null>(null);
  const resolveWorkspaceSourcePdfBytes = useCallback(async (): Promise<Uint8Array> => {
    if (sourceFile) {
      return new Uint8Array(await sourceFile.arrayBuffer());
    }
    if (pdfDoc) {
      return pdfDoc.getData();
    }
    throw new Error('Load a PDF before preparing a signing request.');
  }, [pdfDoc, sourceFile]);
  const resolveWorkspaceImmutableSourcePdfBytes = useCallback(async (): Promise<Uint8Array> => {
    const sourcePdfBytes = await resolveWorkspaceSourcePdfBytes();
    const sourceBlob = new Blob([Uint8Array.from(sourcePdfBytes)], { type: 'application/pdf' });
    const materializedFields = prepareFieldsForMaterialize(fieldHistory.fields);
    const materializedBlob = await ApiService.materializeFormPdf(sourceBlob, materializedFields, { exportMode: 'flat' });
    return new Uint8Array(await materializedBlob.arrayBuffer());
  }, [fieldHistory.fields, resolveWorkspaceSourcePdfBytes]);

  // ── OpenAI pipeline (uses detection state directly) ────────────────
  const openAi = useOpenAiPipeline({
    verifiedUser: auth.verifiedUser,
    fieldsRef: fieldHistory.fieldsRef,
    loadTokenRef: detection.loadTokenRef,
    detectSessionId: detection.detectSessionId,
    setDetectSessionId: detection.setDetectSessionId,
    setMappingSessionId: detection.setMappingSessionId,
    activeSavedFormId: savedForms.activeSavedFormId,
    pageCount,
    dataColumns: dataSource.dataColumns,
    schemaId: dataSource.schemaId,
    pendingAutoActionsRef: detection.pendingAutoActionsRef,
    setBannerNotice: dialog.setBannerNotice,
    requestConfirm: dialog.requestConfirm,
    resolveSourcePdfBytes: resolveWorkspaceSourcePdfBytes,
    loadUserProfile: auth.loadUserProfile,
    resetFieldHistory: fieldHistory.resetFieldHistory,
    updateFieldsWith: fieldHistory.updateFieldsWith,
    setIdentifierKey: dataSource.setIdentifierKey,
    onBeforeOpenAiAction: workspaceSessionDiagnostic.onBeforeOpenAiAction,
    // For computed canRename/canMapSchema
    hasDocument: !!pdfDoc,
    fieldsCount: fieldHistory.fields.length,
    dataSourceKind: dataSource.dataSourceKind,
    hasSchemaOrPending: Boolean(dataSource.schemaId || dataSource.pendingSchemaPayload),
  });

  // ── Image fill (extract from uploaded images/documents) ───────────
  const imageFill = useImageFill({
    fieldsRef: fieldHistory.fieldsRef,
    sessionId: detection.detectSessionId,
    onUpdateField: fieldState.handleUpdateField,
    onLoadUserProfile: auth.loadUserProfile,
  });

  // Update bridges
  openAiBridge.current = {
    runOpenAiRename: openAi.runOpenAiRename,
    applySchemaMappings: openAi.applySchemaMappings,
    handleMappingSuccess: openAi.handleMappingSuccess,
    setHasRenamedFields: openAi.setHasRenamedFields,
    setHasMappedSchema: openAi.setHasMappedSchema,
    setCheckboxRules: openAi.setCheckboxRules,
    setRadioGroupSuggestions: openAi.setRadioGroupSuggestions,
    setTextTransformRules: openAi.setTextTransformRules,
    setOpenAiError: openAi.setOpenAiError,
  };
  openAiSettersForDataSource.current = {
    setMappingInProgress: openAi.setMappingInProgress,
    setOpenAiError: openAi.setOpenAiError,
  };

  const {
    activeGroupId,
    activeGroupName,
    activeGroupTemplates,
    pendingGroupTemplateId,
    groupTemplateStatusById,
    groupSwitchingTemplateId,
    groupUpload,
    groupRenameMapInProgress,
    groupRenameMapLabel,
    groupRenameMapDisabledReason,
    captureActiveGroupTemplateSnapshot,
    ensureGroupTemplateSnapshot,
    resolveGroupTemplateDirtyNames,
    markGroupTemplatesPersisted,
    handleSelectActiveGroupTemplate,
    handleFillSearchTargets,
    confirmDiscardDirtyGroupChanges,
    handleFillableUpload,
    handleSelectSavedForm,
    handleCreateGroup,
    handleUpdateGroup,
    handleDeleteSavedForm,
    handleSavedFormsLimitDelete,
    handleDeleteGroup,
    handleOpenGroup,
    runDetectUpload,
    handleRenameAndMapGroup,
    resetGroupRuntime,
  } = useWorkspaceGroupCoordinator({
    verifiedUser: auth.verifiedUser,
    userProfile: auth.userProfile,
    loadUserProfile: auth.loadUserProfile,
    profileLimits: auth.profileLimits,
    dialog: {
      setBannerNotice: dialog.setBannerNotice,
      requestConfirm: dialog.requestConfirm,
    },
    groups,
    savedForms,
    detection,
    openAi,
    document: {
      pdfDoc,
      sourceFile,
      sourceFileName,
      pageSizes,
      pageCount,
      currentPage,
      scale,
      setLoadError,
      setShowHomepage,
      setShowSearchFill,
      setSearchFillPreset,
      setShowFillLinkManager,
      setSourceFile,
      setSourceFileName,
      setSourceFileIsDemo,
      setPdfDoc,
      setPageSizes,
      setPageCount,
      setCurrentPage,
      setScale,
      setPendingPageJump,
      bumpSearchFillSession: () => setSearchFillSessionId((prev) => prev + 1),
    },
    pdfState,
    fieldHistory: {
      fields: fieldHistory.fields,
      fieldsRef: fieldHistory.fieldsRef,
      historyRef: fieldHistory.historyRef,
      historyTick: fieldHistory.historyTick,
      restoreState: fieldHistory.restoreState,
    },
    fieldSelection: {
      selectedFieldId: fieldState.selectedFieldId,
      setSelectedFieldId: fieldState.setSelectedFieldId,
      handleFieldsChange: fieldState.handleFieldsChange,
    },
    display: {
      showFields: fieldState.showFields,
      showFieldNames: fieldState.showFieldNames,
      showFieldInfo: fieldState.showFieldInfo,
      transformMode,
      setShowFields: fieldState.setShowFields,
      setShowFieldNames: fieldState.setShowFieldNames,
      setShowFieldInfo: fieldState.setShowFieldInfo,
      setTransformMode,
    },
    dataSource: {
      schemaId: dataSource.schemaId,
      schemaUploadInProgress: dataSource.schemaUploadInProgress,
      pendingSchemaPayload: dataSource.pendingSchemaPayload,
      persistSchemaPayload: dataSource.persistSchemaPayload,
      setSchemaUploadInProgress: dataSource.setSchemaUploadInProgress,
      dataColumns: dataSource.dataColumns,
      dataSourceKind: dataSource.dataSourceKind,
      resolveSchemaForMapping: dataSource.resolveSchemaForMapping,
    },
    markSavedFillLinkSnapshot: captureSavedFillLinkPublishFingerprint,
  });

  const handleSelectSavedFormFromProfile = useCallback(
    async (formId: string) => {
      if (isMobileView) {
        dialog.setBannerNotice({
          tone: 'info',
          message: 'Opening saved forms is desktop-only. Increase window width above 900px to reopen templates.',
          autoDismissMs: 8000,
        });
        return;
      }
      const opened = await handleSelectSavedForm(formId);
      if (opened) {
        auth.setShowProfile(false);
      }
    },
    [auth, dialog, handleSelectSavedForm, isMobileView],
  );

  const activeWorkspaceBrowserRoute = useMemo<WorkspaceBrowserRoute>(() => {
    if (showHomepage && browserRoute.kind === 'homepage') {
      return { kind: 'homepage' };
    }
    if (auth.showProfile) {
      return { kind: 'profile' };
    }
    if (activeGroupId) {
      return {
        kind: 'group',
        groupId: activeGroupId,
        templateId: savedForms.activeSavedFormId,
      };
    }
    if (savedForms.activeSavedFormId) {
      return {
        kind: 'saved-form',
        formId: savedForms.activeSavedFormId,
      };
    }
    if (pdfDoc || detection.isProcessing) {
      return { kind: 'ui-root' };
    }
    return { kind: 'upload-root' };
  }, [activeGroupId, auth.showProfile, browserRoute.kind, detection.isProcessing, pdfDoc, savedForms.activeSavedFormId, showHomepage]);

  const restoreViewportFromResume = useCallback((resumeState: ReturnType<typeof findMatchingWorkspaceResumeState>) => {
    if (!resumeState) {
      return;
    }
    const nextPage = Number.isFinite(resumeState.currentPage) && resumeState.currentPage
      ? Math.max(1, Math.min(Math.round(resumeState.currentPage), Math.max(1, pageCount)))
      : null;
    if (nextPage !== null) {
      setCurrentPage(nextPage);
    }
    if (Number.isFinite(resumeState.scale) && resumeState.scale && resumeState.scale > 0) {
      setScale(resumeState.scale);
    }
  }, [pageCount]);

  const resolvePreferredSessionResume = useCallback((
    resumeState: ReturnType<typeof findMatchingWorkspaceResumeState>,
  ): SavedFormSessionResume | null => {
    const preferredSessionId = resumeState?.mappingSessionId || resumeState?.detectSessionId;
    if (!preferredSessionId) {
      return null;
    }
    return {
      sessionId: preferredSessionId,
      fieldCount: resumeState?.fieldCount ?? null,
      pageCount: resumeState?.pageCount ?? null,
    };
  }, []);

  const tryReuseResumedSession = useCallback(async (
    resumeState: ReturnType<typeof findMatchingWorkspaceResumeState>,
  ) => {
    const preferredSession = resolvePreferredSessionResume(resumeState);
    if (!preferredSession?.sessionId) {
      return false;
    }
    if (
      (preferredSession.fieldCount !== null && preferredSession.fieldCount !== fieldHistory.fields.length) ||
      (preferredSession.pageCount !== null && preferredSession.pageCount !== pageCount)
    ) {
      return false;
    }
    try {
      await ApiService.touchSession(preferredSession.sessionId);
      detection.setDetectSessionId(preferredSession.sessionId);
      detection.setMappingSessionId(preferredSession.sessionId);
      return true;
    } catch {
      return false;
    }
  }, [detection, fieldHistory.fields.length, pageCount, resolvePreferredSessionResume]);

  const restoreUiWorkspaceFromResume = useCallback(async (
    resumeState: ReturnType<typeof findMatchingWorkspaceResumeState>,
  ) => {
    const preferredSession = resolvePreferredSessionResume(resumeState);
    if (!preferredSession?.sessionId) {
      return false;
    }

    try {
      const [sessionStatus, sessionPdf] = await Promise.all([
        fetchDetectionStatus(preferredSession.sessionId),
        ApiService.downloadSessionPdf(preferredSession.sessionId),
      ]);
      const sourcePdfName = String(sessionStatus?.sourcePdf || 'document.pdf').trim() || 'document.pdf';
      const sourceFile = new File([sessionPdf], sourcePdfName, { type: 'application/pdf' });
      const restored = await detection.restoreSessionWorkspace(
        sourceFile,
        {
          sessionId: preferredSession.sessionId,
          detectionStatus: String(sessionStatus?.status || '').trim().toLowerCase() || null,
          fields: mapDetectionFields(sessionStatus),
          checkboxRules: Array.isArray(sessionStatus?.checkboxRules) ? sessionStatus.checkboxRules : [],
          textTransformRules: Array.isArray(sessionStatus?.textTransformRules) ? sessionStatus.textTransformRules : [],
        },
        pdfState,
      );
      if (!restored) {
        return false;
      }
      restoreViewportFromResume(resumeState);
      return true;
    } catch (error) {
      debugLog('Failed to restore ui-root workspace session', preferredSession.sessionId, error);
      return false;
    }
  }, [detection, pdfState, resolvePreferredSessionResume, restoreViewportFromResume]);

  const headerActiveGroupTemplateId =
    pendingGroupTemplateId || groupSwitchingTemplateId || savedForms.activeSavedFormId;
  const headerGroupTemplateStatuses = useMemo(() => {
    const nextStatuses = { ...groupTemplateStatusById };
    const pendingTemplateId = pendingGroupTemplateId || groupSwitchingTemplateId;
    if (pendingTemplateId) {
      nextStatuses[pendingTemplateId] = 'loading';
    }
    return nextStatuses;
  }, [groupSwitchingTemplateId, groupTemplateStatusById, pendingGroupTemplateId]);

  const activeTemplateName = savedForms.activeSavedFormName || sourceFileName || null;
  const signing = useWorkspaceSigning({
    verifiedUser: auth.verifiedUser,
    hasDocument: Boolean(pdfDoc),
    sourceDocumentName: activeTemplateName,
    sourceTemplateId: savedForms.activeSavedFormId,
    sourceTemplateName: activeTemplateName,
    fields: fieldHistory.fields,
    resolveSourcePdfBytes: async () => resolveWorkspaceImmutableSourcePdfBytes(),
    reviewedFillContext,
  });
  const {
    canTriggerFillLink,
    handleOpenFillLinkManager,
    clearAllFillLinks,
    dialogProps: fillLinkManagerDialogProps,
  } = useWorkspaceFillLinks({
    verifiedUser: auth.verifiedUser,
    profileLimits: auth.profileLimits,
    managerOpen: showFillLinkManager,
    setManagerOpen: setShowFillLinkManager,
    setBannerNotice: dialog.setBannerNotice,
    activeTemplateId: savedForms.activeSavedFormId,
    activeTemplateName,
    activeGroupId,
    activeGroupName,
    activeGroupTemplates,
    fields: fieldHistory.fields,
    checkboxRules: openAi.checkboxRules,
    textTransformRules: openAi.textTransformRules,
    savedFillLinkPublishFingerprint,
    resolveGroupTemplateDirtyNames,
    ensureGroupTemplateSnapshot,
    applyStructuredDataSource: dataSource.applyStructuredDataSource,
    clearFieldValues: fieldState.handleClearFieldValues,
    setSearchFillPreset,
    setShowSearchFill,
    bumpSearchFillSession: () => setSearchFillSessionId((prev) => prev + 1),
  });

  useEffect(() => {
    if (auth.verifiedUser) return;
    clearAllFillLinks();
    setShowFillLinkManager(false);
  }, [auth.verifiedUser, clearAllFillLinks]);

  const {
    canOpenTemplateApi,
    handleOpenTemplateApiManager,
    clearTemplateApiManager,
    dialogProps: templateApiManagerDialogProps,
  } = useWorkspaceTemplateApi({
    verifiedUser: auth.verifiedUser,
    managerOpen: showTemplateApiManager,
    setManagerOpen: setShowTemplateApiManager,
    setBannerNotice: dialog.setBannerNotice,
    activeTemplateId: savedForms.activeSavedFormId,
    activeTemplateName,
    activeGroupId,
  });

  useEffect(() => {
    if (auth.verifiedUser) return;
    clearTemplateApiManager();
    setShowTemplateApiManager(false);
  }, [auth.verifiedUser, clearTemplateApiManager]);

  // ── Pipeline modal (uses runDetectUpload, dataSource, auth) ────────
  const pipeline = usePipelineModal({
    verifiedUser: auth.verifiedUser,
    loadUserProfile: auth.loadUserProfile,
    userProfile: auth.userProfile,
    detectMaxPages: auth.profileLimits.detectMaxPages,
    schemaId: dataSource.schemaId,
    schemaUploadInProgress: dataSource.schemaUploadInProgress,
    pendingSchemaPayload: dataSource.pendingSchemaPayload,
    persistSchemaPayload: dataSource.persistSchemaPayload,
    setSchemaUploadInProgress: dataSource.setSchemaUploadInProgress,
    runDetectUpload,
  });

  // ── clearWorkspace ─────────────────────────────────────────────────
  const clearWorkspace = useCallback(() => {
    resetGroupRuntime();
    // App-level PDF state
    setPdfDoc(null); setPageSizes({}); setPageCount(0); setCurrentPage(1);
    setScale(1); setPendingPageJump(null);
    // Hook resets
    fieldHistory.reset();
    fieldState.reset();
    detection.reset();
    openAi.reset();
    dataSource.reset();
    savedForms.reset();
    clearAllFillLinks();
    clearTemplateApiManager();
    dialog.reset();
    pipeline.reset();
    // App-level UI state
    setShowSearchFill(false); setSearchFillSessionId((prev) => prev + 1);
    setSearchFillPreset(null); setShowFillLinkManager(false); setShowTemplateApiManager(false);
    createToolDisplayStateRef.current = null;
    setTransformMode(false); setActiveCreateTool(null);
    setManualRadioToolDraft(null); setQuickRadioToolDraft(null);
    setPendingQuickRadioSelection(null); setDismissedRadioSuggestionIds([]);
    setSourceFile(null); setSourceFileName(null); setSourceFileIsDemo(false);
    setReviewedFillContext(null);
  }, [clearAllFillLinks, clearTemplateApiManager, dataSource, detection, dialog, fieldHistory, fieldState, openAi, pipeline, resetGroupRuntime, savedForms]);
  clearWorkspaceRef.current = clearWorkspace;

  // ── Demo (uses wrapped handlers) ───────────────────────────────────
  const demo = useDemo({
    pdfDoc,
    sourceFileName,
    dataColumns: dataSource.dataColumns,
    resetFieldHistory: fieldHistory.resetFieldHistory,
    setSelectedFieldId: fieldState.setSelectedFieldId,
    setShowFields: fieldState.setShowFields,
    setShowFieldNames: fieldState.setShowFieldNames,
    setShowFieldInfo: fieldState.setShowFieldInfo,
    setHasRenamedFields: openAi.setHasRenamedFields,
    setHasMappedSchema: openAi.setHasMappedSchema,
    setShowSearchFill,
    setShowHomepage,
    setLoadError,
    clearWorkspace,
    handleFillableUpload,
    applyParsedDataSource: dataSource.applyParsedDataSource,
    notifyHeaderRenames: dataSource.notifyHeaderRenames,
  });
  demoBridgeRef.current = { demoActive: demo.demoActive, demoCompletionOpen: demo.demoCompletionOpen };

  // ── Auth-related callbacks ─────────────────────────────────────────
  const returnRuntimeToHomepage = useCallback((options?: {
    clearSavedForms?: boolean;
    clearLoadError?: boolean;
    clearLogin?: boolean;
    clearProfile?: boolean;
    clearOnboarding?: boolean;
  }) => {
    clearWorkspace();
    if (options?.clearSavedForms) {
      savedForms.clearSavedForms();
    }
    if (options?.clearLoadError) {
      setLoadError(null);
    }
    if (options?.clearLogin) {
      auth.setShowLogin(false);
    }
    if (options?.clearProfile) {
      auth.setShowProfile(false);
    }
    if (options?.clearOnboarding) {
      setShowOnboarding(false);
    }
    setPendingBrowserRouteKey(null);
    setShowHomepage(true);
    demo.setDemoActive(false);
    demo.setDemoStepIndex(null);
    demo.setDemoCompletionOpen(false);
    demo.setDemoSearchPreset(null);
    returnWorkspaceToHomepage(onBrowserRouteChange);
  }, [auth, clearWorkspace, demo, onBrowserRouteChange, savedForms]);

  const handleSignOut = useCallback(async () => {
    const confirmed = await confirmDiscardDirtyGroupChanges('signing out');
    if (!confirmed) return;
    // Tear down workspace state and unmount the runtime BEFORE clearing auth
    // so the component never renders with a null user (white screen).
    returnRuntimeToHomepage({
      clearSavedForms: true,
      clearLogin: true,
      clearOnboarding: true,
      clearProfile: true,
    });
    await auth.handleSignOut();
  }, [auth, confirmDiscardDirtyGroupChanges, returnRuntimeToHomepage]);

  const handleNavigateHome = useCallback(async () => {
    const confirmed = await confirmDiscardDirtyGroupChanges('returning home');
    if (!confirmed) return;
    returnRuntimeToHomepage({ clearLoadError: true });
  }, [confirmDiscardDirtyGroupChanges, returnRuntimeToHomepage]);

  // ── Save & Download ────────────────────────────────────────────────
  const saveDownload = useSaveDownload({
    pdfDoc,
    sourceFile,
    sourceFileName,
    fields: fieldHistory.fields,
    pageSizes,
    pageCount,
    checkboxRules: openAi.checkboxRules,
    textTransformRules: openAi.textTransformRules,
    hasRenamedFields: openAi.hasRenamedFields,
    hasMappedSchema: openAi.hasMappedSchema,
    mappingSessionId: detection.mappingSessionId,
    activeSavedFormId: savedForms.activeSavedFormId,
    activeSavedFormName: savedForms.activeSavedFormName,
    activeGroupId,
    activeGroupName,
    savedFormsCount: savedForms.savedForms.length,
    savedFormsMax: auth.profileLimits.savedFormsMax,
    verifiedUser: auth.verifiedUser,
    setBannerNotice: dialog.setBannerNotice,
    setLoadError,
    requestConfirm: dialog.requestConfirm,
    requestPrompt: dialog.requestPrompt,
    refreshSavedForms: savedForms.refreshSavedForms,
    refreshGroups: groups.refreshGroups,
    refreshProfile: auth.loadUserProfile,
    setActiveSavedFormId: savedForms.setActiveSavedFormId,
    setActiveSavedFormName: savedForms.setActiveSavedFormName,
    markGroupTemplatesPersisted,
    queueSaveAfterLimit: savedForms.queueSaveAfterLimit,
    allowAnonymousDownload: sourceFileIsDemo,
    onSaveSuccess: captureSavedFillLinkPublishFingerprint,
  });
  const groupDownload = useGroupDownload({
    verifiedUser: auth.verifiedUser,
    activeGroupId,
    activeGroupName,
    activeGroupTemplates,
    activeSavedFormId: savedForms.activeSavedFormId,
    captureActiveGroupTemplateSnapshot,
    ensureGroupTemplateSnapshot,
    setLoadError,
    setBannerNotice: dialog.setBannerNotice,
  });

  // ── OpenAI header bar handlers ─────────────────────────────────────
  const handleRename = openAi.handleRename;
  const handleRenameAndMap = useCallback(
    () => openAi.handleRenameAndMap(dataSource.resolveSchemaForMapping),
    [openAi.handleRenameAndMap, dataSource.resolveSchemaForMapping],
  );
  const handleMapSchema = useCallback(
    () => openAi.handleMapSchema(dataSource.resolveSchemaForMapping),
    [openAi.handleMapSchema, dataSource.resolveSchemaForMapping],
  );

  // ── Field interaction handlers ─────────────────────────────────────
  const handleSelectField = useCallback(
    (fieldId: string) => {
      fieldState.setSelectedFieldId(fieldId);
      const field = fieldHistory.fieldsRef.current.find((entry) => entry.id === fieldId);
      if (!field) return;
      if (field.page && field.page !== currentPage) {
        fieldClickPageChangeRef.current = true;
        setCurrentPage(field.page);
      }
    },
    [currentPage, fieldHistory.fieldsRef, fieldState],
  );

  const handlePageJump = useCallback((page: number) => {
    setCurrentPage(page); setPendingPageJump(page);
    fieldState.setSelectedFieldId((prev: string | null) => {
      if (!prev) return prev;
      const field = fieldHistory.fieldsRef.current.find((entry) => entry.id === prev);
      if (!field) return prev;
      return field.page === page ? prev : null;
    });
  }, [fieldHistory.fieldsRef, fieldState]);

  const handlePageScroll = useCallback((page: number) => {
    setCurrentPage(page);
    if (fieldClickPageChangeRef.current) {
      fieldClickPageChangeRef.current = false;
      return;
    }
    fieldState.setSelectedFieldId((prev: string | null) => {
      if (!prev) return prev;
      const field = fieldHistory.fieldsRef.current.find((entry) => entry.id === prev);
      if (!field) return prev;
      return field.page === page ? prev : null;
    });
  }, [fieldHistory.fieldsRef, fieldState]);

  const handlePageJumpComplete = useCallback(() => { setPendingPageJump(null); }, []);

  const resetCreateToolState = useCallback(() => {
    setActiveCreateTool(null);
    setPendingQuickRadioSelection(null);
    setManualRadioToolDraft(null);
    setQuickRadioToolDraft(null);
  }, []);

  const clearCreateToolState = useCallback(() => {
    createToolDisplayStateRef.current = null;
    resetCreateToolState();
  }, [resetCreateToolState]);

  const applyCreateToolDisplayState = useCallback((state: CreateToolDisplayState) => {
    setTransformMode(state.transformMode);
    fieldState.setShowFields(state.showFields);
    fieldState.setShowFieldNames(state.showFieldNames);
    fieldState.setShowFieldInfo(state.showFieldInfo);
  }, [fieldState]);

  const handleSetTransformMode = useCallback(
    (enabled: boolean) => {
      setTransformMode(enabled);
      if (enabled) {
        clearCreateToolState();
        fieldState.setShowFields(true);
        fieldState.setShowFieldInfo(false);
      }
    },
    [clearCreateToolState, fieldState],
  );

  const handleSetCreateTool = useCallback(
    (type: CreateTool | null) => {
      const currentFields = fieldHistory.fieldsRef.current;
      if (!type) {
        const previousDisplayState = activeCreateTool ? createToolDisplayStateRef.current : null;
        createToolDisplayStateRef.current = null;
        resetCreateToolState();
        if (previousDisplayState) {
          applyCreateToolDisplayState(previousDisplayState);
        }
        return;
      }
      if (!activeCreateTool) {
        createToolDisplayStateRef.current = {
          showFields: fieldState.showFields,
          showFieldNames: fieldState.showFieldNames,
          showFieldInfo: fieldState.showFieldInfo,
          transformMode,
        };
      }
      setActiveCreateTool(type);
      setPendingQuickRadioSelection(null);
      setManualRadioToolDraft((prev) => (
        resolveRadioToolDraftForToolChange('radio', type, activeCreateTool, prev, currentFields)
      ));
      setQuickRadioToolDraft((prev) => (
        resolveRadioToolDraftForToolChange('quick-radio', type, activeCreateTool, prev, currentFields)
      ));
      if (type) {
        setTransformMode(false);
        fieldState.setShowFields(true);
        fieldState.setShowFieldNames(false);
        fieldState.setShowFieldInfo(false);
      }
    },
    [
      activeCreateTool,
      applyCreateToolDisplayState,
      fieldHistory.fieldsRef,
      fieldState,
      resetCreateToolState,
      transformMode,
    ],
  );

  const handleAfterSearchFill = useCallback((payload: { row: Record<string, unknown>; dataSourceKind: DataSourceKind }) => {
    setSearchFillPreset(null);
    handleSetTransformMode(false);
    clearCreateToolState();
    fieldState.setShowFieldInfo(true);
    fieldState.setShowFieldNames(false);
    fieldState.setShowFields(true);

    const responseId = typeof payload.row[FILL_LINK_RESPONSE_ID_KEY] === 'string'
      ? payload.row[FILL_LINK_RESPONSE_ID_KEY] as string
      : null;
    const linkId = typeof payload.row[FILL_LINK_LINK_ID_KEY] === 'string'
      ? payload.row[FILL_LINK_LINK_ID_KEY] as string
      : null;
    const respondentLabel = typeof payload.row[FILL_LINK_RESPONDENT_LABEL_KEY] === 'string'
      ? payload.row[FILL_LINK_RESPONDENT_LABEL_KEY] as string
      : null;

    if (payload.dataSourceKind === 'respondent' && responseId) {
      setReviewedFillContext({
        sourceType: 'fill_link_response',
        sourceId: responseId,
        sourceLinkId: linkId,
        sourceRecordLabel: respondentLabel,
        sourceLabel: dataSource.dataSourceLabel,
        reviewedAt: new Date().toISOString(),
      });
    } else {
      setReviewedFillContext({
        sourceType: 'workspace',
        sourceId: savedForms.activeSavedFormId,
        sourceLabel: dataSource.dataSourceLabel,
        reviewedAt: new Date().toISOString(),
      });
    }

    if (demo.demoActive && DEMO_STEPS[demo.demoStepIndex ?? -1]?.id === 'search-fill') {
      demo.handleDemoCompletion();
    }
  }, [
    dataSource.dataSourceLabel,
    demo,
    fieldState,
    clearCreateToolState,
    handleSetTransformMode,
    savedForms.activeSavedFormId,
  ]);

  const handleCreateFieldWithRect = useCallback(
    (page: number, type: FieldType, rect: { x: number; y: number; width: number; height: number }) => {
      const pageSize = pageSizes[page];
      if (!pageSize) return;
      let createdFieldId: string | null = null;
      let nextRadioDraft: RadioToolDraft | null = null;
      fieldHistory.updateFieldsWith((prev) => {
        const created =
          type === 'radio' && manualRadioToolDraft
            ? createRadioFieldFromRect(prev, page, pageSize, rect, manualRadioToolDraft)
            : createFieldWithRect(type, page, pageSize, prev, rect);
        createdFieldId = created.id;
        const nextFields = [...prev, created];
        if (type === 'radio' && manualRadioToolDraft) {
          nextRadioDraft = advanceRadioToolDraft(nextFields, manualRadioToolDraft);
        }
        return nextFields;
      });
      if (createdFieldId) {
        fieldState.setSelectedFieldId(createdFieldId);
      }
      if (type === 'radio' && nextRadioDraft) {
        setManualRadioToolDraft(nextRadioDraft);
      }
    },
    [fieldHistory, fieldState, manualRadioToolDraft, pageSizes],
  );

  const handleSetFieldType = useCallback(
    (fieldId: string, type: FieldType) => {
      const current = fieldHistory.fieldsRef.current.find((field) => field.id === fieldId);
      if (!current) return;
      if (current.type === type) {
        return;
      }
      const pageSize = pageSizes[current.page];
      const nextRect = pageSize
        ? normalizeRectForFieldType(current.rect, type, pageSize)
        : current.rect;
      if (type === 'radio') {
        const baseDraft = buildNextRadioToolDraft(fieldHistory.fieldsRef.current, current.groupLabel || current.name);
        let nextDraft: RadioToolDraft | null = null;
        fieldHistory.updateFieldsWith((prev) => {
          const nextFields = convertFieldsToRadioGroup(
            prev.map((field) => (
              field.id === fieldId
                ? { ...field, rect: nextRect }
                : field
            )),
            [fieldId],
            baseDraft,
            pageSizes,
          );
          nextDraft = advanceRadioToolDraft(nextFields, baseDraft);
          return nextFields;
        });
        setManualRadioToolDraft(nextDraft ?? baseDraft);
        fieldState.setSelectedFieldId(fieldId);
        return;
      }
      if (current.type === 'radio') {
        fieldHistory.updateFieldsWith((prev) => prev.map((field) => {
          if (field.id !== fieldId) return field;
          return {
            ...convertRadioFieldToType(field, type),
            rect: nextRect,
          };
        }));
        return;
      }
      fieldState.handleUpdateField(fieldId, { type, rect: nextRect });
    },
    [fieldHistory.fieldsRef, fieldHistory, fieldState, pageSizes],
  );

  const handleUpdateRadioToolDraft = useCallback(
    (updates: Partial<RadioToolDraft>) => {
      if (activeCreateTool === 'radio') {
        setManualRadioToolDraft((prev) => (prev ? { ...prev, ...updates } : prev));
        return;
      }
      if (activeCreateTool === 'quick-radio') {
        setQuickRadioToolDraft((prev) => (prev ? { ...prev, ...updates } : prev));
      }
    },
    [activeCreateTool],
  );

  const handleQuickRadioSelection = useCallback(
    (fieldIds: string[], page: number) => {
      setPendingQuickRadioSelection(fieldIds.length ? { fieldIds, page } : null);
      if (fieldIds[0]) {
        fieldState.setSelectedFieldId(fieldIds[0]);
      }
    },
    [fieldState],
  );

  const handleRemovePendingQuickRadioField = useCallback((fieldId: string) => {
    setPendingQuickRadioSelection((prev) => {
      if (!prev) return prev;
      const nextFieldIds = prev.fieldIds.filter((id) => id !== fieldId);
      if (!nextFieldIds.length) {
        return null;
      }
      return { ...prev, fieldIds: nextFieldIds };
    });
  }, []);

  const handleCancelPendingQuickRadioSelection = useCallback(() => {
    setPendingQuickRadioSelection(null);
  }, []);

  const handleApplyPendingQuickRadioSelection = useCallback(() => {
    const validSelection = prunePendingQuickRadioSelection(
      pendingQuickRadioSelection,
      fieldHistory.fieldsRef.current,
      currentPage,
    );
    if (!quickRadioToolDraft || !validSelection?.fieldIds.length) {
      setPendingQuickRadioSelection(null);
      return;
    }
    const selectedIds = validSelection.fieldIds;
    let nextFieldsSnapshot = fieldHistory.fieldsRef.current;
    fieldHistory.updateFieldsWith((prev) => {
      const nextFields = convertFieldsToRadioGroup(prev, selectedIds, quickRadioToolDraft, pageSizes);
      nextFieldsSnapshot = nextFields;
      return nextFields;
    });
    fieldState.setSelectedFieldId(selectedIds[0] || null);
    setPendingQuickRadioSelection(null);
    setQuickRadioToolDraft(buildNextRadioToolDraft(nextFieldsSnapshot));
  }, [currentPage, fieldHistory, fieldState, pageSizes, pendingQuickRadioSelection, quickRadioToolDraft]);

  const handleRenameSelectedRadioGroup = useCallback(
    (groupId: string, updates: { label?: string; key?: string }) => {
      fieldHistory.updateFieldsWith((prev) => renameRadioGroup(prev, groupId, updates));
      setManualRadioToolDraft((prev) => (
        prev && prev.groupId === groupId
          ? {
              ...prev,
              groupKey: updates.key ?? prev.groupKey,
              groupLabel: updates.label ?? prev.groupLabel,
            }
          : prev
      ));
    },
    [fieldHistory],
  );

  const handleUpdateSelectedRadioOption = useCallback(
    (fieldId: string, updates: { label?: string; key?: string }) => {
      fieldHistory.updateFieldsWith((prev) => updateRadioFieldOption(prev, fieldId, updates));
    },
    [fieldHistory],
  );

  const handleMoveSelectedRadioField = useCallback(
    (fieldId: string, targetGroup: RadioGroup) => {
      fieldHistory.updateFieldsWith((prev) => moveRadioFieldToGroup(prev, fieldId, targetGroup));
    },
    [fieldHistory],
  );

  const handleReorderSelectedRadioField = useCallback(
    (fieldId: string, direction: 'up' | 'down') => {
      fieldHistory.updateFieldsWith((prev) => reorderRadioField(prev, fieldId, direction));
    },
    [fieldHistory],
  );

  const handleDissolveSelectedRadioGroup = useCallback(
    (groupId: string) => {
      fieldHistory.updateFieldsWith((prev) => dissolveRadioGroup(prev, groupId));
      setPendingQuickRadioSelection(null);
    },
    [fieldHistory],
  );

  const handleSelectRadioFieldValue = useCallback(
    (fieldId: string) => {
      fieldHistory.updateFieldsWith((prev) => setRadioGroupSelectedValue(prev, fieldId));
      fieldState.setSelectedFieldId(fieldId);
    },
    [fieldHistory, fieldState],
  );

  const handleDismissRadioSuggestion = useCallback((suggestionId: string) => {
    setDismissedRadioSuggestionIds((prev) => (
      prev.includes(suggestionId) ? prev : [...prev, suggestionId]
    ));
  }, []);

  const handleApplyRadioSuggestion = useCallback((suggestion: RadioGroupSuggestion) => {
    const nextFields = applyRadioGroupSuggestion(fieldHistory.fieldsRef.current, suggestion);
    if (nextFields === fieldHistory.fieldsRef.current) {
      return;
    }
    fieldHistory.beginFieldHistory();
    fieldHistory.updateFields(nextFields, { trackHistory: false });
    fieldHistory.commitFieldHistory();
    const firstTargetId = buildRadioSuggestionFieldMap(nextFields, [suggestion]).keys().next().value ?? null;
    if (firstTargetId) {
      fieldState.setSelectedFieldId(firstTargetId);
    }
    setDismissedRadioSuggestionIds((prev) => (
      prev.includes(suggestion.id) ? prev : [...prev, suggestion.id]
    ));
    clearCreateToolState();
  }, [clearCreateToolState, fieldHistory, fieldState]);

  const handleApplyDisplayPreset = useCallback(
    (preset: Exclude<FieldListDisplayPreset, 'custom'>) => {
      if (preset === 'review') {
        handleSetTransformMode(false);
        clearCreateToolState();
        fieldState.setShowFields(true);
        fieldState.setShowFieldNames(true);
        fieldState.setShowFieldInfo(false);
        return;
      }
      if (preset === 'edit') {
        handleSetTransformMode(true);
        fieldState.setShowFields(true);
        fieldState.setShowFieldNames(false);
        fieldState.setShowFieldInfo(false);
        return;
      }
      handleSetTransformMode(false);
      clearCreateToolState();
      fieldState.setShowFields(true);
      fieldState.setShowFieldNames(false);
      fieldState.setShowFieldInfo(true);
    },
    [clearCreateToolState, fieldState, handleSetTransformMode],
  );

  const handleShowFieldsChange = useCallback(
    (enabled: boolean) => {
      if (!enabled) {
        clearCreateToolState();
      }
      fieldState.handleShowFieldsChange(enabled);
    },
    [clearCreateToolState, fieldState],
  );

  const handleShowFieldInfoChange = useCallback(
    (enabled: boolean) => {
      if (enabled) {
        handleSetTransformMode(false);
        clearCreateToolState();
      }
      fieldState.handleShowFieldInfoChange(enabled);
    },
    [clearCreateToolState, fieldState, handleSetTransformMode],
  );

  const handleResetConfidenceFilters = useCallback(() => {
    fieldState.setConfidenceFilter({ high: true, medium: true, low: true });
  }, [fieldState]);

  const handleUndo = useCallback(
    () => fieldHistory.handleUndo((updater) => fieldState.setSelectedFieldId(updater)),
    [fieldHistory, fieldState],
  );

  const handleRedo = useCallback(
    () => fieldHistory.handleRedo((updater) => fieldState.setSelectedFieldId(updater)),
    [fieldHistory, fieldState],
  );

  const initializedEditorDocRef = useRef<PDFDocumentProxy | null>(null);

  useEffect(() => {
    if (!pdfDoc) {
      initializedEditorDocRef.current = null;
      return;
    }
    if (initializedEditorDocRef.current === pdfDoc) {
      return;
    }
    initializedEditorDocRef.current = pdfDoc;
    // Group template restores its own cached display state. Do not overwrite it
    // with the default editor preset each time the active template PDF swaps.
    if (activeGroupId) {
      return;
    }
    if (fieldState.showFields && !fieldState.showFieldNames && !fieldState.showFieldInfo && transformMode) {
      return;
    }
    if (activeCreateTool) {
      return;
    }
    handleApplyDisplayPreset('edit');
  }, [
    activeCreateTool,
    activeGroupId,
    fieldState.showFieldInfo,
    fieldState.showFieldNames,
    fieldState.showFields,
    handleApplyDisplayPreset,
    pdfDoc,
    transformMode,
  ]);

  const handleDismissBanner = useCallback(() => {
    if (openAi.openAiError || dataSource.schemaError) {
      dataSource.setSchemaError(null);
      openAi.setOpenAiError(null);
    }
    if (dialog.bannerNotice) dialog.setBannerNotice(null);
  }, [dataSource, dialog.bannerNotice, openAi]);

  // ── Effects ────────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mediaQuery = window.matchMedia('(max-width: 900px)');
    const update = () => setIsMobileView(mediaQuery.matches);
    update();
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', update);
      return () => mediaQuery.removeEventListener('change', update);
    }
    const legacyMediaQuery = mediaQuery as MediaQueryList & {
      addListener: (listener: (event: MediaQueryListEvent) => void) => void;
      removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
    };
    legacyMediaQuery.addListener(update);
    return () => legacyMediaQuery.removeListener(update);
  }, []);

  const mobileViewTransitionRef = useRef(false);
  useEffect(() => {
    const wasMobile = mobileViewTransitionRef.current;
    mobileViewTransitionRef.current = isMobileView;

    if (
      !isMobileView ||
      auth.showLogin ||
      auth.showProfile ||
      showOnboarding ||
      auth.requiresEmailVerification
    ) {
      return;
    }
    const transitionedToMobile = !wasMobile && isMobileView;
    const hadWorkflowView = !showHomepage || browserRoute.kind !== 'homepage';
    if (
      transitionedToMobile &&
      hadWorkflowView &&
      !dialog.bannerNotice &&
      !openAi.openAiError &&
      !dataSource.schemaError
    ) {
      dialog.setBannerNotice({
        tone: 'info',
        message:
          'Mobile keeps the marketing shell only. Increase window width above 900px to reopen the full editor.',
        autoDismissMs: 8000,
      });
    }
    if (!showHomepage) {
      setShowHomepage(true);
    }
    if (browserRoute.kind !== 'homepage') {
      clearWorkspaceResumeState();
      setPendingBrowserRouteKey(null);
      onBrowserRouteChange?.({ kind: 'homepage' }, { replace: true });
    }
  }, [
    browserRoute.kind,
    dataSource.schemaError,
    dialog,
    isMobileView,
    onBrowserRouteChange,
    openAi.openAiError,
    showHomepage,
    showOnboarding,
    auth.requiresEmailVerification,
    auth.showLogin,
    auth.showProfile,
  ]);

  useEffect(() => {
    if (openAi.openAiError || dataSource.schemaError) dialog.setBannerNotice(null);
  }, [dataSource.schemaError, dialog, openAi.openAiError]);

  useEffect(() => {
    if (!dialog.bannerNotice) return undefined;
    const dismissMs = dialog.bannerNotice.tone === 'error'
      ? WORKSPACE_ERROR_AUTO_DISMISS_MS
      : dialog.bannerNotice.autoDismissMs;
    if (!dismissMs) return undefined;
    const timer = setTimeout(() => dialog.setBannerNotice(null), dismissMs);
    return () => clearTimeout(timer);
  }, [dialog.bannerNotice, dialog.setBannerNotice]);

  useEffect(() => {
    if (!openAi.openAiError && !dataSource.schemaError) return undefined;
    const timer = setTimeout(() => {
      openAi.setOpenAiError(null);
      dataSource.setSchemaError(null);
    }, WORKSPACE_ERROR_AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [
    dataSource.schemaError,
    dataSource.setSchemaError,
    openAi.openAiError,
    openAi.setOpenAiError,
  ]);

  useEffect(() => {
    if (!loadError) return undefined;
    const timer = setTimeout(() => setLoadError(null), WORKSPACE_ERROR_AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [loadError]);

  const focusFieldSearch = useCallback(() => {
    if (typeof document === 'undefined') return;
    const input = document.getElementById('field-search');
    if (!(input instanceof HTMLInputElement)) return;
    input.focus();
    input.select();
  }, []);

  const nudgeSelectedField = useCallback(
    (deltaX: number, deltaY: number, step = 1) => {
      const selectedId = fieldState.selectedFieldId;
      if (!selectedId) return;
      const selectedField = fieldHistory.fieldsRef.current.find((field) => field.id === selectedId);
      if (!selectedField) return;
      const pageSize = pageSizes[selectedField.page];
      if (!pageSize) return;

      const nextRect = clampRectToPage(
        {
          ...selectedField.rect,
          x: selectedField.rect.x + deltaX * step,
          y: selectedField.rect.y + deltaY * step,
        },
        pageSize,
        getMinFieldSize(selectedField.type),
      );
      fieldState.handleUpdateField(selectedId, { rect: nextRect });
    },
    [fieldHistory.fieldsRef, fieldState, pageSizes],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!pdfDoc || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (shouldIgnoreWorkspaceHotkeys(target)) {
        return;
      }
      const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
      const modifier = isMac ? event.metaKey : event.ctrlKey;
      const key = event.key.toLowerCase();

      if (!modifier && !event.altKey) {
        if (key === 'escape') {
          if (activeCreateTool) {
            event.preventDefault();
            handleSetCreateTool(null);
          }
          return;
        }
        if (key === 't') {
          event.preventDefault();
          handleSetCreateTool('text');
          return;
        }
        if (key === 'd') {
          event.preventDefault();
          handleSetCreateTool('date');
          return;
        }
        if (key === 's') {
          event.preventDefault();
          handleSetCreateTool('signature');
          return;
        }
        if (key === 'c') {
          event.preventDefault();
          handleSetCreateTool('checkbox');
          return;
        }
        if (key === 'r') {
          event.preventDefault();
          handleSetCreateTool('radio');
          return;
        }
        if (key === 'q') {
          event.preventDefault();
          handleSetCreateTool('quick-radio');
          return;
        }
        if (key === 'delete' || key === 'backspace') {
          if (!fieldState.selectedFieldId) return;
          event.preventDefault();
          fieldState.handleDeleteField(fieldState.selectedFieldId);
          return;
        }
        if (key === '[' && pageCount > 0) {
          event.preventDefault();
          handlePageJump(Math.max(1, currentPage - 1));
          return;
        }
        if (key === ']' && pageCount > 0) {
          event.preventDefault();
          handlePageJump(Math.min(pageCount, currentPage + 1));
          return;
        }
        if (key === '/') {
          event.preventDefault();
          focusFieldSearch();
          return;
        }
      }

      const nudgeCommand = getFieldNudgeCommandFromKey({
        key,
        altKey: event.altKey,
        shiftKey: event.shiftKey,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        arrowKeyMoveEnabled,
        arrowKeyMoveStep,
      });
      if (nudgeCommand) {
        if (!transformMode || fieldState.showFieldInfo) return;
        if (!fieldState.selectedFieldId) return;
        event.preventDefault();
        nudgeSelectedField(nudgeCommand.deltaX, nudgeCommand.deltaY, nudgeCommand.step);
        return;
      }

      if (!modifier) return;

      if (key === 'f') {
        event.preventDefault();
        focusFieldSearch();
        return;
      }
      if (key === '0') {
        event.preventDefault();
        setScale(1);
        return;
      }
      if (key === 'z') {
        event.preventDefault();
        if (event.shiftKey) handleRedo(); else handleUndo();
      } else if (key === 'x') {
        if (!fieldState.selectedFieldId) return;
        event.preventDefault();
        fieldState.handleDeleteField(fieldState.selectedFieldId);
      } else if (key === 'backspace') {
        if (!fieldState.selectedFieldId) return;
        event.preventDefault();
        fieldState.handleDeleteField(fieldState.selectedFieldId);
      } else if (key === 'y') {
        event.preventDefault(); handleRedo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    activeCreateTool,
    arrowKeyMoveEnabled,
    arrowKeyMoveStep,
    currentPage,
    fieldState,
    focusFieldSearch,
    handlePageJump,
    handleSetCreateTool,
    handleRedo,
    handleUndo,
    nudgeSelectedField,
    pageCount,
    pdfDoc,
    transformMode,
  ]);

  // ── Computed values ────────────────────────────────────────────────
  const { demoActive, demoStepIndex, demoCompletionOpen, demoSearchPreset } = demo;
  const { isProcessing, processingMode, processingHeading, processingDetail } = detection;
  const { verifiedUser, userEmail, requiresEmailVerification, authReady, showLogin, showProfile, profileLimits, authUser, profileLoading, userProfile } = auth;
  const { bannerNotice, dialogRequest } = dialog;
  const {
    openAiError,
    renameInProgress,
    hasRenamedFields,
    mappingInProgress,
    mapSchemaInProgress,
    hasMappedSchema,
    checkboxRules,
    radioGroupSuggestions,
    textTransformRules,
    canRename,
    canMapSchema,
    canRenameAndMap,
    renameDisabledReason,
    mapSchemaDisabledReason,
    renameAndMapDisabledReason,
  } = openAi;
  const { schemaError, dataSourceKind, dataSourceLabel, schemaUploadInProgress, dataColumns, dataRows, identifierKey } = dataSource;
  const { savedForms: savedFormsList, savedFormsLoading, deletingFormId, showSavedFormsLimitDialog } = savedForms;
  const { fields } = fieldHistory;
  const radioGroups = useMemo(() => buildRadioGroups(fields), [fields]);
  const { showFields, showFieldNames, showFieldInfo, confidenceFilter, selectedFieldId, visibleFields, hasFieldValues } = fieldState;
  const {
    billingCheckoutInProgressKind,
    billingCancelInProgress,
    showDowngradeRetentionDialog,
    downgradeRetentionSaveInProgress,
    currentDowngradeRetention,
    downgradeRetentionReactivateLabel,
    closeDowngradeRetentionDialog,
    handleOpenDowngradeRetentionDialog,
    handleStartBillingCheckout,
    handleCancelBillingSubscription,
    handleSaveDowngradeRetentionSelection,
    handleReactivateDowngradedAccount,
  } = useDowngradeRetentionRuntime({
    authReady,
    assumeAuthReady,
    verifiedUser,
    userProfile,
    loadUserProfile: auth.loadUserProfile,
    mutateUserProfile: auth.mutateUserProfile,
    setBannerNotice: dialog.setBannerNotice,
    refreshSavedForms: savedForms.refreshSavedForms,
    refreshGroups: groups.refreshGroups,
  });
  const selectedField = useMemo(
    () => fields.find((field) => field.id === selectedFieldId) || null,
    [fields, selectedFieldId],
  );
  const isDemoAsset = Boolean(sourceFileIsDemo && sourceFileName && DEMO_ASSET_NAME_SET.has(sourceFileName));
  const allowAnonymousDemoEditor = demoActive || isDemoAsset;
  const pendingQuickRadioFields = useMemo(() => {
    return resolvePendingQuickRadioFields(pendingQuickRadioSelection, fields);
  }, [fields, pendingQuickRadioSelection]);
  const activeRadioToolDraft = activeCreateTool === 'radio'
    ? manualRadioToolDraft
    : activeCreateTool === 'quick-radio'
      ? quickRadioToolDraft
      : null;
  const radioSuggestionFieldFingerprint = useMemo(
    () => JSON.stringify(fields.map((field) => ({
      id: field.id,
      name: field.name,
      type: field.type,
      page: field.page,
      x: field.rect.x,
      y: field.rect.y,
      width: field.rect.width,
      height: field.rect.height,
      radioGroupId: field.radioGroupId ?? null,
      radioGroupKey: field.radioGroupKey ?? null,
      radioOptionKey: field.radioOptionKey ?? null,
    }))),
    [fields],
  );
  const visibleRadioGroupSuggestions = useMemo(() => {
    const dismissed = new Set(dismissedRadioSuggestionIds);
    return radioGroupSuggestions.filter((suggestion) => (
      !dismissed.has(suggestion.id) &&
      !isRadioGroupSuggestionApplied(fields, suggestion)
    ));
  }, [dismissedRadioSuggestionIds, fields, radioGroupSuggestions]);
  const radioSuggestionByFieldId = useMemo(
    () => buildRadioSuggestionFieldMap(fields, visibleRadioGroupSuggestions),
    [fields, visibleRadioGroupSuggestions],
  );
  const selectedRadioSuggestion = selectedFieldId
    ? radioSuggestionByFieldId.get(selectedFieldId) ?? null
    : null;

  useEffect(() => {
    const autoApplicableSuggestions = visibleRadioGroupSuggestions.filter(
      (suggestion) => shouldAutoApplyRadioGroupSuggestion(suggestion),
    );
    if (!autoApplicableSuggestions.length) {
      return;
    }
    const result = applyRadioGroupSuggestions(fieldHistory.fieldsRef.current, autoApplicableSuggestions);
    if (result.fields === fieldHistory.fieldsRef.current || !result.appliedSuggestionIds.length) {
      return;
    }
    fieldHistory.beginFieldHistory();
    fieldHistory.updateFields(result.fields, { trackHistory: false });
    fieldHistory.commitFieldHistory();
  }, [
    fieldHistory.beginFieldHistory,
    fieldHistory.commitFieldHistory,
    fieldHistory.fieldsRef,
    fieldHistory.updateFields,
    visibleRadioGroupSuggestions,
  ]);

  useEffect(() => {
    if (activeCreateTool !== 'radio') {
      setManualRadioToolDraft(null);
      return;
    }
    setManualRadioToolDraft((prev) => prev ?? buildNextRadioToolDraft(fieldHistory.fieldsRef.current));
  }, [activeCreateTool, fieldHistory.fieldsRef]);

  useEffect(() => {
    if (activeCreateTool !== 'quick-radio') {
      setQuickRadioToolDraft(null);
      return;
    }
    setQuickRadioToolDraft((prev) => prev ?? buildNextRadioToolDraft(fieldHistory.fieldsRef.current));
  }, [activeCreateTool, fieldHistory.fieldsRef]);

  useEffect(() => {
    if (activeCreateTool === 'quick-radio') {
      return;
    }
    setPendingQuickRadioSelection(null);
  }, [activeCreateTool]);

  useEffect(() => {
    setPendingQuickRadioSelection((prev) => prunePendingQuickRadioSelection(prev, fields, currentPage));
  }, [currentPage, fields]);

  useEffect(() => {
    if (!manualRadioToolDraft) {
      return;
    }
    const matchingGroup = radioGroups.find((group) => group.id === manualRadioToolDraft.groupId);
    if (!matchingGroup) {
      return;
    }
    if (
      matchingGroup.key === manualRadioToolDraft.groupKey &&
      matchingGroup.label === manualRadioToolDraft.groupLabel
    ) {
      return;
    }
    setManualRadioToolDraft((prev) => (
      prev && prev.groupId === matchingGroup.id
        ? {
            ...prev,
            groupKey: matchingGroup.key,
            groupLabel: matchingGroup.label,
          }
        : prev
    ));
  }, [manualRadioToolDraft, radioGroups]);

  const dismissedRadioSuggestionFingerprintRef = useRef<string | null>(null);

  useEffect(() => {
    if (dismissedRadioSuggestionFingerprintRef.current === null) {
      dismissedRadioSuggestionFingerprintRef.current = radioSuggestionFieldFingerprint;
      return;
    }
    if (dismissedRadioSuggestionFingerprintRef.current !== radioSuggestionFieldFingerprint) {
      dismissedRadioSuggestionFingerprintRef.current = radioSuggestionFieldFingerprint;
      setDismissedRadioSuggestionIds([]);
    }
  }, [radioSuggestionFieldFingerprint]);
  const displayPreset = useMemo<FieldListDisplayPreset>(() => {
    if (showFields && showFieldNames && !showFieldInfo && !transformMode) return 'review';
    if (showFields && !showFieldNames && !showFieldInfo && transformMode) return 'edit';
    if (showFields && !showFieldNames && showFieldInfo && !transformMode) return 'fill';
    return 'custom';
  }, [showFieldInfo, showFieldNames, showFields, transformMode]);

  const bootstrapAuthSyncedRef = useRef(false);

  useEffect(() => {
    if (!bootstrapAuthUser) return;
    if (bootstrapAuthSyncedRef.current) return;
    bootstrapAuthSyncedRef.current = true;
    void auth.syncAuthSession(bootstrapAuthUser, { forceTokenRefresh: true, deferSavedForms: true });
  }, [auth, bootstrapAuthUser]);

  const shouldLockWorkspaceScroll = !showHomepage && !showLogin && !showProfile && !requiresEmailVerification;

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const root = document.getElementById('root');
    document.documentElement.classList.toggle('workspace-no-scroll', shouldLockWorkspaceScroll);
    document.body.classList.toggle('workspace-no-scroll', shouldLockWorkspaceScroll);
    root?.classList.toggle('workspace-no-scroll', shouldLockWorkspaceScroll);
    return () => {
      document.documentElement.classList.remove('workspace-no-scroll');
      document.body.classList.remove('workspace-no-scroll');
      root?.classList.remove('workspace-no-scroll');
    };
  }, [shouldLockWorkspaceScroll]);

  const handledLaunchIntentRef = useRef<WorkspaceLaunchIntent>(null);
  useEffect(() => {
    if (!launchIntent || handledLaunchIntentRef.current === launchIntent) return;
    if (launchIntent === 'workflow') {
      setShowHomepage(false);
    } else if (launchIntent === 'demo') {
      setShowHomepage(false);
      demo.startDemo();
    } else if (launchIntent === 'signin') {
      auth.setShowLogin(true);
    } else if (launchIntent === 'profile') {
      if (verifiedUser || bootstrapHasVerifiedUser) {
        auth.setShowProfile(true);
      } else {
        auth.setShowLogin(true);
      }
    }
    handledLaunchIntentRef.current = launchIntent;
  }, [
    auth.setShowLogin,
    auth.setShowProfile,
    bootstrapHasVerifiedUser,
    demo.startDemo,
    launchIntent,
    verifiedUser,
  ]);

  // Check for pending onboarding after email verification completes.
  const onboardingCheckedRef = useRef(false);
  useEffect(() => {
    if (!verifiedUser?.uid || onboardingCheckedRef.current || showOnboarding) return;
    onboardingCheckedRef.current = true;
    if (consumeOnboardingPending(verifiedUser.uid)) {
      setShowOnboarding(true);
    }
  }, [verifiedUser, showOnboarding]);

  useEffect(() => {
    if (!showLogin || !verifiedUser) {
      return;
    }
    // Email verification and other external auth completions can resolve after
    // the runtime already opened its login shell. Close that shell once the
    // verified session exists so onboarding or the requested workspace can show.
    auth.setShowLogin(false);
  }, [auth.setShowLogin, showLogin, verifiedUser]);

  const hadVerifiedWorkspaceRef = useRef(Boolean(bootstrapHasVerifiedUser));
  const handledSignedOutRedirectRef = useRef(false);
  useEffect(() => {
    if (verifiedUser) {
      hadVerifiedWorkspaceRef.current = true;
      handledSignedOutRedirectRef.current = false;
      return;
    }
    if (!hadVerifiedWorkspaceRef.current || handledSignedOutRedirectRef.current) {
      return;
    }
    if (!authReady) {
      return;
    }
    if (showLogin || showOnboarding || requiresEmailVerification || allowAnonymousDemoEditor) {
      return;
    }

    const hasProtectedWorkspaceState = (
      browserRoute.kind !== 'homepage' ||
      !showHomepage ||
      showProfile ||
      Boolean(pdfDoc || detection.isProcessing || savedForms.activeSavedFormId || activeGroupId)
    );
    if (!hasProtectedWorkspaceState) {
      return;
    }

    // Firebase can report sign-out before the parent shell finishes swapping
    // routes. Force the runtime back to the homepage once per auth loss so the
    // user never gets stranded on a blank/loading screen.
    handledSignedOutRedirectRef.current = true;
    returnRuntimeToHomepage({
      clearSavedForms: true,
      clearLogin: true,
      clearOnboarding: true,
      clearProfile: true,
    });
  }, [
    activeGroupId,
    authReady,
    allowAnonymousDemoEditor,
    bootstrapHasVerifiedUser,
    browserRoute.kind,
    detection.isProcessing,
    onBrowserRouteChange,
    pdfDoc,
    requiresEmailVerification,
    returnRuntimeToHomepage,
    savedForms.activeSavedFormId,
    showHomepage,
    showLogin,
    showOnboarding,
    showProfile,
    verifiedUser,
  ]);

  useEffect(() => {
    if (!verifiedUser?.uid || launchIntent === 'demo') {
      return;
    }
    if (pendingBrowserRouteKey !== null) {
      return;
    }
    const canPersistUiWorkspaceRoute =
      activeWorkspaceBrowserRoute.kind === 'ui-root'
      && Boolean(detection.detectSessionId || detection.mappingSessionId);
    if (
      activeWorkspaceBrowserRoute.kind !== 'saved-form'
      && activeWorkspaceBrowserRoute.kind !== 'group'
      && !canPersistUiWorkspaceRoute
    ) {
      clearWorkspaceResumeState();
      return;
    }
    writeWorkspaceResumeState({
      version: 1,
      userId: verifiedUser.uid,
      route: activeWorkspaceBrowserRoute,
      currentPage,
      scale,
      detectSessionId: detection.detectSessionId,
      mappingSessionId: detection.mappingSessionId,
      fieldCount: fieldHistory.fields.length,
      pageCount,
      updatedAtMs: Date.now(),
    });
  }, [
    activeWorkspaceBrowserRoute,
    currentPage,
    detection.detectSessionId,
    detection.mappingSessionId,
    fieldHistory.fields.length,
    launchIntent,
    pageCount,
    pendingBrowserRouteKey,
    scale,
    verifiedUser?.uid,
  ]);

  useEffect(() => {
    if (!onBrowserRouteChange || pendingBrowserRouteKey !== null || launchIntent === 'demo') {
      return;
    }
    if (areWorkspaceBrowserRoutesEqual(browserRoute, activeWorkspaceBrowserRoute)) {
      return;
    }
    onBrowserRouteChange(activeWorkspaceBrowserRoute);
  }, [
    activeWorkspaceBrowserRoute,
    browserRoute,
    launchIntent,
    onBrowserRouteChange,
    pendingBrowserRouteKey,
  ]);

  useEffect(() => {
    if (browserRoute.kind === 'homepage' || pendingBrowserRouteKey !== browserRouteKey) {
      return;
    }
    let cancelled = false;
    const finishRouteRestore = () => {
      if (cancelled) return;
      if (routeRestoreInFlightKeyRef.current === browserRouteKey) {
        routeRestoreInFlightKeyRef.current = null;
      }
      setPendingBrowserRouteKey((current) => (current === browserRouteKey ? null : current));
    };
    const failRouteRestore = (message?: string) => {
      if (cancelled) return;
      if (routeRestoreInFlightKeyRef.current === browserRouteKey) {
        routeRestoreInFlightKeyRef.current = null;
      }
      if (message) {
        dialog.setBannerNotice({
          tone: 'error',
          message,
          autoDismissMs: 8000,
        });
      }
      clearWorkspaceResumeState();
      const fallbackRoute: WorkspaceBrowserRoute = { kind: 'upload-root' };
      setPendingBrowserRouteKey(getWorkspaceBrowserRouteKey(fallbackRoute));
      onBrowserRouteChange?.(fallbackRoute, { replace: true });
    };
    const restoreRequestedRoute = async () => {
      if (browserRoute.kind === 'profile') {
        if (!auth.showProfile && !auth.showLogin) {
          setShowHomepage(false);
          if (verifiedUser || bootstrapHasVerifiedUser) {
            auth.setShowProfile(true);
          } else {
            auth.setShowLogin(true);
          }
          return;
        }
        finishRouteRestore();
        return;
      }

      if (browserRoute.kind === 'upload-root') {
        if (auth.showProfile) {
          auth.setShowProfile(false);
          return;
        }
        if (showHomepage) {
          setShowHomepage(false);
          return;
        }
        finishRouteRestore();
        return;
      }

      if (browserRoute.kind === 'ui-root') {
        if (auth.showProfile) {
          auth.setShowProfile(false);
          return;
        }
        if (showHomepage) {
          setShowHomepage(false);
          return;
        }
        if (!verifiedUser && !bootstrapHasVerifiedUser) {
          auth.setShowLogin(true);
          return;
        }
        if (!verifiedUser) {
          return;
        }
        if (pdfDoc || detection.isProcessing) {
          finishRouteRestore();
          return;
        }
        const resumeState = findMatchingWorkspaceResumeState(browserRoute, verifiedUser.uid);
        if (!resumeState) {
          finishRouteRestore();
          return;
        }
        if (routeRestoreInFlightKeyRef.current === browserRouteKey) {
          return;
        }
        routeRestoreInFlightKeyRef.current = browserRouteKey;
        const restored = await restoreUiWorkspaceFromResume(resumeState);
        if (!restored) {
          failRouteRestore('Failed to reopen the active workspace.');
          return;
        }
        finishRouteRestore();
        return;
      }

      if (!verifiedUser) {
        return;
      }

      if (isMobileView) {
        clearWorkspaceResumeState();
        onBrowserRouteChange?.({ kind: 'homepage' }, { replace: true });
        setPendingBrowserRouteKey(null);
        return;
      }

      const resumeState = findMatchingWorkspaceResumeState(browserRoute, verifiedUser.uid);
      if (browserRoute.kind === 'saved-form') {
        if (routeRestoreInFlightKeyRef.current === browserRouteKey) {
          return;
        }
        if (activeGroupId || savedForms.activeSavedFormId !== browserRoute.formId) {
          routeRestoreInFlightKeyRef.current = browserRouteKey;
          const opened = await handleSelectSavedForm(browserRoute.formId, {
            preferredSession: resolvePreferredSessionResume(resumeState),
          });
          if (!opened) {
            failRouteRestore('Failed to reopen the saved form.');
            return;
          }
          restoreViewportFromResume(resumeState);
          finishRouteRestore();
          return;
        }
        restoreViewportFromResume(resumeState);
        void tryReuseResumedSession(resumeState);
        finishRouteRestore();
        return;
      }

      if (
        activeGroupId !== browserRoute.groupId ||
        (browserRoute.templateId && savedForms.activeSavedFormId !== browserRoute.templateId)
      ) {
        if (routeRestoreInFlightKeyRef.current === browserRouteKey) {
          return;
        }
        routeRestoreInFlightKeyRef.current = browserRouteKey;
        const opened = await handleOpenGroup(browserRoute.groupId, {
          preferredTemplateId: browserRoute.templateId,
          preferredSession: resolvePreferredSessionResume(resumeState),
        });
        if (!opened) {
          failRouteRestore('Failed to reopen the saved group.');
          return;
        }
        restoreViewportFromResume(resumeState);
        finishRouteRestore();
        return;
      }

      restoreViewportFromResume(resumeState);
      void tryReuseResumedSession(resumeState);
      finishRouteRestore();
    };

    void restoreRequestedRoute();
    return () => {
      cancelled = true;
    };
  }, [
    activeGroupId,
    auth,
    bootstrapHasVerifiedUser,
    browserRoute,
    browserRouteKey,
    detection.isProcessing,
    dialog,
    handleOpenGroup,
    handleSelectSavedForm,
    isMobileView,
    onBrowserRouteChange,
    pendingBrowserRouteKey,
    resolvePreferredSessionResume,
    restoreViewportFromResume,
    restoreUiWorkspaceFromResume,
    savedForms.activeSavedFormId,
    showHomepage,
    pdfDoc,
    tryReuseResumedSession,
    verifiedUser,
  ]);

  const hasDocument = !!pdfDoc;
  const canSaveToProfile = Boolean(pdfDoc && verifiedUser);
  const canDownload = Boolean(pdfDoc && (verifiedUser || sourceFileIsDemo));

  const demoUiLocked = demoCompletionOpen || (!demoActive && isDemoAsset);

  const activeErrorMessage = openAiError ?? schemaError;
  const bannerAlert: BannerNotice | null = activeErrorMessage
    ? { tone: 'error', message: activeErrorMessage }
    : bannerNotice;
  const shouldShowBannerAlert = Boolean(bannerAlert) && !(demoActive && !isMobileView);

  const handleDemoLockedAction = useCallback(() => {
    if (typeof window === 'undefined') return;
    window.alert(DEMO_DISABLED_MESSAGE);
  }, []);

  const currentView = showHomepage ? 'homepage' : isProcessing ? 'processing' : hasDocument ? 'editor' : 'upload';
  const workspaceRouteLoading = (
    pendingBrowserRouteKey !== null &&
    !isProcessing &&
    browserRoute.kind !== 'saved-form' &&
    browserRoute.kind !== 'group'
  );
  const activeDemoStep = demoStepIndex !== null ? DEMO_STEPS[demoStepIndex] : null;
  const showDemoTour = demoActive && currentView === 'editor' && activeDemoStep?.id !== 'search-fill';
  const shouldShowProcessingAd = processingMode === 'detect' && Boolean(PROCESSING_AD_VIDEO_URL);
  const handleOpenSearchFill = useCallback(() => {
    setSearchFillPreset(null);
    setShowSearchFill(true);
  }, []);

  const handleCloseSearchFill = useCallback(() => {
    setShowSearchFill(false);
    setSearchFillPreset(null);
  }, []);

  const handleCancelLogin = useCallback(() => {
    auth.setShowLogin(false);
    if (!verifiedUser) {
      onBrowserRouteChange?.({ kind: 'homepage' }, { replace: true });
    }
  }, [auth, onBrowserRouteChange, verifiedUser]);

  const runtimeLoadingFallback = (
    <div className="auth-loading-screen">
      <div className="auth-loading-card">Loading workspace…</div>
    </div>
  );

  useEffect(() => {
    if (currentView === 'editor') return;
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  }, [currentView]);

  // ── Dialog renderers ───────────────────────────────────────────────
  const dialogContent = (() => {
    if (!dialogRequest) return null;
    if (dialogRequest.kind === 'confirm') {
      return (<ConfirmDialog open title={dialogRequest.title} description={dialogRequest.message}
        confirmLabel={dialogRequest.confirmLabel} cancelLabel={dialogRequest.cancelLabel}
        tone={dialogRequest.tone} onConfirm={() => dialog.resolveDialog(true)} onCancel={() => dialog.resolveDialog(false)} />);
    }
    if (dialogRequest.kind === 'prompt') {
      return (<PromptDialog open title={dialogRequest.title} description={dialogRequest.message}
        confirmLabel={dialogRequest.confirmLabel} cancelLabel={dialogRequest.cancelLabel}
        tone={dialogRequest.tone} defaultValue={dialogRequest.defaultValue}
        placeholder={dialogRequest.placeholder} requireValue={dialogRequest.requireValue}
        onSubmit={(value) => dialog.resolveDialog(value)} onCancel={() => dialog.resolveDialog(null)} />);
    }
    return null;
  })();

  const savedFormsLimitDialog = (
    <SavedFormsLimitDialog open={showSavedFormsLimitDialog}
      maxSavedForms={profileLimits.savedFormsMax} savedForms={savedFormsList}
      deletingFormId={deletingFormId} onDelete={handleSavedFormsLimitDelete}
      onClose={savedForms.closeSavedFormsLimitDialog} />
  );
  const fillLinkManagerDialog = (
    <Suspense fallback={null}>
      <LazyFillLinkManagerDialog {...fillLinkManagerDialogProps} />
    </Suspense>
  );
  const templateApiManagerDialog = (
    <Suspense fallback={null}>
      <LazyApiFillManagerDialog {...templateApiManagerDialogProps} />
    </Suspense>
  );
  const signatureRequestDialog = (
    <Suspense fallback={null}>
      <LazySignatureRequestDialog {...signing.dialogProps} />
    </Suspense>
  );
  const downgradeRetentionDialog = (
    <Suspense fallback={null}>
      <LazyDowngradeRetentionDialog
        open={showDowngradeRetentionDialog}
        retention={currentDowngradeRetention}
        billingEnabled={userProfile?.billing?.enabled === true}
        savingSelection={downgradeRetentionSaveInProgress}
        checkoutInProgress={billingCheckoutInProgressKind !== null}
        reactivateLabel={downgradeRetentionReactivateLabel}
        onClose={closeDowngradeRetentionDialog}
        onSaveSelection={handleSaveDowngradeRetentionSelection}
        onReactivatePremium={handleReactivateDowngradedAccount}
      />
    </Suspense>
  );
  const groupUploadDialog = (
    <Suspense fallback={null}>
      <LazyGroupUploadDialog
        open={groupUpload.open}
        groupName={groupUpload.groupName}
        onGroupNameChange={groupUpload.setGroupName}
        items={groupUpload.items}
        wantsRename={groupUpload.wantsRename}
        onWantsRenameChange={groupUpload.setWantsRename}
        wantsMap={groupUpload.wantsMap}
        onWantsMapChange={groupUpload.setWantsMap}
        processing={groupUpload.processing}
        localError={groupUpload.localError}
        progressLabel={groupUpload.progressLabel}
        pageSummary={groupUpload.pageSummary}
        creditEstimate={groupUpload.creditEstimate}
        creditsRemaining={groupUpload.creditsRemaining}
        schemaUploadInProgress={dataSource.schemaUploadInProgress}
        dataSourceLabel={dataSourceLabel}
        onChooseDataSource={dataSource.handleChooseDataSource}
        onClose={groupUpload.closeDialog}
        onAddFiles={groupUpload.addFiles}
        onRemoveFile={groupUpload.removeFile}
        onConfirm={groupUpload.confirm}
      />
    </Suspense>
  );
  const demoCompletionDialog = (
    <ConfirmDialog open={demoCompletionOpen} title="Demo complete"
      description="Replay the walkthrough or keep exploring the editor with the mapped PDF."
      confirmLabel="Replay demo" cancelLabel="Continue in editor"
      onConfirm={demo.handleDemoReplay} onCancel={demo.handleDemoContinue} />
  );
  const dataSourceInputs = (
    <>
      <input ref={dataSource.csvInputRef} id="csv-file-input" name="csv-file" type="file" accept=".csv,text/csv" aria-label="Upload CSV schema file" style={{ display: 'none' }} onChange={dataSource.handleCsvFileSelected} />
      <input ref={dataSource.excelInputRef} id="excel-file-input" name="excel-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" aria-label="Upload Excel schema file" style={{ display: 'none' }} onChange={dataSource.handleExcelFileSelected} />
      <input ref={dataSource.jsonInputRef} id="json-file-input" name="json-file" type="file" accept=".json,application/json" aria-label="Upload JSON schema file" style={{ display: 'none' }} onChange={dataSource.handleJsonFileSelected} />
      <input ref={dataSource.sqlInputRef} id="sql-file-input" name="sql-file" type="file" accept=".sql,text/x-sql,application/sql" aria-label="Upload SQL schema file" style={{ display: 'none' }} onChange={dataSource.handleSqlFileSelected} />
      <input ref={dataSource.txtInputRef} id="txt-file-input" name="txt-file" type="file" accept=".txt,text/plain" aria-label="Upload TXT schema file" style={{ display: 'none' }} onChange={dataSource.handleTxtFileSelected} />
    </>
  );
  const uploadBrowserViewModel = useUploadBrowserViewModel({
    loadError,
    onSetLoadError: setLoadError,
    verifiedUser: !!verifiedUser,
    schemaUploadInProgress,
    dataSourceLabel,
    onChooseDataSource: dataSource.handleChooseDataSource,
    pipeline: {
      showPipelineModal: pipeline.showPipelineModal,
      pendingDetectFile: pipeline.pendingDetectFile,
      pendingDetectPageCount: pipeline.pendingDetectPageCount,
      pendingDetectPageCountLoading: pipeline.pendingDetectPageCountLoading,
      pendingDetectCreditEstimate: pipeline.pendingDetectCreditEstimate,
      pendingDetectWithinPageLimit: pipeline.pendingDetectWithinPageLimit,
      pendingDetectCreditsRemaining: pipeline.pendingDetectCreditsRemaining,
      uploadWantsRename: pipeline.uploadWantsRename,
      uploadWantsMap: pipeline.uploadWantsMap,
      pipelineError: pipeline.pipelineError,
      onSetUploadWantsRename: pipeline.setUploadWantsRename,
      onSetUploadWantsMap: pipeline.setUploadWantsMap,
      onSetPipelineError: pipeline.setPipelineError,
      onPipelineCancel: pipeline.cancel,
      onPipelineConfirm: pipeline.confirm,
      onDetectUpload: pipeline.openModal,
    },
    savedForms: {
      savedForms: savedFormsList,
      savedFormsLoading,
      deletingFormId,
    },
    groups: {
      groups: groups.groups,
      groupsLoading: groups.groupsLoading,
      groupsCreating: groups.groupsCreating,
      updatingGroupId: groups.updatingGroupId,
      selectedGroupFilterId: groups.selectedGroupFilterId,
      selectedGroupFilterLabel: groups.selectedGroupFilterLabel,
      deletingGroupId: groups.deletingGroupId,
      setSelectedGroupFilterId: groups.setSelectedGroupFilterId,
    },
    handlers: {
      onFillableUpload: handleFillableUpload,
      onOpenGroupUpload: groupUpload.openDialog,
      onSelectSavedForm: handleSelectSavedForm,
      onDeleteSavedForm: handleDeleteSavedForm,
      onOpenGroup: handleOpenGroup,
      onCreateGroup: handleCreateGroup,
      onUpdateGroup: handleUpdateGroup,
      onDeleteGroup: handleDeleteGroup,
    },
    groupUploadDialog,
  });

  // ── Render ─────────────────────────────────────────────────────────
  if (!authReady && !assumeAuthReady) {
    return (<div className="auth-loading-screen"><div className="auth-loading-card">Loading workspace…</div></div>);
  }
  if (workspaceRouteLoading) {
    return (<div className="auth-loading-screen"><div className="auth-loading-card">Loading workspace…</div></div>);
  }
  if (requiresEmailVerification) {
    return (
      <Suspense fallback={runtimeLoadingFallback}>
        <LazyVerifyEmailPage
          email={authUser?.email ?? null}
          onRefresh={auth.handleRefreshVerification}
          onSignOut={handleSignOut}
        />
      </Suspense>
    );
  }
  if (showLogin) {
    return (
      <Suspense fallback={runtimeLoadingFallback}>
        <LazyLoginPage
          onAuthenticated={(options) => {
            auth.setShowLogin(false);
            if (options?.isNewUser) {
              setShowOnboarding(true);
            }
          }}
          onCancel={handleCancelLogin}
        />
      </Suspense>
    );
  }
  if (showOnboarding) {
    return (
      <Suspense fallback={runtimeLoadingFallback}>
        <LazyOnboardingPage
          onStartTrial={() => {
            clearOnboardingPending();
            setShowOnboarding(false);
            handleStartBillingCheckout('free_trial');
          }}
          onSkipToFree={() => {
            clearOnboardingPending();
            setShowOnboarding(false);
          }}
          checkoutInProgress={billingCheckoutInProgressKind === 'free_trial'}
        />
      </Suspense>
    );
  }
  if (showProfile && verifiedUser) {
    return (
      <>
        {shouldShowBannerAlert && bannerAlert ? <Alert tone={bannerAlert.tone} variant="banner" message={bannerAlert.message} onDismiss={handleDismissBanner} /> : null}
        {savedFormsLimitDialog}{fillLinkManagerDialog}{templateApiManagerDialog}{signatureRequestDialog}{downgradeRetentionDialog}{dialogContent}
        <Suspense fallback={runtimeLoadingFallback}>
          <LazyProfilePage email={userProfile?.email ?? verifiedUser.email} role={userProfile?.role ?? 'base'}
            creditsRemaining={userProfile?.creditsRemaining ?? 0}
            monthlyCreditsRemaining={userProfile?.monthlyCreditsRemaining ?? 0}
            refillCreditsRemaining={userProfile?.refillCreditsRemaining ?? 0}
            availableCredits={userProfile?.availableCredits ?? userProfile?.creditsRemaining ?? 0}
            refillCreditsLocked={Boolean(userProfile?.refillCreditsLocked)}
            billingEnabled={typeof userProfile?.billing?.enabled === 'boolean' ? userProfile.billing.enabled : null}
            billingHasSubscription={userProfile?.billing?.hasSubscription === true}
            billingSubscriptionStatus={userProfile?.billing?.subscriptionStatus ?? null}
            billingCancelAtPeriodEnd={userProfile?.billing?.cancelAtPeriodEnd ?? null}
            billingCancelAt={userProfile?.billing?.cancelAt ?? null}
            billingCurrentPeriodEnd={userProfile?.billing?.currentPeriodEnd ?? null}
            billingTrialUsed={userProfile?.billing?.trialUsed ?? null}
            billingPlans={userProfile?.billing?.plans}
            retention={currentDowngradeRetention}
            profileError={auth.profileLoadError}
            creditPricing={userProfile?.creditPricing}
            isLoading={profileLoading}
            limits={profileLimits} savedForms={savedFormsList} savedFormsLoading={savedFormsLoading}
            allowSavedFormOpen={!isMobileView}
            onSelectSavedForm={handleSelectSavedFormFromProfile} onDeleteSavedForm={handleDeleteSavedForm}
            deletingFormId={deletingFormId}
            billingCheckoutInProgressKind={billingCheckoutInProgressKind}
            billingCancelInProgress={billingCancelInProgress}
            onStartBillingCheckout={userProfile?.billing?.enabled === true ? handleStartBillingCheckout : undefined}
            onCancelBillingSubscription={userProfile?.billing?.enabled === true ? handleCancelBillingSubscription : undefined}
            onOpenDowngradeRetention={currentDowngradeRetention ? handleOpenDowngradeRetentionDialog : undefined}
            onClose={auth.handleCloseProfile} onSignOut={handleSignOut} />
        </Suspense>
      </>
    );
  }

  // Safety net: if auth was lost while the runtime is still mounted (e.g.
  // sign-out race), force the homepage view instead of rendering an empty editor.
  // Demo sessions are the one supported anonymous editor mode.
  if (!verifiedUser && !showLogin && !showOnboarding && currentView === 'editor' && !allowAnonymousDemoEditor) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">Redirecting…</div>
      </div>
    );
  }

  if (currentView !== 'editor') {
    return (
      <Suspense fallback={runtimeLoadingFallback}>
        {/* Keep the legacy header and the active runtime screen in one suspense boundary
            so startup fallback replaces the whole shell instead of painting the header first. */}
        <div className="homepage-shell">
          {shouldShowBannerAlert && bannerAlert ? <Alert tone={bannerAlert.tone} variant="banner" message={bannerAlert.message} onDismiss={handleDismissBanner} /> : null}
          {savedFormsLimitDialog}{fillLinkManagerDialog}{templateApiManagerDialog}{signatureRequestDialog}{downgradeRetentionDialog}{demoCompletionDialog}{dialogContent}
          <LegacyHeader currentView={currentView} onNavigateHome={handleNavigateHome}
            showBackButton={!showHomepage} userEmail={userEmail ?? null}
            onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined}
            onSignOut={verifiedUser ? handleSignOut : undefined}
            onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined} />
          <main className="landing-main">
            {currentView === 'homepage' ? (
              <LazyHomepage
                onStartWorkflow={() => {
                  if (verifiedUser) {
                    setShowHomepage(false);
                    return;
                  }
                  auth.setShowLogin(true);
                }}
                onStartDemo={demo.startDemo}
                userEmail={userEmail ?? null} onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined}
                onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined} />
            ) : null}
            {currentView === 'upload' ? (
              <LazyUploadView {...uploadBrowserViewModel} />
            ) : null}
            {currentView === 'processing' ? (
              <LazyProcessingView heading={processingHeading} detail={processingDetail} showAd={shouldShowProcessingAd}
                adVideoUrl={PROCESSING_AD_VIDEO_URL} adPosterUrl={PROCESSING_AD_POSTER_URL} />
            ) : null}
          </main>
          {dataSourceInputs}
        </div>
      </Suspense>
    );
  }

  const appShellClassName = demoActive || demoCompletionOpen ? 'app app--demo-locked' : 'app';
  return (
    <div className={appShellClassName}>
      {shouldShowBannerAlert && bannerAlert ? <Alert tone={bannerAlert.tone} variant="banner" message={bannerAlert.message} onDismiss={handleDismissBanner} /> : null}
      {savedFormsLimitDialog}{fillLinkManagerDialog}{templateApiManagerDialog}{signatureRequestDialog}{downgradeRetentionDialog}{demoCompletionDialog}{dialogContent}
      <HeaderBar
        pageCount={pageCount} currentPage={currentPage} scale={scale} onScaleChange={setScale}
        onNavigateHome={handleNavigateHome} mappingInProgress={mappingInProgress}
        mapSchemaInProgress={mapSchemaInProgress} hasMappedSchema={hasMappedSchema}
        renameInProgress={renameInProgress} hasRenamedFields={hasRenamedFields}
        dataSourceKind={dataSourceKind} dataSourceLabel={dataSourceLabel}
        groupName={activeGroupName}
        groupTemplates={activeGroupTemplates.map((template) => ({ id: template.id, name: template.name }))}
        groupTemplateStatuses={headerGroupTemplateStatuses}
        activeGroupTemplateId={headerActiveGroupTemplateId}
        groupTemplateSwitchInProgress={Boolean(pendingGroupTemplateId || groupSwitchingTemplateId)}
        onSelectGroupTemplate={(formId) => { void handleSelectActiveGroupTemplate(formId); }}
        onChooseDataSource={dataSource.handleChooseDataSource} onClearDataSource={dataSource.handleClearDataSource}
        onRename={demoActive ? demo.handleDemoRename : handleRename}
        onRenameAndMap={demoActive ? demo.handleDemoRenameAndMap : handleRenameAndMap}
        onRenameAndMapGroup={demoActive ? undefined : (activeGroupId ? handleRenameAndMapGroup : undefined)}
        onMapSchema={demoActive ? demo.handleDemoMapSchema : handleMapSchema}
        canMapSchema={demoActive ? true : canMapSchema} canRename={demoActive ? true : canRename}
        canRenameAndMap={demoActive ? true : canRenameAndMap}
        canRenameAndMapGroup={demoActive ? true : !groupRenameMapDisabledReason}
        mapSchemaDisabledReason={demoActive ? null : mapSchemaDisabledReason}
        renameDisabledReason={demoActive ? null : renameDisabledReason}
        renameAndMapDisabledReason={demoActive ? null : renameAndMapDisabledReason}
        renameAndMapGroupDisabledReason={demoActive ? null : groupRenameMapDisabledReason}
        renameAndMapGroupInProgress={groupRenameMapInProgress}
        renameAndMapGroupButtonLabel={groupRenameMapLabel}
        onOpenSearchFill={handleOpenSearchFill}
        onOpenImageFill={!demoActive && detection.detectSessionId && fieldHistory.fields.length > 0 ? imageFill.openDialog : undefined}
        onDownload={saveDownload.handleDownload}
        onDownloadGroup={activeGroupId ? groupDownload.handleDownloadGroup : undefined}
        onSaveToProfile={saveDownload.handleSaveToProfile}
        downloadInProgress={saveDownload.downloadInProgress}
        downloadGroupInProgress={groupDownload.downloadGroupInProgress}
        saveInProgress={saveDownload.saveInProgress}
        canDownload={canDownload}
        canDownloadGroup={Boolean(
          activeGroupId &&
          activeGroupTemplates.length > 0 &&
          auth.verifiedUser &&
          !mappingInProgress &&
          !renameInProgress &&
          !mapSchemaInProgress &&
          !groupRenameMapInProgress,
        )}
        canSave={canSaveToProfile}
        userEmail={userEmail}
        onOpenFillLink={verifiedUser ? handleOpenFillLinkManager : undefined}
        canFillLink={canTriggerFillLink}
        onOpenTemplateApi={verifiedUser && !activeGroupId ? handleOpenTemplateApiManager : undefined}
        canOpenTemplateApi={canOpenTemplateApi}
        onOpenSignatureRequest={signing.canShowAction ? signing.openDialog : undefined}
        canSendForSignature={signing.canSendForSignature}
        onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined}
        onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
        demoLocked={demoUiLocked}
        onDemoLockedAction={handleDemoLockedAction}
        demoFillLinkDocsHref="/usage-docs/fill-by-link"
        demoCreateGroupDocsHref="/usage-docs/create-group"
        demoFillFromImagesDocsHref="/usage-docs/fill-from-images"
        demoSignatureDocsHref="/usage-docs/signature-workflow"
        onBlockedAction={(message) => dialog.setBannerNotice({ tone: 'error', message })}
      />
      <div className="app-shell">
        <FieldListPanel fields={visibleFields} totalFieldCount={fields.length}
          selectedFieldId={selectedFieldId} selectedField={selectedField}
          currentPage={currentPage} pageCount={pageCount} showFields={showFields}
          onBlockedAction={(message) => dialog.setBannerNotice({ tone: 'error', message })}
          showFieldNames={showFieldNames} showFieldInfo={showFieldInfo}
          transformMode={transformMode}
          displayPreset={displayPreset} onApplyDisplayPreset={handleApplyDisplayPreset}
          onShowFieldsChange={handleShowFieldsChange}
          onShowFieldNamesChange={fieldState.handleShowFieldNamesChange}
          onShowFieldInfoChange={handleShowFieldInfoChange}
          onTransformModeChange={handleSetTransformMode}
          canClearInputs={hasFieldValues} onClearInputs={fieldState.handleClearFieldValues}
          confidenceFilter={confidenceFilter} onConfidenceFilterChange={fieldState.handleConfidenceFilterChange}
          onResetConfidenceFilters={handleResetConfidenceFilters}
          onSelectField={handleSelectField} onPageChange={handlePageJump}
          renameInProgress={renameInProgress} />
        <main className="workspace">
          {loadError ? (
            <div className="viewer viewer--empty">
              <div className="viewer__placeholder viewer__placeholder--error">
                <h2>Unable to load PDF</h2><Alert tone="error" variant="inline" message={loadError} />
              </div>
            </div>
          ) : (
            <PdfViewer pdfDoc={pdfDoc} pageNumber={currentPage} scale={scale}
              pageSizes={pageSizes}
              fields={visibleFields} showFields={showFields} showFieldNames={showFieldNames}
              showFieldInfo={showFieldInfo}
              moveEnabled={transformMode && !showFieldInfo}
              resizeEnabled={transformMode && !showFieldInfo}
              createEnabled={Boolean(activeCreateTool) && !showFieldInfo}
              activeCreateTool={activeCreateTool}
              selectedFieldId={selectedFieldId}
              pendingQuickRadioFieldIds={pendingQuickRadioSelection?.fieldIds || []}
              radioSuggestionByFieldId={radioSuggestionByFieldId}
              onSelectField={handleSelectField} onUpdateField={fieldState.handleUpdateField}
              onUpdateFieldGeometry={fieldState.handleUpdateFieldGeometry}
              onCreateFieldWithRect={handleCreateFieldWithRect}
              onQuickRadioSelect={handleQuickRadioSelection}
              onSelectRadioField={handleSelectRadioFieldValue}
              onBeginFieldChange={fieldHistory.beginFieldHistory}
              onCommitFieldChange={fieldHistory.commitFieldHistory}
              onPageChange={handlePageScroll} pendingPageJump={pendingPageJump}
              onPageJumpComplete={handlePageJumpComplete} />
          )}
        </main>
        <FieldInspectorPanel fields={fields} selectedFieldId={selectedFieldId}
          selectedField={selectedField}
          radioGroups={radioGroups}
          selectedRadioSuggestion={selectedRadioSuggestion}
          activeCreateTool={activeCreateTool}
          radioToolDraft={activeRadioToolDraft}
          pendingQuickRadioFields={pendingQuickRadioFields}
          arrowKeyMoveEnabled={arrowKeyMoveEnabled}
          arrowKeyMoveStep={arrowKeyMoveStep}
          onUpdateField={fieldState.handleUpdateField}
          onSetFieldType={handleSetFieldType}
          onUpdateFieldDraft={fieldState.handleUpdateFieldDraft}
          onDeleteField={fieldState.handleDeleteField}
          onDeleteAllFields={fieldState.handleDeleteAllFields}
          onCreateToolChange={handleSetCreateTool}
          onUpdateRadioToolDraft={handleUpdateRadioToolDraft}
          onApplyPendingQuickRadioSelection={handleApplyPendingQuickRadioSelection}
          onCancelPendingQuickRadioSelection={handleCancelPendingQuickRadioSelection}
          onRemovePendingQuickRadioField={handleRemovePendingQuickRadioField}
          onRenameRadioGroup={handleRenameSelectedRadioGroup}
          onUpdateRadioFieldOption={handleUpdateSelectedRadioOption}
          onMoveRadioFieldToGroup={handleMoveSelectedRadioField}
          onReorderRadioField={handleReorderSelectedRadioField}
          onDissolveRadioGroup={handleDissolveSelectedRadioGroup}
          onApplyRadioSuggestion={handleApplyRadioSuggestion}
          onDismissRadioSuggestion={handleDismissRadioSuggestion}
          onArrowKeyMoveEnabledChange={setArrowKeyMoveEnabled}
          onArrowKeyMoveStepChange={(value) => setArrowKeyMoveStep(sanitizeArrowKeyMoveStep(value))}
          onUndo={handleUndo}
          onRedo={handleRedo}
          canUndo={fieldHistory.canUndo}
          canRedo={fieldHistory.canRedo}
          onBeginFieldChange={fieldHistory.beginFieldHistory}
          onCommitFieldChange={fieldHistory.commitFieldHistory}
          onBlockedAction={(message) => dialog.setBannerNotice({ tone: 'error', message })} />
      </div>
      {showSearchFill ? (
        <Suspense fallback={null}>
          <LazySearchFillModal open={showSearchFill} onClose={handleCloseSearchFill}
            sessionId={searchFillSessionId} dataSourceKind={dataSourceKind}
            dataSourceLabel={dataSourceLabel} columns={dataColumns}
            identifierKey={identifierKey} rows={dataRows} fields={fields}
            checkboxRules={checkboxRules}
            textTransformRules={textTransformRules}
            searchPreset={!demoActive ? searchFillPreset : null}
            fillTargets={activeGroupId ? activeGroupTemplates.map((template) => ({ id: template.id, name: template.name })) : []}
            activeFillTargetId={savedForms.activeSavedFormId}
            onFillTargets={activeGroupId ? handleFillSearchTargets : undefined}
            onFieldsChange={fieldState.handleFieldsChange} onClearFields={fieldState.handleClearFieldValues}
            onAfterFill={handleAfterSearchFill}
            onError={(message) => dataSource.setSchemaError(message)}
            onRequestDataSource={(kind) => dataSource.handleChooseDataSource(kind)}
            demoSearch={demoActive ? demoSearchPreset : null} />
        </Suspense>
      ) : null}
      {imageFill.open ? (
        <Suspense fallback={null}>
          <LazyImageFillDialog
            open={imageFill.open}
            onClose={imageFill.closeDialog}
            files={imageFill.files}
            extractedFields={imageFill.extractedFields}
            loading={imageFill.loading}
            error={imageFill.error}
            creditEstimate={imageFill.creditEstimate}
            onAddFiles={imageFill.addFiles}
            onRemoveFile={imageFill.removeFile}
            onRunExtraction={imageFill.runExtraction}
            onUpdateFieldValue={imageFill.updateFieldValue}
            onRejectField={imageFill.rejectField}
            onApplyFields={imageFill.applyFields}
          />
        </Suspense>
      ) : null}
      {dataSourceInputs}
      {showDemoTour ? (
        <Suspense fallback={null}>
          <LazyDemoTour open={showDemoTour} step={activeDemoStep} stepIndex={demoStepIndex ?? 0}
            stepCount={DEMO_STEPS.length} onNext={demo.handleDemoNext}
            onBack={demo.handleDemoBack} onClose={demo.exitDemo} />
        </Suspense>
      ) : null}
    </div>
  );
}

export default WorkspaceRuntime;
