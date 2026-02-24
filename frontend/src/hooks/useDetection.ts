import { useCallback, useEffect, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import type {
  BannerNotice,
  CheckboxHint,
  CheckboxRule,
  PageSize,
  PdfField,
  PendingAutoActions,
  ProcessingMode,
  TextTransformRule,
} from '../types';
import {
  DETECTION_RUNNING_STANDARD_CPU_MESSAGE,
  DETECTION_WAITING_STANDARD_CPU_MESSAGE,
  mapDetectionFields,
  resolveDetectionStatusMessage,
} from '../utils/detection';
import { extractFieldsFromPdf, loadPageSizes, loadPdfFromFile } from '../utils/pdf';
import { buildTemplateFields } from '../utils/fields';
import { debugLog } from '../utils/debug';
import { ApiError } from '../services/apiConfig';
import { ApiService } from '../services/api';
import { detectFields, pollDetectionStatus } from '../services/detectionApi';
import {
  DETECTION_POST_WARMUP_MESSAGE,
  DETECTION_WARMUP_DELAY_MS,
  DETECTION_WARMUP_DURATION_MS,
  DETECTION_WARMUP_MESSAGE,
  DETECTION_WARMUP_PAGE_THRESHOLD,
  DEFAULT_PROCESSING_MESSAGE,
  DEMO_ASSETS,
  DETECTION_BACKGROUND_MAX_RETRIES,
  DETECTION_BACKGROUND_POLL_TIMEOUT_MS,
  DETECTION_BACKGROUND_RETRY_BASE_MS,
  DETECTION_BACKGROUND_RETRY_MAX_MS,
  FILLABLE_TEMPLATE_PROCESSING_MESSAGE,
  QUEUE_WAIT_THRESHOLD_MS,
  SAVED_FORM_PROCESSING_MESSAGE,
} from '../config/appConstants';

const DEMO_ASSET_NAME_SET = new Set(Object.values(DEMO_ASSETS));

export interface UseDetectionDeps {
  verifiedUser: User | null;
  profileLimits: { detectMaxPages: number; fillableMaxPages: number };
  fieldsRef: React.MutableRefObject<PdfField[]>;
  historyRef: React.MutableRefObject<{ undo: PdfField[][]; redo: PdfField[][] }>;
  resetFieldHistory: (fields?: PdfField[]) => void;
  updateFields: (fields: PdfField[], options?: { trackHistory?: boolean }) => void;
  setSelectedFieldId: (updater: string | null | ((prev: string | null) => string | null)) => void;
  clearWorkspace: () => void;
  setBannerNotice: (notice: BannerNotice | null) => void;
  setShowHomepage: (value: boolean) => void;
  setHasRenamedFields: (value: boolean) => void;
  setHasMappedSchema: (value: boolean) => void;
  setCheckboxRules: (rules: CheckboxRule[]) => void;
  setCheckboxHints: (hints: CheckboxHint[]) => void;
  setTextTransformRules: (rules: TextTransformRule[]) => void;
  setSchemaError: (value: string | null) => void;
  setOpenAiError: (value: string | null) => void;
  setSourceFile: (file: File | null) => void;
  setSourceFileName: (name: string | null) => void;
  setSourceFileIsDemo: (value: boolean) => void;
  setActiveSavedFormId: (id: string | null) => void;
  setActiveSavedFormName: (name: string | null) => void;
  setShowSearchFill: (value: boolean) => void;
  setSearchFillSessionId: (updater: (prev: number) => number) => void;
  setLoadError: (message: string | null) => void;
  runOpenAiRename: (options?: {
    confirm?: boolean;
    allowDefer?: boolean;
    sessionId?: string | null;
    schemaId?: string | null;
  }) => Promise<PdfField[] | null>;
  applySchemaMappings: (options?: {
    fieldsOverride?: PdfField[];
    schemaIdOverride?: string | null;
  }) => Promise<boolean>;
  handleMappingSuccess: () => void;
  schemaId: string | null;
  // Session keep-alive deps
  pdfDoc: PDFDocumentProxy | null;
  sourceFileIsDemo: boolean;
  sourceFileName: string | null;
  demoStateRef: React.MutableRefObject<{ demoActive: boolean; demoCompletionOpen: boolean }>;
}

export function useDetection(deps: UseDetectionDeps) {
  const [detectSessionId, setDetectSessionId] = useState<string | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMode, setProcessingMode] = useState<ProcessingMode>(null);
  const [processingDetail, setProcessingDetail] = useState(DEFAULT_PROCESSING_MESSAGE);
  const loadTokenRef = useRef(0);
  const detectionRetryRef = useRef<Map<string, number>>(new Map());
  const resumeDetectionPollingRef = useRef<((sessionId: string, loadToken: number) => void) | null>(null);
  const pendingAutoActionsRef = useRef<PendingAutoActions | null>(null);
  const detectionPipeline: 'commonforms' = 'commonforms';

  const scheduleDetectionRetry = useCallback((sessionId: string, loadToken: number) => {
    const attempts = detectionRetryRef.current.get(sessionId) ?? 0;
    const nextAttempt = attempts + 1;
    if (nextAttempt > DETECTION_BACKGROUND_MAX_RETRIES) {
      detectionRetryRef.current.delete(sessionId);
      return;
    }
    detectionRetryRef.current.set(sessionId, nextAttempt);
    const delay = Math.min(
      DETECTION_BACKGROUND_RETRY_MAX_MS,
      DETECTION_BACKGROUND_RETRY_BASE_MS * 2 ** (nextAttempt - 1),
    );
    window.setTimeout(() => {
      resumeDetectionPollingRef.current?.(sessionId, loadToken);
    }, delay);
  }, []);

  const resumeDetectionPolling = useCallback(
    async (sessionId: string, loadToken: number) => {
      try {
        const payload = await pollDetectionStatus(sessionId, {
          timeoutMs: DETECTION_BACKGROUND_POLL_TIMEOUT_MS,
        });
        if (loadTokenRef.current !== loadToken) return;
        const status = String(payload?.status || '').toLowerCase();
        if (status === 'complete') {
          detectionRetryRef.current.delete(sessionId);
          const nextFields = mapDetectionFields(payload);
          if (!nextFields.length) {
            deps.setBannerNotice({ tone: 'info', message: 'Detection finished but no fields were found.', autoDismissMs: 8000 });
            return;
          }
          const hasEdits = deps.historyRef.current.undo.length > 0;
          if (hasEdits) {
            deps.updateFields(nextFields);
          } else {
            deps.resetFieldHistory(nextFields);
          }
          deps.setSelectedFieldId(null);
          deps.setHasRenamedFields(false);
          deps.setHasMappedSchema(false);
          deps.setCheckboxRules([]);
          deps.setCheckboxHints([]);
          deps.setTextTransformRules([]);
          setDetectSessionId(sessionId);
          setMappingSessionId(sessionId);
          const pendingAutoActions = pendingAutoActionsRef.current;
          if (
            pendingAutoActions &&
            pendingAutoActions.loadToken === loadToken &&
            pendingAutoActions.sessionId === sessionId
          ) {
            pendingAutoActionsRef.current = null;
            if (pendingAutoActions.autoRename && pendingAutoActions.autoMap) {
              const renamed = await deps.runOpenAiRename({
                confirm: false, allowDefer: true, sessionId, schemaId: pendingAutoActions.schemaId,
              });
              if (renamed) deps.handleMappingSuccess();
            } else if (pendingAutoActions.autoRename) {
              await deps.runOpenAiRename({ confirm: false, allowDefer: true, sessionId });
            } else if (pendingAutoActions.autoMap) {
              if (!pendingAutoActions.schemaId) {
                deps.setSchemaError('Upload a schema file before running mapping.');
              } else {
                const mapped = await deps.applySchemaMappings({ schemaIdOverride: pendingAutoActions.schemaId });
                if (mapped) deps.handleMappingSuccess();
              }
            }
          }
          deps.setBannerNotice({
            tone: 'success',
            message: `Detection finished in the background (${nextFields.length} fields).`,
            autoDismissMs: 7000,
          });
          return;
        }
        if (status === 'failed') {
          detectionRetryRef.current.delete(sessionId);
          const message = payload?.error || 'Detection failed on the backend.';
          deps.setBannerNotice({ tone: 'error', message: String(message), autoDismissMs: 8000 });
          return;
        }
        if (payload?.timedOut) {
          deps.setBannerNotice({
            tone: 'info', message: 'Detection is still running on the backend. It may take a few more minutes.', autoDismissMs: 8000,
          });
          scheduleDetectionRetry(sessionId, loadToken);
        }
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        if (error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404)) {
          detectionRetryRef.current.delete(sessionId);
          pendingAutoActionsRef.current = null;
          setDetectSessionId(null);
          setMappingSessionId(null);
          deps.setBannerNotice({ tone: 'error', message: (error as Error).message, autoDismissMs: 8000 });
          return;
        }
        const message = error instanceof Error ? error.message : 'Detection failed on the backend.';
        deps.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
        scheduleDetectionRetry(sessionId, loadToken);
      }
    },
    [scheduleDetectionRetry, deps],
  );

  useEffect(() => {
    resumeDetectionPollingRef.current = resumeDetectionPolling;
  }, [resumeDetectionPolling]);

  const commitPdfLoad = useCallback(
    (
      doc: PDFDocumentProxy,
      sizes: Record<number, PageSize>,
      initialFields: PdfField[],
      loadToken: number,
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      if (loadTokenRef.current !== loadToken) return false;
      pdfState.setPdfDoc(doc);
      pdfState.setPageSizes(sizes);
      pdfState.setPageCount(doc.numPages);
      pdfState.setCurrentPage(1);
      pdfState.setScale(1);
      pdfState.setPendingPageJump(null);
      deps.resetFieldHistory(initialFields);
      deps.setSelectedFieldId(null);
      setIsProcessing(false);
      setProcessingMode(null);
      return true;
    },
    [deps],
  );

  const handleFillableUpload = useCallback(
    async (
      file: File,
      options: { isDemo?: boolean; skipExistingFields?: boolean } = {},
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      deps.setShowSearchFill(false);
      deps.setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('fillable');
      setIsProcessing(true);
      setProcessingDetail(FILLABLE_TEMPLATE_PROCESSING_MESSAGE);
      deps.setLoadError(null);
      deps.setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      deps.setHasRenamedFields(false);
      deps.setHasMappedSchema(false);
      deps.setCheckboxRules([]);
      deps.setCheckboxHints([]);
      deps.setTextTransformRules([]);
      deps.setSchemaError(null);
      deps.setOpenAiError(null);
      deps.setSourceFile(file);
      deps.setSourceFileName(file.name);
      deps.setSourceFileIsDemo(Boolean(options.isDemo));
      deps.setActiveSavedFormId(null);
      deps.setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > deps.profileLimits.fillableMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(`Fillable uploads are limited to ${deps.profileLimits.fillableMaxPages} pages on your plan.`);
          return;
        }
        const sizesPromise = loadPageSizes(doc);
        const existingFieldsPromise = options.skipExistingFields
          ? null
          : (async () => {
              try { return await extractFieldsFromPdf(doc); }
              catch (error) { debugLog('Failed to extract existing fields', error); return []; }
            })();
        const sizes = await sizesPromise;
        if (!commitPdfLoad(doc, sizes, [], loadToken, pdfState)) return;

        if (!existingFieldsPromise) {
          debugLog('Loaded fillable PDF (existing fields suppressed)', { name: file.name, pages: doc.numPages });
          return;
        }

        void (async () => {
          const existingFields = await existingFieldsPromise;
          if (loadTokenRef.current !== loadToken) return;
          deps.resetFieldHistory(existingFields);
          deps.setSelectedFieldId(null);
          debugLog('Extracted existing PDF fields', { total: existingFields.length });
          debugLog('Loaded fillable PDF', { name: file.name, pages: doc.numPages, fields: existingFields.length });
          if (!existingFields.length) return;
          if (!deps.verifiedUser) return;
          try {
            const sessionPayload = await ApiService.createTemplateSession(file, {
              fields: buildTemplateFields(existingFields),
              pageCount: doc.numPages,
            });
            if (loadTokenRef.current !== loadToken) return;
            setDetectSessionId(sessionPayload.sessionId);
            setMappingSessionId(sessionPayload.sessionId);
          } catch (error) {
            if (loadTokenRef.current !== loadToken) return;
            deps.setBannerNotice({ tone: 'info', message: 'Rename is unavailable for this template.', autoDismissMs: 8000 });
            debugLog('Failed to register template session', error);
          }
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        deps.clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        deps.setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [commitPdfLoad, deps],
  );

  const handleSelectSavedForm = useCallback(
    async (
      formId: string,
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      deps.setShowSearchFill(false);
      deps.setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('saved');
      setIsProcessing(true);
      setProcessingDetail(SAVED_FORM_PROCESSING_MESSAGE);
      deps.setLoadError(null);
      deps.setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      deps.setHasRenamedFields(false);
      deps.setHasMappedSchema(false);
      deps.setSchemaError(null);
      deps.setOpenAiError(null);

      try {
        const [savedMeta, blob] = await Promise.all([
          ApiService.loadSavedForm(formId),
          ApiService.downloadSavedForm(formId),
        ]);
        const name = savedMeta?.name || 'saved-form.pdf';
        const file = new File([blob], name, { type: 'application/pdf' });
        deps.setSourceFile(file);
        deps.setSourceFileName(name);
        deps.setSourceFileIsDemo(false);
        const doc = await loadPdfFromFile(file);
        const sizesPromise = loadPageSizes(doc);
        const existingFieldsPromise = (async () => {
          try { return await extractFieldsFromPdf(doc); }
          catch (error) { debugLog('Failed to extract saved form fields', error); return []; }
        })();
        const sizes = await sizesPromise;
        if (!commitPdfLoad(doc, sizes, [], loadToken, pdfState)) return;
        deps.setActiveSavedFormId(formId);
        deps.setActiveSavedFormName(savedMeta?.name || null);
        const savedFillRules = savedMeta?.fillRules && typeof savedMeta.fillRules === 'object'
          ? savedMeta.fillRules
          : null;
        const savedCheckboxRules = Array.isArray(savedFillRules?.checkboxRules)
          ? (savedFillRules.checkboxRules as CheckboxRule[])
          : Array.isArray(savedMeta?.checkboxRules)
          ? (savedMeta.checkboxRules as CheckboxRule[])
          : [];
        const savedCheckboxHints = Array.isArray(savedFillRules?.checkboxHints)
          ? (savedFillRules.checkboxHints as CheckboxHint[])
          : Array.isArray(savedMeta?.checkboxHints)
          ? (savedMeta.checkboxHints as CheckboxHint[])
          : [];
        const savedTextTransformRules = Array.isArray(savedFillRules?.textTransformRules)
          ? (savedFillRules.textTransformRules as TextTransformRule[])
          : Array.isArray((savedFillRules as Record<string, unknown> | null)?.templateRules)
          ? ((savedFillRules as Record<string, unknown>).templateRules as TextTransformRule[])
          : Array.isArray(savedMeta?.textTransformRules)
          ? (savedMeta.textTransformRules as TextTransformRule[])
          : Array.isArray((savedMeta as Record<string, unknown> | null)?.templateRules)
          ? ((savedMeta as Record<string, unknown>).templateRules as TextTransformRule[])
          : [];
        deps.setCheckboxRules(savedCheckboxRules);
        deps.setCheckboxHints(savedCheckboxHints);
        deps.setTextTransformRules(savedTextTransformRules);

        void (async () => {
          const existingFields = await existingFieldsPromise;
          if (loadTokenRef.current !== loadToken) return;
          deps.resetFieldHistory(existingFields);
          deps.setSelectedFieldId(null);
          debugLog('Extracted saved form fields', { total: existingFields.length });
          debugLog('Loaded saved form', { name, pages: doc.numPages, fields: existingFields.length });
          if (!existingFields.length) {
            deps.setBannerNotice({ tone: 'info', message: 'No fields found in this saved form. Rename is unavailable.', autoDismissMs: 8000 });
            return;
          }
          try {
            const sessionPayload = await ApiService.createSavedFormSession(formId, {
              fields: buildTemplateFields(existingFields),
              pageCount: doc.numPages,
            });
            if (loadTokenRef.current !== loadToken) return;
            setDetectSessionId(sessionPayload.sessionId);
            setMappingSessionId(sessionPayload.sessionId);
          } catch (error) {
            if (loadTokenRef.current !== loadToken) return;
            deps.setBannerNotice({ tone: 'info', message: 'Rename is unavailable for this saved form.', autoDismissMs: 8000 });
            debugLog('Failed to register saved form session', error);
          }
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load saved form.';
        deps.clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        deps.setLoadError(message);
        debugLog('Failed to load saved form', message);
      }
    },
    [commitPdfLoad, deps],
  );

  const runDetectUpload = useCallback(
    async (
      file: File,
      options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null } = {},
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      pendingAutoActionsRef.current = null;
      detectionRetryRef.current.clear();
      deps.setShowSearchFill(false);
      deps.setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('detect');
      setIsProcessing(true);
      setProcessingDetail(DEFAULT_PROCESSING_MESSAGE);
      deps.setLoadError(null);
      deps.setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      deps.setHasRenamedFields(false);
      deps.setHasMappedSchema(false);
      deps.setCheckboxRules([]);
      deps.setCheckboxHints([]);
      deps.setTextTransformRules([]);
      deps.setSchemaError(null);
      deps.setOpenAiError(null);
      deps.setSourceFile(file);
      deps.setSourceFileName(file.name);
      deps.setSourceFileIsDemo(false);
      deps.setActiveSavedFormId(null);
      deps.setActiveSavedFormName(null);
      const openAiActionsRequested = Boolean(options.autoRename || options.autoMap);
      let warmupActive = false;
      let warmupCompleted = false;
      let warmupStartTimer: number | null = null;
      let warmupEndTimer: number | null = null;
      let shouldShowRenameWarmup = false;
      const clearWarmupTimers = () => {
        if (warmupStartTimer !== null) {
          window.clearTimeout(warmupStartTimer);
          warmupStartTimer = null;
        }
        if (warmupEndTimer !== null) {
          window.clearTimeout(warmupEndTimer);
          warmupEndTimer = null;
        }
      };
      const scheduleRenameWarmup = () => {
        if (!shouldShowRenameWarmup || warmupCompleted || warmupActive || warmupStartTimer !== null) return;
        warmupStartTimer = window.setTimeout(() => {
          warmupStartTimer = null;
          if (loadTokenRef.current !== loadToken || !shouldShowRenameWarmup || warmupCompleted) return;
          warmupActive = true;
          setProcessingDetail(DETECTION_WARMUP_MESSAGE);
          warmupEndTimer = window.setTimeout(() => {
            warmupEndTimer = null;
            if (loadTokenRef.current !== loadToken) return;
            warmupActive = false;
            warmupCompleted = true;
            setProcessingDetail(DETECTION_POST_WARMUP_MESSAGE);
          }, DETECTION_WARMUP_DURATION_MS);
        }, DETECTION_WARMUP_DELAY_MS);
      };
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > deps.profileLimits.detectMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(`Detection uploads are limited to ${deps.profileLimits.detectMaxPages} pages on your plan.`);
          return;
        }
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        shouldShowRenameWarmup = openAiActionsRequested && doc.numPages < DETECTION_WARMUP_PAGE_THRESHOLD;
        if (shouldShowRenameWarmup) {
          setProcessingDetail(DETECTION_WAITING_STANDARD_CPU_MESSAGE);
        }
        const activeSchemaId = options.schemaIdOverride ?? deps.schemaId;

        let detectedFields: PdfField[] = [];
        let detectedSessionId: string | null = null;
        let detectionTimedOut = false;
        let detectionError: string | null = null;
        let authFailure: ApiError | null = null;

        try {
          const detection = await detectFields(file, {
            pipeline: detectionPipeline,
            prewarmRename: Boolean(options.autoRename),
            prewarmRemap: Boolean(options.autoMap),
            onStatus: (payload) => {
              if (loadTokenRef.current !== loadToken) return;
              const message = resolveDetectionStatusMessage(payload, QUEUE_WAIT_THRESHOLD_MS);
              if (!message) return;
              if (warmupActive) return;
              const status = String(payload?.status || '').toLowerCase();
              const profile = String(payload?.detectionProfile || '').toLowerCase();
              if (shouldShowRenameWarmup && status === 'running' && profile === 'light') {
                setProcessingDetail(DETECTION_RUNNING_STANDARD_CPU_MESSAGE);
                scheduleRenameWarmup();
                return;
              }
              setProcessingDetail(message);
            },
          });
          detectedSessionId = detection?.sessionId || null;
          detectionTimedOut = Boolean(detection?.timedOut);
          detectedFields = mapDetectionFields(detection);
          debugLog('Field detection returned', { total: detectedFields.length });
        } catch (error) {
          if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            authFailure = error;
          } else {
            detectionError = error instanceof Error ? error.message : 'Field detection failed.';
          }
          debugLog('Field detection failed', error);
        }

        if (authFailure) {
          if (loadTokenRef.current !== loadToken) return;
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(authFailure.message);
          deps.setBannerNotice({ tone: 'error', message: authFailure.message, autoDismissMs: 8000 });
          return;
        }

        if (!detectedFields.length) {
          try {
            detectedFields = await extractFieldsFromPdf(doc);
            debugLog('Fallback PDF field extraction returned', { total: detectedFields.length });
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
          }
        }
        if (!detectedFields.length && detectionError && !detectionTimedOut) {
          deps.setBannerNotice({
            tone: 'error',
            message: `${detectionError} No embedded fields were found.`,
            autoDismissMs: 10000,
          });
        }
        if (detectionTimedOut) {
          deps.setBannerNotice({
            tone: 'info',
            message: 'Detection is still running on the backend. Using embedded form fields for now.',
            autoDismissMs: 8000,
          });
          if (detectedSessionId) {
            void resumeDetectionPolling(detectedSessionId, loadToken);
          }
        }

        if (!commitPdfLoad(doc, sizes, detectedFields, loadToken, pdfState)) return;
        setDetectSessionId(detectedSessionId);
        if (detectedSessionId) setMappingSessionId(detectedSessionId);
        debugLog('Loaded PDF', { name: file.name, pages: doc.numPages, fields: detectedFields.length });

        if (loadTokenRef.current !== loadToken) return;
        if (!options.autoRename && !options.autoMap) return;

        if (detectionTimedOut && detectedSessionId) {
          pendingAutoActionsRef.current = {
            loadToken, sessionId: detectedSessionId, schemaId: activeSchemaId,
            autoRename: Boolean(options.autoRename), autoMap: Boolean(options.autoMap),
          };
          deps.setBannerNotice({
            tone: 'info',
            message: 'Detection is still running. OpenAI actions will start once fields are ready.',
            autoDismissMs: 8000,
          });
          return;
        }
        if (!detectedFields.length) {
          deps.setBannerNotice({ tone: 'info', message: 'No fields detected. OpenAI actions were skipped.', autoDismissMs: 8000 });
          return;
        }

        if (options.autoRename && options.autoMap) {
          const renamed = await deps.runOpenAiRename({
            confirm: false, allowDefer: true, sessionId: detectedSessionId, schemaId: activeSchemaId,
          });
          if (renamed) deps.handleMappingSuccess();
          return;
        }
        if (options.autoRename) {
          await deps.runOpenAiRename({ confirm: false, allowDefer: true, sessionId: detectedSessionId });
        }
        if (options.autoMap) {
          const mapped = await deps.applySchemaMappings({ schemaIdOverride: activeSchemaId });
          if (mapped) deps.handleMappingSuccess();
        }
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        deps.clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        deps.setLoadError(message);
        debugLog('Failed to load PDF', message);
      } finally {
        clearWarmupTimers();
      }
    },
    [commitPdfLoad, resumeDetectionPolling, deps],
  );

  // ── Session keep-alive ────────────────────────────────────────────
  useEffect(() => {
    const sessionId = detectSessionId || mappingSessionId;
    const isDemoAsset = Boolean(deps.sourceFileIsDemo && deps.sourceFileName && DEMO_ASSET_NAME_SET.has(deps.sourceFileName));
    const { demoActive, demoCompletionOpen } = deps.demoStateRef.current;
    const demoSessionSuppressed = demoActive || demoCompletionOpen || isDemoAsset;
    if (!sessionId || !deps.verifiedUser || !deps.pdfDoc || demoSessionSuppressed) return;
    let cancelled = false;
    let intervalId: number | null = null;
    const intervalMs = 60_000;
    const reportExpired = () => {
      deps.setBannerNotice({ tone: 'info', message: 'This session expired. Re-upload the PDF to run Rename or Map again.', autoDismissMs: 8000 });
      setDetectSessionId(null); setMappingSessionId(null);
    };
    const ping = async () => {
      try { await ApiService.touchSession(sessionId); }
      catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) { reportExpired(); return; }
        debugLog('Failed to refresh session TTL', error);
      }
    };
    const start = () => { if (intervalId !== null) return; intervalId = window.setInterval(() => { if (!document.hidden) void ping(); }, intervalMs); void ping(); };
    const stop = () => { if (intervalId === null) return; window.clearInterval(intervalId); intervalId = null; };
    const handleVisibility = () => { if (document.hidden) stop(); else start(); };
    document.addEventListener('visibilitychange', handleVisibility);
    if (!document.hidden) start();
    return () => { cancelled = true; stop(); document.removeEventListener('visibilitychange', handleVisibility); };
  }, [deps.verifiedUser, deps.pdfDoc, deps.sourceFileIsDemo, deps.sourceFileName, deps.setBannerNotice, deps.demoStateRef, detectSessionId, mappingSessionId]);

  const reset = useCallback(() => {
    setProcessingMode(null);
    setMappingSessionId(null);
    setDetectSessionId(null);
    detectionRetryRef.current.clear();
  }, []);

  return {
    detectSessionId, setDetectSessionId,
    mappingSessionId, setMappingSessionId,
    isProcessing, setIsProcessing,
    processingMode, setProcessingMode,
    processingDetail,
    loadTokenRef,
    detectionRetryRef,
    pendingAutoActionsRef,
    commitPdfLoad,
    handleFillableUpload,
    handleSelectSavedForm,
    runDetectUpload,
    resumeDetectionPolling,
    scheduleDetectionRetry,
    reset,
  };
}
