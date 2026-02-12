/**
 * App shell that orchestrates PDF detection, mapping, and viewer state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { FieldListPanel } from './components/panels/FieldListPanel';
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

/**
 * Main application component that coordinates auth, detection, and editing.
 */
function App() {
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
  const [showHomepage, setShowHomepage] = useState(true);
  const [isMobileView, setIsMobileView] = useState(false);
  const [showSearchFill, setShowSearchFill] = useState(false);
  const [searchFillSessionId, setSearchFillSessionId] = useState(0);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceFileName, setSourceFileName] = useState<string | null>(null);
  const [sourceFileIsDemo, setSourceFileIsDemo] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

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

  // ── Save & Download ────────────────────────────────────────────────
  const saveDownload = useSaveDownload({
    pdfDoc,
    sourceFile,
    sourceFileName,
    fields: fieldHistory.fields,
    checkboxRules: openAi.checkboxRules,
    checkboxHints: openAi.checkboxHints,
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

  const handleCreateField = useCallback(
    (type: FieldType) => fieldState.handleCreateField(type, currentPage, pageSizes),
    [currentPage, fieldState, pageSizes],
  );

  const handleUndo = useCallback(
    () => fieldHistory.handleUndo((updater) => fieldState.setSelectedFieldId(updater)),
    [fieldHistory, fieldState],
  );

  const handleRedo = useCallback(
    () => fieldHistory.handleRedo((updater) => fieldState.setSelectedFieldId(updater)),
    [fieldHistory, fieldState],
  );

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
    const mediaQuery = window.matchMedia('(max-width: 1020px)');
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

  useEffect(() => {
    if (!isMobileView || showHomepage) return;
    if (pdfDoc || detection.isProcessing) {
      if (!dialog.bannerNotice && !openAi.openAiError && !dataSource.schemaError) {
        dialog.setBannerNotice({
          tone: 'info',
          message: 'The editor works best on larger screens. If controls feel cramped, increase your window size.',
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

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!pdfDoc || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')) return;
      const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
      const modifier = isMac ? event.metaKey : event.ctrlKey;
      if (!modifier) return;
      const key = event.key.toLowerCase();
      if (key === 'z') {
        event.preventDefault();
        if (event.shiftKey) handleRedo(); else handleUndo();
      } else if (key === 'x') {
        if (!fieldState.selectedFieldId) return;
        event.preventDefault();
        fieldState.handleDeleteField(fieldState.selectedFieldId);
      } else if (key === 'y') {
        event.preventDefault(); handleRedo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [fieldState, handleRedo, handleUndo, pdfDoc]);

  // ── Computed values ────────────────────────────────────────────────
  const { demoActive, demoStepIndex, demoCompletionOpen, demoSearchPreset } = demo;
  const { isProcessing, processingMode, processingDetail } = detection;
  const { verifiedUser, userEmail, requiresEmailVerification, authReady, showLogin, showProfile, profileLimits, authUser, profileLoading, userProfile } = auth;
  const { bannerNotice, dialogRequest } = dialog;
  const { openAiError, renameInProgress, hasRenamedFields, mappingInProgress, mapSchemaInProgress, hasMappedSchema, checkboxRules, checkboxHints, canRename, canMapSchema, canRenameAndMap } = openAi;
  const { schemaError, dataSourceKind, dataSourceLabel, schemaUploadInProgress, dataColumns, dataRows, identifierKey, canSearchFill } = dataSource;
  const { savedForms: savedFormsList, deletingFormId, showSavedFormsLimitDialog } = savedForms;
  const { fields } = fieldHistory;
  const { showFields, showFieldNames, showFieldInfo, confidenceFilter, selectedFieldId, visibleFields, hasFieldValues } = fieldState;

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
  if (!authReady) {
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
        <ProfilePage email={userProfile?.email ?? verifiedUser.email} role={userProfile?.role ?? 'basic'}
          creditsRemaining={userProfile?.creditsRemaining ?? 0} isLoading={profileLoading}
          limits={profileLimits} savedForms={savedFormsList}
          onSelectSavedForm={handleSelectSavedFormFromProfile} onDeleteSavedForm={savedForms.handleDeleteSavedForm}
          deletingFormId={deletingFormId} onClose={auth.handleCloseProfile} onSignOut={handleSignOut} />
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
            <Homepage onStartWorkflow={() => setShowHomepage(false)} onStartDemo={demo.startDemo}
              userEmail={userEmail ?? null} onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined}
              onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined} />
          )}
          {currentView === 'upload' && (
            <UploadView
              loadError={loadError} showPipelineModal={pipeline.showPipelineModal}
              pendingDetectFile={pipeline.pendingDetectFile} uploadWantsRename={pipeline.uploadWantsRename}
              uploadWantsMap={pipeline.uploadWantsMap} schemaUploadInProgress={schemaUploadInProgress}
              dataSourceLabel={dataSourceLabel} pipelineError={pipeline.pipelineError}
              verifiedUser={!!verifiedUser} savedForms={savedFormsList} deletingFormId={deletingFormId}
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
        onOpenSearchFill={canSearchFill ? () => setShowSearchFill(true) : undefined}
        canSearchFill={canSearchFill} onDownload={saveDownload.handleDownload} onSaveToProfile={saveDownload.handleSaveToProfile}
        downloadInProgress={saveDownload.downloadInProgress} saveInProgress={saveDownload.saveInProgress}
        canDownload={canDownload} canSave={canSaveToProfile} userEmail={userEmail}
        onOpenProfile={verifiedUser ? auth.handleOpenProfile : undefined}
        onSignIn={!verifiedUser ? () => auth.setShowLogin(true) : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
        demoLocked={demoUiLocked} onDemoLockedAction={handleDemoLockedAction} />
      <div className="app-shell">
        <FieldListPanel fields={visibleFields} selectedFieldId={selectedFieldId}
          currentPage={currentPage} pageCount={pageCount} showFields={showFields}
          showFieldNames={showFieldNames} showFieldInfo={showFieldInfo}
          onShowFieldsChange={fieldState.handleShowFieldsChange}
          onShowFieldNamesChange={fieldState.handleShowFieldNamesChange}
          onShowFieldInfoChange={fieldState.handleShowFieldInfoChange}
          canClearInputs={hasFieldValues} onClearInputs={fieldState.handleClearFieldValues}
          confidenceFilter={confidenceFilter} onConfidenceFilterChange={fieldState.handleConfidenceFilterChange}
          onSelectField={handleSelectField} onPageChange={handlePageJump} />
        <main className="workspace">
          {loadError ? (
            <div className="viewer viewer--empty">
              <div className="viewer__placeholder viewer__placeholder--error">
                <h2>Unable to load PDF</h2><Alert tone="error" variant="inline" message={loadError} />
              </div>
            </div>
          ) : (
            <PdfViewer pdfDoc={pdfDoc} pageNumber={currentPage} scale={scale} pageSizes={pageSizes}
              fields={visibleFields} showFields={showFields} showFieldNames={showFieldNames}
              showFieldInfo={showFieldInfo} selectedFieldId={selectedFieldId}
              onSelectField={handleSelectField} onUpdateField={fieldState.handleUpdateField}
              onUpdateFieldGeometry={fieldState.handleUpdateFieldGeometry}
              onBeginFieldChange={fieldHistory.beginFieldHistory}
              onCommitFieldChange={fieldHistory.commitFieldHistory}
              onPageChange={handlePageScroll} pendingPageJump={pendingPageJump}
              onPageJumpComplete={handlePageJumpComplete} />
          )}
        </main>
        <FieldInspectorPanel fields={fields} selectedFieldId={selectedFieldId}
          currentPage={currentPage} onUpdateField={fieldState.handleUpdateField}
          onUpdateFieldDraft={fieldState.handleUpdateFieldDraft}
          onDeleteField={fieldState.handleDeleteField} onCreateField={handleCreateField}
          onBeginFieldChange={fieldHistory.beginFieldHistory}
          onCommitFieldChange={fieldHistory.commitFieldHistory}
          canUndo={fieldHistory.canUndo} canRedo={fieldHistory.canRedo}
          onUndo={handleUndo} onRedo={handleRedo} />
      </div>
      {showSearchFill ? (
        <SearchFillModal open={showSearchFill} onClose={() => setShowSearchFill(false)}
          sessionId={searchFillSessionId} dataSourceKind={dataSourceKind}
          dataSourceLabel={dataSourceLabel} columns={dataColumns}
          identifierKey={identifierKey} rows={dataRows} fields={fields}
          checkboxRules={checkboxRules} checkboxHints={checkboxHints}
          onFieldsChange={fieldState.handleFieldsChange} onClearFields={fieldState.handleClearFieldValues}
          onAfterFill={() => {
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

export default App;
