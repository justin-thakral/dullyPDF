/**
 * Workspace runtime shell that orchestrates detection, mapping, and editor state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import './App.css';
import type {
  BannerNotice,
  FieldType,
  PageSize,
  PdfField,
} from './types';
import { debugLog } from './utils/debug';
import Homepage from './components/pages/Homepage';
import LoginPage from './components/pages/LoginPage';
import ProfilePage from './components/pages/ProfilePage';
import VerifyEmailPage from './components/pages/VerifyEmailPage';
import { HeaderBar } from './components/layout/HeaderBar';
import LegacyHeader from './components/layout/LegacyHeader';
import SearchFillModal from './components/features/SearchFillModal';
import UploadView from './components/features/UploadView';
import ProcessingView from './components/features/ProcessingView';
import { DemoTour } from './components/demo/DemoTour';
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
import { useDataSource } from './hooks/useDataSource';
import { useOpenAiPipeline } from './hooks/useOpenAiPipeline';
import { useDetection } from './hooks/useDetection';
import { usePipelineModal } from './hooks/usePipelineModal';
import { useSaveDownload } from './hooks/useSaveDownload';
import { useDemo } from './hooks/useDemo';
import { ApiService, type BillingCheckoutKind } from './services/api';
import { applyRouteSeo } from './utils/seo';
import { clampRectToPage } from './utils/coords';
import { createFieldWithRect, getMinFieldSize, normalizeRectForFieldType } from './utils/fields';

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
}: WorkspaceRuntimeProps) {
  // ── Ref bridges to break circular hook dependencies ────────────────
  const savedFormsBridge = useRef({
    clearSavedFormsRetry: () => {},
    clearSavedForms: () => {},
    refreshSavedForms: async (_opts?: { allowRetry?: boolean }) => {},
  });
  const openAiBridge = useRef({
    runOpenAiRename: async (_opts?: any) => null as PdfField[] | null,
    applySchemaMappings: async (_opts?: any) => false,
    handleMappingSuccess: () => {},
    setHasRenamedFields: (_v: boolean) => {},
    setHasMappedSchema: (_v: boolean) => {},
    setCheckboxRules: (_v: any[]) => {},
    setCheckboxHints: (_v: any[]) => {},
    setTextTransformRules: (_v: any[]) => {},
    setOpenAiError: (_v: string | null) => {},
  });
  const openAiSettersForDataSource = useRef({
    setMappingInProgress: (_v: boolean) => {},
    setOpenAiError: (_v: string | null) => {},
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

  // ── Saved forms (uses auth) ────────────────────────────────────────
  const savedForms = useSavedForms({
    authUserRef: auth.authUserRef,
    setBannerNotice: dialog.setBannerNotice,
    requestConfirm: dialog.requestConfirm,
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
  const [isMobileView, setIsMobileView] = useState(false);
  const [showSearchFill, setShowSearchFill] = useState(false);
  const [transformMode, setTransformMode] = useState(false);
  const [activeCreateTool, setActiveCreateTool] = useState<FieldType | null>(null);
  const [searchFillSessionId, setSearchFillSessionId] = useState(0);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceFileName, setSourceFileName] = useState<string | null>(null);
  const [sourceFileIsDemo, setSourceFileIsDemo] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [billingCheckoutInProgressKind, setBillingCheckoutInProgressKind] = useState<BillingCheckoutKind | null>(null);
  const [billingCancelInProgress, setBillingCancelInProgress] = useState(false);

  useEffect(() => {
    applyRouteSeo({ kind: 'app' });
  }, []);

  const pdfState = useMemo(() => ({
    setPdfDoc, setPageSizes, setPageCount, setCurrentPage, setScale, setPendingPageJump,
  }), []);

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
    setCheckboxHints: (v) => openAiBridge.current.setCheckboxHints(v),
    setTextTransformRules: (v) => openAiBridge.current.setTextTransformRules(v),
    setOpenAiError: (v) => openAiBridge.current.setOpenAiError(v),
    // Session keep-alive deps
    pdfDoc,
    sourceFileIsDemo,
    sourceFileName,
    demoStateRef: demoBridgeRef,
  });

  // ── OpenAI pipeline (uses detection state directly) ────────────────
  const openAi = useOpenAiPipeline({
    verifiedUser: auth.verifiedUser,
    fieldsRef: fieldHistory.fieldsRef,
    loadTokenRef: detection.loadTokenRef,
    detectSessionId: detection.detectSessionId,
    activeSavedFormId: savedForms.activeSavedFormId,
    dataColumns: dataSource.dataColumns,
    schemaId: dataSource.schemaId,
    pendingAutoActionsRef: detection.pendingAutoActionsRef,
    setBannerNotice: dialog.setBannerNotice,
    requestConfirm: dialog.requestConfirm,
    loadUserProfile: auth.loadUserProfile,
    resetFieldHistory: fieldHistory.resetFieldHistory,
    updateFieldsWith: fieldHistory.updateFieldsWith,
    setIdentifierKey: dataSource.setIdentifierKey,
    // For computed canRename/canMapSchema
    hasDocument: !!pdfDoc,
    fieldsCount: fieldHistory.fields.length,
    dataSourceKind: dataSource.dataSourceKind,
    hasSchemaOrPending: Boolean(dataSource.schemaId || dataSource.pendingSchemaPayload),
  });

  // Update bridges
  openAiBridge.current = {
    runOpenAiRename: openAi.runOpenAiRename,
    applySchemaMappings: openAi.applySchemaMappings,
    handleMappingSuccess: openAi.handleMappingSuccess,
    setHasRenamedFields: openAi.setHasRenamedFields,
    setHasMappedSchema: openAi.setHasMappedSchema,
    setCheckboxRules: openAi.setCheckboxRules,
    setCheckboxHints: openAi.setCheckboxHints,
    setTextTransformRules: openAi.setTextTransformRules,
    setOpenAiError: openAi.setOpenAiError,
  };
  openAiSettersForDataSource.current = {
    setMappingInProgress: openAi.setMappingInProgress,
    setOpenAiError: openAi.setOpenAiError,
  };

  // ── Wrapped detection handlers (bind pdfState) ─────────────────────
  const handleFillableUpload = useCallback(
    (file: File, options: { isDemo?: boolean; skipExistingFields?: boolean } = {}) =>
      detection.handleFillableUpload(file, options, pdfState),
    [detection.handleFillableUpload, pdfState],
  );

  const handleSelectSavedForm = useCallback(
    (formId: string) => detection.handleSelectSavedForm(formId, pdfState),
    [detection.handleSelectSavedForm, pdfState],
  );

  const handleSelectSavedFormFromProfile = useCallback(
    (formId: string) => {
      auth.setShowProfile(false);
      void handleSelectSavedForm(formId);
    },
    [auth, handleSelectSavedForm],
  );

  const runDetectUpload = useCallback(
    (file: File, options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null } = {}) =>
      detection.runDetectUpload(file, options, pdfState),
    [detection.runDetectUpload, pdfState],
  );

  // ── Pipeline modal (uses runDetectUpload, dataSource, auth) ────────
  const pipeline = usePipelineModal({
    verifiedUser: auth.verifiedUser,
    loadUserProfile: auth.loadUserProfile,
    schemaId: dataSource.schemaId,
    schemaUploadInProgress: dataSource.schemaUploadInProgress,
    pendingSchemaPayload: dataSource.pendingSchemaPayload,
    persistSchemaPayload: dataSource.persistSchemaPayload,
    setSchemaUploadInProgress: dataSource.setSchemaUploadInProgress,
    runDetectUpload,
  });

  // ── clearWorkspace ─────────────────────────────────────────────────
  const clearWorkspace = useCallback(() => {
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
    dialog.reset();
    pipeline.reset();
    // App-level UI state
    setShowSearchFill(false); setSearchFillSessionId((prev) => prev + 1);
    setTransformMode(false); setActiveCreateTool(null);
    setSourceFile(null); setSourceFileName(null); setSourceFileIsDemo(false);
  }, [fieldHistory, fieldState, detection, openAi, dataSource, savedForms, dialog, pipeline]);
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
  const handleSignOut = useCallback(async () => {
    await auth.handleSignOut();
    clearWorkspace();
    savedForms.clearSavedForms();
    setShowHomepage(true);
    auth.setShowProfile(false);
    demo.setDemoActive(false);
    demo.setDemoStepIndex(null);
    demo.setDemoCompletionOpen(false);
    demo.setDemoSearchPreset(null);
  }, [auth, clearWorkspace, demo, savedForms]);

  const handleNavigateHome = useCallback(() => {
    clearWorkspace();
    setLoadError(null);
    setShowHomepage(true);
    demo.setDemoActive(false);
    demo.setDemoStepIndex(null);
    demo.setDemoCompletionOpen(false);
    demo.setDemoSearchPreset(null);
  }, [clearWorkspace, demo]);

  const refreshProfileAfterBillingAction = useCallback(
    async (options?: { attempts?: number; retryDelayMs?: number }) => {
      const attempts = Math.max(1, options?.attempts ?? 3);
      const retryDelayMs = Math.max(0, options?.retryDelayMs ?? 1200);
      for (let attempt = 0; attempt < attempts; attempt += 1) {
        const profile = await auth.loadUserProfile();
        if (profile) return profile;
        if (attempt < attempts - 1 && retryDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
        }
      }
      return null;
    },
    [auth.loadUserProfile],
  );

  const handleStartBillingCheckout = useCallback(
    async (kind: BillingCheckoutKind) => {
      if (billingCancelInProgress) return;
      if (!auth.userProfile?.billing?.enabled) {
        dialog.setBannerNotice({
          tone: 'error',
          message: 'Stripe billing is currently unavailable.',
          autoDismissMs: 8000,
        });
        return;
      }
      setBillingCheckoutInProgressKind(kind);
      try {
        const payload = await ApiService.createBillingCheckoutSession(kind);
        const checkoutUrl = payload?.checkoutUrl;
        if (!checkoutUrl) {
          throw new Error('Stripe checkout URL is missing.');
        }
        window.location.assign(checkoutUrl);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to start checkout.';
        dialog.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
      } finally {
        setBillingCheckoutInProgressKind(null);
      }
    },
    [auth.userProfile?.billing?.enabled, billingCancelInProgress, dialog.setBannerNotice],
  );

  const handleCancelBillingSubscription = useCallback(async () => {
    if (billingCheckoutInProgressKind !== null) return;
    if (!auth.userProfile?.billing?.enabled) {
      dialog.setBannerNotice({
        tone: 'error',
        message: 'Stripe billing is currently unavailable.',
        autoDismissMs: 8000,
      });
      return;
    }
    if (!auth.userProfile?.billing?.hasSubscription) {
      dialog.setBannerNotice({
        tone: 'info',
        message: 'No active subscription is linked to this profile yet.',
        autoDismissMs: 7000,
      });
      return;
    }
    if (auth.userProfile?.billing?.cancelAtPeriodEnd === true) {
      dialog.setBannerNotice({
        tone: 'info',
        message: 'Subscription is already cancelled for period end.',
        autoDismissMs: 7000,
      });
      return;
    }
    setBillingCancelInProgress(true);
    try {
      const payload = await ApiService.cancelBillingSubscription();
      const alreadyCanceled = Boolean(payload?.alreadyCanceled);
      const cancelAtPeriodEnd = Boolean(payload?.cancelAtPeriodEnd);
      const stateSyncDeferred = Boolean(payload?.stateSyncDeferred);
      const refreshedProfile = await refreshProfileAfterBillingAction({
        attempts: 2,
        retryDelayMs: 1200,
      });
      if (alreadyCanceled) {
        dialog.setBannerNotice({
          tone: 'info',
          message: 'Subscription is already cancelled for period end.',
          autoDismissMs: 7000,
        });
      } else if (stateSyncDeferred) {
        dialog.setBannerNotice({
          tone: 'info',
          message: cancelAtPeriodEnd
            ? 'Stripe cancellation is scheduled, but profile sync is delayed. Refresh in a moment to confirm local role and billing status.'
            : 'Stripe cancellation succeeded, but profile sync is delayed. Refresh in a moment to confirm local role and billing status.',
          autoDismissMs: 9000,
        });
      } else if (!refreshedProfile) {
        dialog.setBannerNotice({
          tone: 'error',
          message: 'Stripe accepted the cancellation, but profile refresh failed. Reopen Profile in a moment to confirm subscription status.',
          autoDismissMs: 9000,
        });
      } else {
        dialog.setBannerNotice({
          tone: 'success',
          message: cancelAtPeriodEnd
            ? 'Subscription cancellation is scheduled for period end. Pro access remains active until then.'
            : 'Subscription canceled.',
          autoDismissMs: 8000,
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel subscription.';
      dialog.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
    } finally {
      setBillingCancelInProgress(false);
    }
  }, [
    auth.userProfile?.billing?.enabled,
    auth.userProfile?.billing?.cancelAtPeriodEnd,
    auth.userProfile?.billing?.hasSubscription,
    billingCheckoutInProgressKind,
    dialog.setBannerNotice,
    refreshProfileAfterBillingAction,
  ]);

  // ── Save & Download ────────────────────────────────────────────────
  const saveDownload = useSaveDownload({
    pdfDoc,
    sourceFile,
    sourceFileName,
    fields: fieldHistory.fields,
    checkboxRules: openAi.checkboxRules,
    checkboxHints: openAi.checkboxHints,
    textTransformRules: openAi.textTransformRules,
    mappingSessionId: detection.mappingSessionId,
    activeSavedFormId: savedForms.activeSavedFormId,
    activeSavedFormName: savedForms.activeSavedFormName,
    savedFormsCount: savedForms.savedForms.length,
    savedFormsMax: auth.profileLimits.savedFormsMax,
    verifiedUser: auth.verifiedUser,
    setBannerNotice: dialog.setBannerNotice,
    setLoadError,
    requestConfirm: dialog.requestConfirm,
    requestPrompt: dialog.requestPrompt,
    refreshSavedForms: savedForms.refreshSavedForms,
    setActiveSavedFormId: savedForms.setActiveSavedFormId,
    setActiveSavedFormName: savedForms.setActiveSavedFormName,
    queueSaveAfterLimit: savedForms.queueSaveAfterLimit,
    allowAnonymousDownload: sourceFileIsDemo,
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
      if (field.page && field.page !== currentPage) setCurrentPage(field.page);
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
    fieldState.setSelectedFieldId((prev: string | null) => {
      if (!prev) return prev;
      const field = fieldHistory.fieldsRef.current.find((entry) => entry.id === prev);
      if (!field) return prev;
      return field.page === page ? prev : null;
    });
  }, [fieldHistory.fieldsRef, fieldState]);

  const handlePageJumpComplete = useCallback(() => { setPendingPageJump(null); }, []);

  const handleSetTransformMode = useCallback(
    (enabled: boolean) => {
      setTransformMode(enabled);
      if (enabled) {
        fieldState.setShowFields(true);
        fieldState.setShowFieldInfo(false);
      }
    },
    [fieldState],
  );

  const handleSetCreateTool = useCallback(
    (type: FieldType | null) => {
      setActiveCreateTool(type);
      if (type) {
        fieldState.setShowFields(true);
        fieldState.setShowFieldInfo(false);
      }
    },
    [fieldState],
  );

  const handleCreateFieldWithRect = useCallback(
    (page: number, type: FieldType, rect: { x: number; y: number; width: number; height: number }) => {
      const pageSize = pageSizes[page];
      if (!pageSize) return;
      let createdFieldId: string | null = null;
      fieldHistory.updateFieldsWith((prev) => {
        const created = createFieldWithRect(type, page, pageSize, prev, rect);
        createdFieldId = created.id;
        return [...prev, created];
      });
      if (createdFieldId) {
        fieldState.setSelectedFieldId(createdFieldId);
      }
    },
    [fieldHistory, fieldState, pageSizes],
  );

  const handleSetFieldType = useCallback(
    (fieldId: string, type: FieldType) => {
      const current = fieldHistory.fieldsRef.current.find((field) => field.id === fieldId);
      if (!current) return;
      const pageSize = pageSizes[current.page];
      const nextRect = pageSize
        ? normalizeRectForFieldType(current.rect, type, pageSize)
        : current.rect;
      fieldState.handleUpdateField(fieldId, { type, rect: nextRect });
    },
    [fieldHistory.fieldsRef, fieldState, pageSizes],
  );

  const handleApplyDisplayPreset = useCallback(
    (preset: Exclude<FieldListDisplayPreset, 'custom'>) => {
      if (preset === 'review') {
        handleSetTransformMode(false);
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
      fieldState.setShowFields(true);
      fieldState.setShowFieldNames(false);
      fieldState.setShowFieldInfo(true);
    },
    [fieldState, handleSetTransformMode],
  );

  const handleShowFieldInfoChange = useCallback(
    (enabled: boolean) => {
      if (enabled) {
        handleSetTransformMode(false);
        setActiveCreateTool(null);
      }
      fieldState.handleShowFieldInfoChange(enabled);
    },
    [fieldState, handleSetTransformMode],
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
    handleApplyDisplayPreset('edit');
  }, [handleApplyDisplayPreset, pdfDoc]);

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

    if (!isMobileView || showHomepage) return;
    if (pdfDoc || detection.isProcessing) {
      const transitionedToMobile = !wasMobile && isMobileView;
      if (
        transitionedToMobile &&
        !dialog.bannerNotice &&
        !openAi.openAiError &&
        !dataSource.schemaError
      ) {
        dialog.setBannerNotice({
          tone: 'info',
          message:
            'The full editor is optimized for desktop. Increase window width above 900px for the best editing workflow.',
          autoDismissMs: 8000,
        });
      }
      return;
    }
    setShowHomepage(true);
  }, [dataSource.schemaError, detection.isProcessing, dialog, isMobileView, openAi.openAiError, pdfDoc, showHomepage]);

  useEffect(() => {
    if (!fieldState.showFields) return;
    fieldState.lastFieldVisibilityRef.current = {
      showFieldInfo: fieldState.showFieldInfo,
      showFieldNames: fieldState.showFieldNames,
    };
  }, [fieldState, fieldState.showFieldInfo, fieldState.showFieldNames, fieldState.showFields]);

  useEffect(() => {
    if (openAi.openAiError || dataSource.schemaError) dialog.setBannerNotice(null);
  }, [dataSource.schemaError, dialog, openAi.openAiError]);

  useEffect(() => {
    if (!auth.authReady && !assumeAuthReady) return;
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    const billingState = (url.searchParams.get('billing') || '').toLowerCase();
    if (!billingState) return;
    if (billingState === 'success') {
      dialog.setBannerNotice({
        tone: 'info',
        message: 'Checkout completed. Syncing your profile credits…',
        autoDismissMs: 8000,
      });
      void (async () => {
        let reconciledCount = 0;
        let reconcileFailed = false;
        try {
          const reconciliation = await ApiService.reconcileBillingCheckoutFulfillment({
            lookbackHours: 72,
            maxEvents: 150,
            dryRun: false,
          });
          reconciledCount = typeof reconciliation?.reconciledCount === 'number' ? reconciliation.reconciledCount : 0;
        } catch (error) {
          reconcileFailed = true;
          debugLog('Billing checkout reconciliation failed', error);
        }
        const refreshedProfile = await refreshProfileAfterBillingAction({
          attempts: 3,
          retryDelayMs: 1200,
        });
        if (refreshedProfile) {
          const message = reconciledCount > 0
            ? `Checkout completed. Recovered ${reconciledCount} missed billing event${reconciledCount === 1 ? '' : 's'} and refreshed your profile.`
            : (reconcileFailed
              ? 'Checkout completed and your profile has been refreshed. Automatic billing reconciliation is temporarily unavailable.'
              : 'Checkout completed and your profile has been refreshed.');
          dialog.setBannerNotice({
            tone: 'success',
            message,
            autoDismissMs: 8000,
          });
        } else {
          dialog.setBannerNotice({
            tone: 'error',
            message: 'Checkout completed, but profile refresh failed. Reopen Profile in a moment to verify credits and subscription status.',
            autoDismissMs: 9000,
          });
        }
      })();
    } else if (billingState === 'cancel') {
      dialog.setBannerNotice({
        tone: 'info',
        message: 'Checkout was canceled.',
        autoDismissMs: 6000,
      });
    }
    url.searchParams.delete('billing');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  }, [assumeAuthReady, auth.authReady, dialog.setBannerNotice, refreshProfileAfterBillingAction]);

  useEffect(() => {
    if (!dialog.bannerNotice?.autoDismissMs) return undefined;
    const timer = setTimeout(() => dialog.setBannerNotice(null), dialog.bannerNotice.autoDismissMs);
    return () => clearTimeout(timer);
  }, [dialog, dialog.bannerNotice]);

  useEffect(() => {
    return () => {
      if (!pdfDoc) return;
      void pdfDoc.destroy().catch((error) => { debugLog('Failed to release PDF document resources', error); });
    };
  }, [pdfDoc]);

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
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT')
      ) {
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

      if (event.altKey && !modifier) {
        const step = event.shiftKey ? 10 : 1;
        if (key === 'arrowleft') {
          event.preventDefault();
          nudgeSelectedField(-1, 0, step);
          return;
        }
        if (key === 'arrowright') {
          event.preventDefault();
          nudgeSelectedField(1, 0, step);
          return;
        }
        if (key === 'arrowup') {
          event.preventDefault();
          nudgeSelectedField(0, -1, step);
          return;
        }
        if (key === 'arrowdown') {
          event.preventDefault();
          nudgeSelectedField(0, 1, step);
          return;
        }
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
  ]);

  // ── Computed values ────────────────────────────────────────────────
  const { demoActive, demoStepIndex, demoCompletionOpen, demoSearchPreset } = demo;
  const { isProcessing, processingMode, processingDetail } = detection;
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
    checkboxHints,
    textTransformRules,
    canRename,
    canMapSchema,
    canRenameAndMap,
    renameDisabledReason,
    mapSchemaDisabledReason,
    renameAndMapDisabledReason,
  } = openAi;
  const { schemaError, dataSourceKind, dataSourceLabel, schemaUploadInProgress, dataColumns, dataRows, identifierKey, canSearchFill } = dataSource;
  const { savedForms: savedFormsList, savedFormsLoading, deletingFormId, showSavedFormsLimitDialog } = savedForms;
  const { fields } = fieldHistory;
  const { showFields, showFieldNames, showFieldInfo, confidenceFilter, selectedFieldId, visibleFields, hasFieldValues } = fieldState;
  const selectedField = useMemo(
    () => fields.find((field) => field.id === selectedFieldId) || null,
    [fields, selectedFieldId],
  );
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

  const hasDocument = !!pdfDoc;
  const canSaveToProfile = Boolean(pdfDoc && verifiedUser);
  const canDownload = Boolean(pdfDoc && verifiedUser);

  const isDemoAsset = Boolean(sourceFileIsDemo && sourceFileName && DEMO_ASSET_NAME_SET.has(sourceFileName));
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
  const activeDemoStep = demoStepIndex !== null ? DEMO_STEPS[demoStepIndex] : null;
  const showDemoTour = demoActive && currentView === 'editor';
  const shouldShowProcessingAd = processingMode === 'detect' && Boolean(PROCESSING_AD_VIDEO_URL);

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
      deletingFormId={deletingFormId} onDelete={savedForms.handleSavedFormsLimitDelete}
      onClose={savedForms.closeSavedFormsLimitDialog} />
  );
  const demoCompletionDialog = (
    <ConfirmDialog open={demoCompletionOpen} title="Demo complete"
      description="Replay the walkthrough or keep exploring the editor with the mapped PDF."
      confirmLabel="Replay demo" cancelLabel="Continue in editor"
      onConfirm={demo.handleDemoReplay} onCancel={demo.handleDemoContinue} />
  );
  const dataSourceInputs = (
    <>
      <input ref={dataSource.csvInputRef} id="csv-file-input" name="csv-file" type="file" accept=".csv,text/csv" style={{ display: 'none' }} onChange={dataSource.handleCsvFileSelected} />
      <input ref={dataSource.excelInputRef} id="excel-file-input" name="excel-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" style={{ display: 'none' }} onChange={dataSource.handleExcelFileSelected} />
      <input ref={dataSource.jsonInputRef} id="json-file-input" name="json-file" type="file" accept=".json,application/json" style={{ display: 'none' }} onChange={dataSource.handleJsonFileSelected} />
      <input ref={dataSource.txtInputRef} id="txt-file-input" name="txt-file" type="file" accept=".txt,text/plain" style={{ display: 'none' }} onChange={dataSource.handleTxtFileSelected} />
    </>
  );

  // ── Render ─────────────────────────────────────────────────────────
  if (!authReady && !assumeAuthReady) {
    return (<div className="auth-loading-screen"><div className="auth-loading-card">Loading workspace…</div></div>);
  }
  if (requiresEmailVerification) {
    return (<VerifyEmailPage email={authUser?.email ?? null} onRefresh={auth.handleRefreshVerification} onSignOut={handleSignOut} />);
  }
  if (showLogin) {
    return (<LoginPage onAuthenticated={() => auth.setShowLogin(false)} onCancel={() => auth.setShowLogin(false)} />);
  }
  if (showProfile && verifiedUser) {
    return (
      <>
        {shouldShowBannerAlert && bannerAlert ? <Alert tone={bannerAlert.tone} variant="banner" message={bannerAlert.message} onDismiss={handleDismissBanner} /> : null}
        {savedFormsLimitDialog}{dialogContent}
        <ProfilePage email={userProfile?.email ?? verifiedUser.email} role={userProfile?.role ?? 'base'}
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
          billingPlans={userProfile?.billing?.plans}
          profileError={auth.profileLoadError}
          creditPricing={userProfile?.creditPricing}
          isLoading={profileLoading}
          limits={profileLimits} savedForms={savedFormsList} savedFormsLoading={savedFormsLoading}
          onSelectSavedForm={handleSelectSavedFormFromProfile} onDeleteSavedForm={savedForms.handleDeleteSavedForm}
          deletingFormId={deletingFormId}
          billingCheckoutInProgressKind={billingCheckoutInProgressKind}
          billingCancelInProgress={billingCancelInProgress}
          onStartBillingCheckout={userProfile?.billing?.enabled === true ? handleStartBillingCheckout : undefined}
          onCancelBillingSubscription={userProfile?.billing?.enabled === true ? handleCancelBillingSubscription : undefined}
          onClose={auth.handleCloseProfile} onSignOut={handleSignOut} />
      </>
    );
  }

  if (currentView !== 'editor') {
    return (
      <div className="homepage-shell">
        {shouldShowBannerAlert && bannerAlert ? <Alert tone={bannerAlert.tone} variant="banner" message={bannerAlert.message} onDismiss={handleDismissBanner} /> : null}
        {savedFormsLimitDialog}{demoCompletionDialog}{dialogContent}
        <LegacyHeader currentView={currentView} onNavigateHome={handleNavigateHome}
          showBackButton={!showHomepage} userEmail={userEmail ?? null}
          onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined}
          onSignOut={verifiedUser ? handleSignOut : undefined}
          onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined} />
        <main className="landing-main">
          {currentView === 'homepage' && (
            <Homepage
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
          )}
          {currentView === 'upload' && (
            <UploadView
              loadError={loadError} showPipelineModal={pipeline.showPipelineModal}
              pendingDetectFile={pipeline.pendingDetectFile} uploadWantsRename={pipeline.uploadWantsRename}
              uploadWantsMap={pipeline.uploadWantsMap} schemaUploadInProgress={schemaUploadInProgress}
              dataSourceLabel={dataSourceLabel} pipelineError={pipeline.pipelineError}
              verifiedUser={!!verifiedUser} savedForms={savedFormsList} savedFormsLoading={savedFormsLoading}
              deletingFormId={deletingFormId}
              onSetUploadWantsRename={pipeline.setUploadWantsRename} onSetUploadWantsMap={pipeline.setUploadWantsMap}
              onSetPipelineError={pipeline.setPipelineError} onSetLoadError={setLoadError}
              onChooseDataSource={dataSource.handleChooseDataSource}
              onPipelineCancel={pipeline.cancel} onPipelineConfirm={pipeline.confirm}
              onDetectUpload={pipeline.openModal} onFillableUpload={handleFillableUpload}
              onSelectSavedForm={handleSelectSavedForm} onDeleteSavedForm={savedForms.handleDeleteSavedForm} />
          )}
          {currentView === 'processing' && (
            <ProcessingView detail={processingDetail} showAd={shouldShowProcessingAd}
              adVideoUrl={PROCESSING_AD_VIDEO_URL} adPosterUrl={PROCESSING_AD_POSTER_URL} />
          )}
        </main>
        {dataSourceInputs}
      </div>
    );
  }

  const appShellClassName = demoActive || demoCompletionOpen ? 'app app--demo-locked' : 'app';
  return (
    <div className={appShellClassName}>
      {shouldShowBannerAlert && bannerAlert ? <Alert tone={bannerAlert.tone} variant="banner" message={bannerAlert.message} onDismiss={handleDismissBanner} /> : null}
      {savedFormsLimitDialog}{demoCompletionDialog}{dialogContent}
      <HeaderBar
        pageCount={pageCount} currentPage={currentPage} scale={scale} onScaleChange={setScale}
        onNavigateHome={handleNavigateHome} mappingInProgress={mappingInProgress}
        mapSchemaInProgress={mapSchemaInProgress} hasMappedSchema={hasMappedSchema}
        renameInProgress={renameInProgress} hasRenamedFields={hasRenamedFields}
        dataSourceKind={dataSourceKind} dataSourceLabel={dataSourceLabel}
        onChooseDataSource={dataSource.handleChooseDataSource} onClearDataSource={dataSource.handleClearDataSource}
        onRename={demoActive ? demo.handleDemoRename : handleRename}
        onRenameAndMap={demoActive ? demo.handleDemoRenameAndMap : handleRenameAndMap}
        onMapSchema={demoActive ? demo.handleDemoMapSchema : handleMapSchema}
        canMapSchema={demoActive ? true : canMapSchema} canRename={demoActive ? true : canRename}
        canRenameAndMap={demoActive ? true : canRenameAndMap}
        mapSchemaDisabledReason={demoActive ? null : mapSchemaDisabledReason}
        renameDisabledReason={demoActive ? null : renameDisabledReason}
        renameAndMapDisabledReason={demoActive ? null : renameAndMapDisabledReason}
        onOpenSearchFill={canSearchFill ? () => setShowSearchFill(true) : undefined}
        canSearchFill={canSearchFill} onDownload={saveDownload.handleDownload} onSaveToProfile={saveDownload.handleSaveToProfile}
        downloadInProgress={saveDownload.downloadInProgress} saveInProgress={saveDownload.saveInProgress}
        canDownload={canDownload} canSave={canSaveToProfile} userEmail={userEmail}
        onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined}
        onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
        demoLocked={demoUiLocked} onDemoLockedAction={handleDemoLockedAction} />
      <div className="app-shell">
        <FieldListPanel fields={visibleFields} totalFieldCount={fields.length}
          selectedFieldId={selectedFieldId} selectedField={selectedField}
          currentPage={currentPage} pageCount={pageCount} showFields={showFields}
          showFieldNames={showFieldNames} showFieldInfo={showFieldInfo}
          transformMode={transformMode}
          displayPreset={displayPreset} onApplyDisplayPreset={handleApplyDisplayPreset}
          onShowFieldsChange={fieldState.handleShowFieldsChange}
          onShowFieldNamesChange={fieldState.handleShowFieldNamesChange}
          onShowFieldInfoChange={handleShowFieldInfoChange}
          onTransformModeChange={handleSetTransformMode}
          canClearInputs={hasFieldValues} onClearInputs={fieldState.handleClearFieldValues}
          confidenceFilter={confidenceFilter} onConfidenceFilterChange={fieldState.handleConfidenceFilterChange}
          onResetConfidenceFilters={handleResetConfidenceFilters}
          onSelectField={handleSelectField} onPageChange={handlePageJump} />
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
              moveEnabled={!showFieldInfo}
              resizeEnabled={transformMode && !showFieldInfo}
              createEnabled={Boolean(activeCreateTool) && !showFieldInfo}
              activeCreateTool={activeCreateTool}
              selectedFieldId={selectedFieldId}
              onSelectField={handleSelectField} onUpdateField={fieldState.handleUpdateField}
              onUpdateFieldGeometry={fieldState.handleUpdateFieldGeometry}
              onCreateFieldWithRect={handleCreateFieldWithRect}
              onBeginFieldChange={fieldHistory.beginFieldHistory}
              onCommitFieldChange={fieldHistory.commitFieldHistory}
              onPageChange={handlePageScroll} pendingPageJump={pendingPageJump}
              onPageJumpComplete={handlePageJumpComplete} />
          )}
        </main>
        <FieldInspectorPanel fields={fields} selectedFieldId={selectedFieldId}
          activeCreateTool={activeCreateTool}
          onUpdateField={fieldState.handleUpdateField}
          onSetFieldType={handleSetFieldType}
          onUpdateFieldDraft={fieldState.handleUpdateFieldDraft}
          onDeleteField={fieldState.handleDeleteField}
          onCreateToolChange={handleSetCreateTool}
          onUndo={handleUndo}
          onRedo={handleRedo}
          canUndo={fieldHistory.canUndo}
          canRedo={fieldHistory.canRedo}
          onBeginFieldChange={fieldHistory.beginFieldHistory}
          onCommitFieldChange={fieldHistory.commitFieldHistory} />
      </div>
      {showSearchFill ? (
        <SearchFillModal open={showSearchFill} onClose={() => setShowSearchFill(false)}
          sessionId={searchFillSessionId} dataSourceKind={dataSourceKind}
          dataSourceLabel={dataSourceLabel} columns={dataColumns}
          identifierKey={identifierKey} rows={dataRows} fields={fields}
          checkboxRules={checkboxRules} checkboxHints={checkboxHints}
          textTransformRules={textTransformRules}
          onFieldsChange={fieldState.handleFieldsChange} onClearFields={fieldState.handleClearFieldValues}
          onAfterFill={() => {
            handleSetTransformMode(false);
            setActiveCreateTool(null);
            fieldState.setShowFieldInfo(true); fieldState.setShowFieldNames(false);
            fieldState.setShowFields(true);
            if (demoActive && DEMO_STEPS[demoStepIndex ?? -1]?.id === 'search-fill') demo.handleDemoCompletion();
          }}
          onError={(message) => dataSource.setSchemaError(message)}
          onRequestDataSource={(kind) => dataSource.handleChooseDataSource(kind)}
          demoSearch={demoActive ? demoSearchPreset : null} />
      ) : null}
      {dataSourceInputs}
      {showDemoTour ? (
        <DemoTour open={showDemoTour} step={activeDemoStep} stepIndex={demoStepIndex ?? 0}
          stepCount={DEMO_STEPS.length} onNext={demo.handleDemoNext}
          onBack={demo.handleDemoBack} onClose={demo.exitDemo} />
      ) : null}
    </div>
  );
}

export default WorkspaceRuntime;
