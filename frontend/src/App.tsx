/**
 * App shell that orchestrates PDF detection, mapping, and viewer state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import './App.css';
import type {
  CheckboxHint,
  CheckboxRule,
  ConfidenceFilter,
  ConfidenceTier,
  FieldType,
  PageSize,
  PdfField,
} from './types';
import { createField, ensureUniqueFieldName, makeId } from './utils/fields';
import { fieldConfidenceTierForField, parseConfidence } from './utils/confidence';
import { parseCsv } from './utils/csv';
import { normaliseDataKey, pickIdentifierKey, type HeaderRename } from './utils/dataSource';
import { computeCheckboxMeta, type CheckboxMeta } from './utils/checkboxMeta';
import { parseJsonDataSource } from './utils/json';
import { inferSchemaFromRows, parseSchemaText } from './utils/schema';
import { parseExcel } from './utils/excel';
import { extractFieldsFromPdf, loadPageSizes, loadPdfFromFile } from './utils/pdf';
import { ALERT_MESSAGES, buildImportFileBeforeMapping } from './utils/alertMessages';
import { detectFields, fetchDetectionStatus, pollDetectionStatus } from './services/detectionApi';
import { Auth } from './services/auth';
import { setAuthToken } from './services/authTokenStore';
import { ApiError } from './services/apiConfig';
import { ApiService, type ProfileLimits, type UserProfile } from './api';
import Homepage from './components/pages/Homepage';
import LoginPage from './components/pages/LoginPage';
import ProfilePage from './components/pages/ProfilePage';
import VerifyEmailPage from './components/pages/VerifyEmailPage';
import { HeaderBar, type DataSourceKind } from './components/layout/HeaderBar';
import LegacyHeader from './components/layout/LegacyHeader';
import SearchFillModal from './components/features/SearchFillModal';
import { DemoTour, type DemoStep } from './components/demo/DemoTour';
import { FieldInspectorPanel } from './components/panels/FieldInspectorPanel';
import { FieldListPanel } from './components/panels/FieldListPanel';
import { PdfViewer } from './components/viewer/PdfViewer';
import UploadComponent from './components/features/UploadComponent';
import { Alert, type AlertTone } from './components/ui/Alert';
import { ConfirmDialog, PromptDialog, SavedFormsLimitDialog, type DialogTone } from './components/ui/Dialog';
import { CommonFormsAttribution } from './components/ui/CommonFormsAttribution';

const DEBUG_UI = false;
const MAX_FIELD_HISTORY = 10;
const SAVED_FORMS_RETRY_LIMIT = 3;
const SAVED_FORMS_RETRY_BASE_MS = 500;
const SAVED_FORMS_RETRY_MAX_MS = 4000;
const SAVED_FORMS_TIMEOUT_MS = 6000;
const AUTH_READY_FALLBACK_MS = 5000;
const DEMO_ASSETS = {
  rawPdf: 'new_patient_forms_1915ccb015.pdf',
  baseDetectionsPdf: 'baseFieldDetections.pdf',
  openAiRenamePdf: 'openAiRename.pdf',
  openAiRemapPdf: 'openAiRemap.pdf',
  csv: 'new_patient_forms_1915ccb015_mock.csv',
};
const DEMO_DISABLED_MESSAGE = 'Disabled during demo.';
const DEMO_STEPS: DemoStep[] = [
  {
    id: 'commonforms',
    title: (
      <>
        Field detection with <CommonFormsAttribution />
      </>
    ),
    body: 'The ML detector identifies candidate fields with confidence scores for review.',
    variant: 'modal',
  },
  {
    id: 'rename',
    title: 'OpenAI rename',
    body: 'Standardize names by sending the PDF to OpenAI.',
    targetSelector: '[data-demo-target="openai-rename"]',
    placement: 'bottom',
  },
  {
    id: 'csv',
    title: 'Connect the CSV database',
    body: 'Adding the mock CSV database for this form.',
    targetSelector: '[data-demo-target="data-source"]',
    placement: 'bottom',
  },
  {
    id: 'remap',
    title: 'OpenAI schema mapping',
    body: 'Mapping standardized field names to database column names.',
    targetSelector: '[data-demo-target="openai-remap"]',
    placement: 'bottom',
  },
  {
    id: 'search-fill',
    title: 'Search & Fill',
    body: 'Click Search to end the demo and fill Justin Thakral\'s information.',
    targetSelector: '[data-demo-target="search-fill-search"]',
    placement: 'right',
    showNext: false,
  },
];
const env = import.meta.env;
const PROCESSING_AD_VIDEO_URL =
  typeof env.VITE_PROCESSING_AD_VIDEO_URL === 'string' ? env.VITE_PROCESSING_AD_VIDEO_URL.trim() : '';
const PROCESSING_AD_POSTER_URL =
  typeof env.VITE_PROCESSING_AD_POSTER_URL === 'string' ? env.VITE_PROCESSING_AD_POSTER_URL.trim() : '';
const DEFAULT_PROCESSING_MESSAGE = 'Detecting fields and building the editor.';
const SAVED_FORM_PROCESSING_MESSAGE = 'Grabbing your template from the cloud.';
const FILLABLE_TEMPLATE_PROCESSING_MESSAGE = 'Opening template in editor.';
const QUEUE_WAIT_THRESHOLD_MS = 15000;
const DETECTION_BACKGROUND_POLL_TIMEOUT_MS = (() => {
  const raw = env.VITE_DETECTION_BACKGROUND_TIMEOUT_MS;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && parsed >= 0) {
    return parsed;
  }
  return 10 * 60 * 1000;
})();
const DETECTION_BACKGROUND_RETRY_BASE_MS = 5000;
const DETECTION_BACKGROUND_RETRY_MAX_MS = 30000;
const DETECTION_BACKGROUND_MAX_RETRIES = 5;
const DEFAULT_PROFILE_LIMITS: ProfileLimits = {
  detectMaxPages: 5,
  fillableMaxPages: 50,
  savedFormsMax: 3,
};

type ProcessingMode = 'detect' | 'fillable' | 'saved' | null;
type SchemaPayload = {
  name?: string;
  fields: Array<{ name: string; type?: string }>;
  source?: string;
  sampleCount?: number;
};
type PendingAutoActions = {
  loadToken: number;
  sessionId: string;
  schemaId: string | null;
  autoRename: boolean;
  autoMap: boolean;
};
type DemoSearchPreset = {
  query: string;
  searchKey?: string;
  searchMode?: 'contains' | 'equals';
  autoRun?: boolean;
  autoFillOnSearch?: boolean;
  highlightResult?: boolean;
  token: number;
};

/**
 * Conditional UI debug logger.
 */
function debugLog(...args: unknown[]) {
  if (!DEBUG_UI) return;
  console.log('[dullypdf-ui]', ...args);
}

/**
 * Normalize backend field types into UI field categories.
 */
function normaliseFieldType(raw: unknown): FieldType {
  const candidate = String(raw || '').toLowerCase();
  if (candidate === 'checkbox') return 'checkbox';
  if (candidate === 'signature') return 'signature';
  if (candidate === 'date') return 'date';
  return 'text';
}

/**
 * Coerce rect inputs into a consistent {x,y,width,height} shape.
 */
function rectToBox(rect: unknown): { x: number; y: number; width: number; height: number } | null {
  if (!rect) return null;
  if (Array.isArray(rect) && rect.length === 4) {
    const [x1, y1, x2, y2] = rect.map((value) => Number(value));
    if ([x1, y1, x2, y2].some((val) => Number.isNaN(val))) return null;
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
  }
  if (typeof rect === 'object') {
    const candidate = rect as { x?: number; y?: number; width?: number; height?: number };
    if (
      typeof candidate.x === 'number' &&
      typeof candidate.y === 'number' &&
      typeof candidate.width === 'number' &&
      typeof candidate.height === 'number'
    ) {
      return {
        x: candidate.x,
        y: candidate.y,
        width: candidate.width,
        height: candidate.height,
      };
    }
  }
  return null;
}

/**
 * Convert raw filenames into a display-friendly saved form name.
 */
function normaliseFormName(raw: string | null | undefined): string {
  const trimmed = String(raw || '').trim();
  if (!trimmed.length) return 'Saved form';
  return trimmed.replace(/\.pdf$/i, '');
}

/**
 * Estimate confidence for a rename mapping based on string similarity.
 */
function deriveMappingConfidence(originalName: string, nextName: string): number {
  const normalise = (value: string) =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  const left = normalise(originalName);
  const right = normalise(nextName);
  if (!left || !right) return 0.7;
  if (left === right) return 0.95;
  if (left.includes(right) || right.includes(left)) return 0.85;
  return 0.7;
}

/**
 * Normalize values so fillable PDFs receive consistent defaults.
 */
function normaliseFieldValueForMaterialize(field: PdfField): PdfField['value'] {
  const value = field.value;
  if (field.type === 'checkbox') {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string' && value.trim().length === 0) return false;
    return value;
  }
  if (value === null || value === undefined) return '';
  if (typeof value === 'string' && value.trim().length === 0) return '';
  return value;
}

/**
 * Apply value normalization across all fields before materialization.
 */
function prepareFieldsForMaterialize(fields: PdfField[]): PdfField[] {
  return fields.map((field) => {
    const value = normaliseFieldValueForMaterialize(field);
    return value === field.value ? field : { ...field, value };
  });
}

type FieldNameUpdate = {
  newName?: string;
  mappingConfidence?: unknown;
};

type NameQueue<T> = {
  entries: T[];
  index: number;
};

type BannerNotice = {
  tone: AlertTone;
  message: string;
  autoDismissMs?: number;
};

type ConfirmDialogOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
};

type PromptDialogOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
  defaultValue?: string;
  placeholder?: string;
  requireValue?: boolean;
};

type DialogRequest =
  | ({ kind: 'confirm' } & ConfirmDialogOptions)
  | ({ kind: 'prompt' } & PromptDialogOptions);

function enqueueByName<T>(queue: Map<string, NameQueue<T>>, key: string, entry: T) {
  const bucket = queue.get(key);
  if (bucket) {
    bucket.entries.push(entry);
    return;
  }
  queue.set(key, { entries: [entry], index: 0 });
}

function takeNextByName<T>(queue: Map<string, NameQueue<T>>, key: string): T | null {
  const bucket = queue.get(key);
  if (!bucket || bucket.index >= bucket.entries.length) return null;
  const entry = bucket.entries[bucket.index];
  bucket.index += 1;
  return entry ?? null;
}

/**
 * Apply rename updates while enforcing unique field names.
 */
function applyFieldNameUpdatesToList(
  fields: PdfField[],
  updatesByCurrentName: Map<string, NameQueue<FieldNameUpdate>>,
  checkboxMetaById?: Map<string, CheckboxMeta>,
): PdfField[] {
  if (!updatesByCurrentName.size) return fields;
  const existingNames = new Set(fields.map((field) => field.name));
  return fields.map((field) => {
    const update = takeNextByName(updatesByCurrentName, field.name);
    if (!update) return field;

    let next = field;
    const nextMappingConfidence = parseConfidence(update.mappingConfidence);
    if (nextMappingConfidence !== undefined && nextMappingConfidence !== field.mappingConfidence) {
      next = { ...next, mappingConfidence: nextMappingConfidence };
    }
    const checkboxMeta = checkboxMetaById?.get(field.id);
    if (
      field.type === 'checkbox' &&
      checkboxMeta &&
      (!field.groupKey || !field.optionKey)
    ) {
      const nextOptionLabel = checkboxMeta.optionLabel ?? field.optionLabel;
      if (
        next.groupKey !== checkboxMeta.groupKey ||
        next.optionKey !== checkboxMeta.optionKey ||
        next.optionLabel !== nextOptionLabel
      ) {
        next = {
          ...next,
          groupKey: checkboxMeta.groupKey,
          optionKey: checkboxMeta.optionKey,
          optionLabel: nextOptionLabel,
        };
      }
    }

    const desiredName = update.newName;
    if (!desiredName || desiredName === field.name) {
      return next;
    }

    existingNames.delete(field.name);
    const uniqueName = ensureUniqueFieldName(desiredName, existingNames);
    existingNames.add(uniqueName);

    if (uniqueName === next.name) {
      return next;
    }

    return { ...next, name: uniqueName };
  });
}

function resolveIdentifierKey(candidate: unknown, columns: string[]): string | null {
  if (!candidate || !columns.length) return null;
  const raw = String(candidate || '').trim();
  if (!raw) return null;
  if (columns.includes(raw)) return raw;
  const normalized = normaliseDataKey(raw);
  if (!normalized) return null;
  const match = columns.find((col) => normaliseDataKey(col) === normalized);
  return match ?? null;
}

/**
 * Convert backend detection payloads into client field models.
 */
function mapDetectionFields(payload: any): PdfField[] {
  const rawFields = Array.isArray(payload?.fields) ? payload.fields : [];
  return rawFields
    .map((field: any, index: number) => {
      const rect = rectToBox(field?.rect || field?.bbox);
      if (!rect) return null;
      const fieldConfidence = parseConfidence(field?.isItAfieldConfidence ?? field?.confidence);
      const renameConfidence = parseConfidence(field?.renameConfidence ?? field?.rename_confidence);
      return {
        id: makeId(),
        name: String(field?.name || `field_${index + 1}`),
        type: normaliseFieldType(field?.type),
        page: Number(field?.page) || 1,
        rect,
        fieldConfidence,
        renameConfidence,
        groupKey: field?.groupKey ?? field?.group_key,
        optionKey: field?.optionKey ?? field?.option_key,
        optionLabel: field?.optionLabel ?? field?.option_label,
        groupLabel: field?.groupLabel ?? field?.group_label,
      } as PdfField;
    })
    .filter(Boolean) as PdfField[];
}

function parseIsoTimestamp(value: unknown): number | null {
  if (typeof value !== 'string' || !value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function resolveDetectionStatusMessage(payload: any): string | null {
  const status = String(payload?.status || '').toLowerCase();
  if (!status) return null;
  const profile = String(payload?.detectionProfile || '').toLowerCase();
  const profileLabel =
    profile === 'heavy' ? 'high-capacity CPU' : profile === 'light' ? 'standard CPU' : 'CPU';
  if (status === 'queued') {
    const startedAt = parseIsoTimestamp(payload?.detectionStartedAt);
    if (!startedAt) {
      const queuedAt = parseIsoTimestamp(payload?.detectionQueuedAt);
      if (queuedAt && Date.now() - queuedAt > QUEUE_WAIT_THRESHOLD_MS) {
        return `Waiting for an available ${profileLabel}...`;
      }
      return `Waiting for ${profileLabel} to start...`;
    }
  }
  if (status === 'running') {
    return `Detecting fields on the ${profileLabel}...`;
  }
  return null;
}

/**
 * Main application component that coordinates auth, detection, and editing.
 */
function App() {
  const [authReady, setAuthReady] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authSignInProvider, setAuthSignInProvider] = useState<string | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [showHomepage, setShowHomepage] = useState(true);
  const [isMobileView, setIsMobileView] = useState(false);
  const [demoActive, setDemoActive] = useState(false);
  const [demoStepIndex, setDemoStepIndex] = useState<number | null>(null);
  const [demoCompletionOpen, setDemoCompletionOpen] = useState(false);
  const [demoSearchPreset, setDemoSearchPreset] = useState<DemoSearchPreset | null>(null);
  const detectionPipeline: 'commonforms' = 'commonforms';
  const [pendingDetectFile, setPendingDetectFile] = useState<File | null>(null);
  const [showPipelineModal, setShowPipelineModal] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [uploadWantsRename, setUploadWantsRename] = useState(false);
  const [uploadWantsMap, setUploadWantsMap] = useState(false);
  const [detectSessionId, setDetectSessionId] = useState<string | null>(null);

  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [pendingPageJump, setPendingPageJump] = useState<number | null>(null);
  const [fields, setFields] = useState<PdfField[]>([]);
  const [showFields, setShowFields] = useState(true);
  const [showFieldNames, setShowFieldNames] = useState(true);
  const [showFieldInfo, setShowFieldInfo] = useState(false);
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>({
    high: true,
    medium: true,
    low: true,
  });
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMode, setProcessingMode] = useState<ProcessingMode>(null);
  const [processingDetail, setProcessingDetail] = useState(DEFAULT_PROCESSING_MESSAGE);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showSavedFormsLimitDialog, setShowSavedFormsLimitDialog] = useState(false);
  const [savedForms, setSavedForms] = useState<Array<{ id: string; name: string; createdAt: string }>>([]);
  const [activeSavedFormId, setActiveSavedFormId] = useState<string | null>(null);
  const [activeSavedFormName, setActiveSavedFormName] = useState<string | null>(null);
  const [deletingFormId, setDeletingFormId] = useState<string | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<string | null>(null);
  const [mappingInProgress, setMappingInProgress] = useState(false);
  const [mapSchemaInProgress, setMapSchemaInProgress] = useState(false);
  const [hasMappedSchema, setHasMappedSchema] = useState(false);
  const [renameInProgress, setRenameInProgress] = useState(false);
  const [hasRenamedFields, setHasRenamedFields] = useState(false);
  const [checkboxRules, setCheckboxRules] = useState<CheckboxRule[]>([]);
  const [checkboxHints, setCheckboxHints] = useState<CheckboxHint[]>([]);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [openAiError, setOpenAiError] = useState<string | null>(null);
  const [bannerNotice, setBannerNotice] = useState<BannerNotice | null>(null);
  const [dialogRequest, setDialogRequest] = useState<DialogRequest | null>(null);
  const [schemaId, setSchemaId] = useState<string | null>(null);
  const [pendingSchemaPayload, setPendingSchemaPayload] = useState<SchemaPayload | null>(null);
  const [dataSourceKind, setDataSourceKind] = useState<DataSourceKind>('none');
  const [dataSourceLabel, setDataSourceLabel] = useState<string | null>(null);
  const [schemaUploadInProgress, setSchemaUploadInProgress] = useState(false);
  const [dataColumns, setDataColumns] = useState<string[]>([]);
  const [dataRows, setDataRows] = useState<Array<Record<string, unknown>>>([]);
  const [identifierKey, setIdentifierKey] = useState<string | null>(null);
  const [showSearchFill, setShowSearchFill] = useState(false);
  const [searchFillSessionId, setSearchFillSessionId] = useState(0);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceFileName, setSourceFileName] = useState<string | null>(null);
  const [sourceFileIsDemo, setSourceFileIsDemo] = useState(false);
  const [saveInProgress, setSaveInProgress] = useState(false);
  const [downloadInProgress, setDownloadInProgress] = useState(false);
  const loadTokenRef = useRef(0);
  const dialogResolverRef = useRef<((value: any) => void) | null>(null);
  const authUserRef = useRef<User | null>(null);
  const savedFormsRetryRef = useRef(0);
  const savedFormsRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveActionRef = useRef<(() => Promise<void>) | null>(null);
  const schemaPersistPromiseRef = useRef<Promise<string | null> | null>(null);
  const schemaPersistFingerprintRef = useRef<string | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const excelInputRef = useRef<HTMLInputElement>(null);
  const jsonInputRef = useRef<HTMLInputElement>(null);
  const txtInputRef = useRef<HTMLInputElement>(null);
  const demoAssetCacheRef = useRef<Map<string, File>>(new Map());
  const lastDemoStepRef = useRef<number | null>(null);
  const fieldsRef = useRef<PdfField[]>([]);
  const historyRef = useRef<{ undo: PdfField[][]; redo: PdfField[][] }>({ undo: [], redo: [] });
  const pendingHistoryRef = useRef<PdfField[] | null>(null);
  const pendingAutoActionsRef = useRef<PendingAutoActions | null>(null);
  const detectionRetryRef = useRef<Map<string, number>>(new Map());
  const resumeDetectionPollingRef = useRef<((sessionId: string, loadToken: number) => void) | null>(null);
  const [historyTick, setHistoryTick] = useState(0);
  const lastFieldVisibilityRef = useRef({ showFieldInfo, showFieldNames });
  const requiresEmailVerification = useMemo(
    () => Boolean(authUser && authSignInProvider === 'password' && !authUser.emailVerified),
    [authSignInProvider, authUser],
  );
  const verifiedUser = useMemo(
    () => (requiresEmailVerification ? null : authUser),
    [authUser, requiresEmailVerification],
  );
  const profileLimits = useMemo(
    () => userProfile?.limits ?? DEFAULT_PROFILE_LIMITS,
    [userProfile],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mediaQuery = window.matchMedia('(max-width: 1020px)');
    const update = () => setIsMobileView(mediaQuery.matches);
    update();
    if ('addEventListener' in mediaQuery) {
      mediaQuery.addEventListener('change', update);
      return () => mediaQuery.removeEventListener('change', update);
    }
    mediaQuery.addListener(update);
    return () => mediaQuery.removeListener(update);
  }, []);

  useEffect(() => {
    if (!isMobileView) return;
    if (showHomepage) return;
    if (pdfDoc || isProcessing) {
      if (!bannerNotice && !openAiError && !schemaError) {
        setBannerNotice({
          tone: 'info',
          message:
            'The editor works best on larger screens. If controls feel cramped, increase your window size.',
          autoDismissMs: 8000,
        });
      }
      return;
    }
    setShowHomepage(true);
  }, [bannerNotice, isMobileView, isProcessing, openAiError, pdfDoc, schemaError, showHomepage]);

  useEffect(() => {
    fieldsRef.current = fields;
  }, [fields]);

  useEffect(() => {
    if (!showFields) return;
    lastFieldVisibilityRef.current = { showFieldInfo, showFieldNames };
  }, [showFields, showFieldInfo, showFieldNames]);

  useEffect(() => {
    if (!demoActive && !demoCompletionOpen) return;
    const prevBodyOverflow = document.body.style.overflow;
    const prevHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prevBodyOverflow;
      document.documentElement.style.overflow = prevHtmlOverflow;
    };
  }, [demoActive, demoCompletionOpen]);

  useEffect(() => {
    authUserRef.current = verifiedUser;
  }, [verifiedUser]);

  useEffect(() => {
    return () => {
      if (!pdfDoc) return;
      void pdfDoc.destroy().catch((error) => {
        debugLog('Failed to release PDF document resources', error);
      });
    };
  }, [pdfDoc]);

  const clearSavedFormsRetry = useCallback(() => {
    if (savedFormsRetryTimerRef.current) {
      clearTimeout(savedFormsRetryTimerRef.current);
      savedFormsRetryTimerRef.current = null;
    }
    savedFormsRetryRef.current = 0;
  }, []);

  const refreshSavedForms = useCallback(
    async (options?: { allowRetry?: boolean }) => {
      const currentUser = authUserRef.current;
      if (!currentUser) return;
      try {
        const forms = await ApiService.getSavedForms({
          suppressErrors: false,
          timeoutMs: SAVED_FORMS_TIMEOUT_MS,
        });
        setSavedForms(forms || []);
        clearSavedFormsRetry();
      } catch (error) {
        if (!options?.allowRetry || !(error instanceof TypeError)) {
          debugLog('Failed to load saved forms', error);
          return;
        }
        const attempt = savedFormsRetryRef.current + 1;
        if (attempt > SAVED_FORMS_RETRY_LIMIT) {
          debugLog('Saved forms retry limit reached', error);
          return;
        }
        savedFormsRetryRef.current = attempt;
        const delay = Math.min(
          SAVED_FORMS_RETRY_MAX_MS,
          SAVED_FORMS_RETRY_BASE_MS * 2 ** (attempt - 1),
        );
        if (savedFormsRetryTimerRef.current) {
          clearTimeout(savedFormsRetryTimerRef.current);
        }
        savedFormsRetryTimerRef.current = setTimeout(() => {
          void refreshSavedForms(options);
        }, delay);
      }
    },
    [clearSavedFormsRetry],
  );

  const loadUserProfile = useCallback(async () => {
    if (!authUserRef.current) return null;
    setProfileLoading(true);
    try {
      const profile = await ApiService.getProfile();
      setUserProfile(profile);
      return profile;
    } catch (error) {
      debugLog('Failed to load profile', error);
      setUserProfile(null);
      return null;
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const syncAuthSession = useCallback(
    async (user: User | null, options?: { forceTokenRefresh?: boolean; deferSavedForms?: boolean }) => {
      authUserRef.current = null;
      setAuthUser(user);
      setAuthSignInProvider(null);

      if (!user) {
        clearSavedFormsRetry();
        setSavedForms([]);
        setUserProfile(null);
        setShowProfile(false);
        return;
      }

      try {
        const tokenResult = await user.getIdTokenResult(options?.forceTokenRefresh ?? true);
        setAuthToken(tokenResult.token);
        const provider =
          tokenResult.signInProvider ??
          (user.providerData.length === 1 ? user.providerData[0]?.providerId ?? null : null);
        setAuthSignInProvider(provider);
        const needsVerification = provider === 'password' && !user.emailVerified;
        if (needsVerification) {
          clearSavedFormsRetry();
          setSavedForms([]);
          setUserProfile(null);
          setShowProfile(false);
          return;
        }
        authUserRef.current = user;
        if (options?.deferSavedForms) {
          void refreshSavedForms({ allowRetry: true });
          void loadUserProfile();
        } else {
          await refreshSavedForms({ allowRetry: true });
          await loadUserProfile();
        }
      } catch (error) {
        console.error('Failed to initialize session', error);
      }
    },
    [clearSavedFormsRetry, loadUserProfile, refreshSavedForms],
  );

  useEffect(() => {
    let isActive = true;
    const markReady = () => {
      if (!isActive) return;
      setAuthReady(true);
    };
    const readyTimer = setTimeout(markReady, AUTH_READY_FALLBACK_MS);
    const unsubscribe = Auth.onAuthStateChanged(async (user) => {
      await syncAuthSession(user, { forceTokenRefresh: true, deferSavedForms: true });
      markReady();
    });
    return () => {
      isActive = false;
      clearTimeout(readyTimer);
      clearSavedFormsRetry();
      unsubscribe();
    };
  }, [clearSavedFormsRetry, syncAuthSession]);

  useEffect(() => {
    if (openAiError || schemaError) {
      setBannerNotice(null);
    }
  }, [openAiError, schemaError]);

  useEffect(() => {
    if (!bannerNotice?.autoDismissMs) return undefined;
    const timer = setTimeout(() => setBannerNotice(null), bannerNotice.autoDismissMs);
    return () => clearTimeout(timer);
  }, [bannerNotice]);

  useEffect(() => {
    if (!showProfile || !verifiedUser) return;
    void loadUserProfile();
  }, [loadUserProfile, showProfile, verifiedUser]);

  const pushFieldHistory = useCallback((snapshot: PdfField[]) => {
    const history = historyRef.current;
    history.undo = [...history.undo, snapshot].slice(-MAX_FIELD_HISTORY);
    history.redo = [];
    setHistoryTick((prev) => prev + 1);
  }, []);

  const resetFieldHistory = useCallback((nextFields: PdfField[] = []) => {
    historyRef.current.undo = [];
    historyRef.current.redo = [];
    pendingHistoryRef.current = null;
    fieldsRef.current = nextFields;
    setFields(nextFields);
    setHistoryTick((prev) => prev + 1);
  }, []);

  const clearPendingAutoActions = useCallback(() => {
    pendingAutoActionsRef.current = null;
  }, []);

  const updateFields = useCallback(
    (nextFields: PdfField[], options?: { trackHistory?: boolean }) => {
      const prev = fieldsRef.current;
      if (nextFields === prev) return;
      if (options?.trackHistory !== false) {
        pushFieldHistory(prev);
      }
      fieldsRef.current = nextFields;
      setFields(nextFields);
    },
    [pushFieldHistory],
  );

  const updateFieldsWith = useCallback(
    (updater: (prev: PdfField[]) => PdfField[], options?: { trackHistory?: boolean }) => {
      const prev = fieldsRef.current;
      const next = updater(prev);
      updateFields(next, options);
    },
    [updateFields],
  );

  const beginFieldHistory = useCallback(() => {
    if (!pendingHistoryRef.current) {
      pendingHistoryRef.current = fieldsRef.current;
    }
  }, []);

  const commitFieldHistory = useCallback(() => {
    const pending = pendingHistoryRef.current;
    if (!pending) return;
    pendingHistoryRef.current = null;
    if (pending === fieldsRef.current) return;
    pushFieldHistory(pending);
  }, [pushFieldHistory]);

  const handleUndo = useCallback(() => {
    commitFieldHistory();
    const history = historyRef.current;
    if (!history.undo.length) return;
    const previous = history.undo[history.undo.length - 1];
    history.undo = history.undo.slice(0, -1);
    history.redo = [...history.redo, fieldsRef.current].slice(-MAX_FIELD_HISTORY);
    pendingHistoryRef.current = null;
    fieldsRef.current = previous;
    setFields(previous);
    setHistoryTick((prev) => prev + 1);
    setSelectedFieldId((currentId) =>
      currentId && previous.some((field) => field.id === currentId) ? currentId : null,
    );
  }, [commitFieldHistory]);

  const handleRedo = useCallback(() => {
    commitFieldHistory();
    const history = historyRef.current;
    if (!history.redo.length) return;
    const next = history.redo[history.redo.length - 1];
    history.redo = history.redo.slice(0, -1);
    history.undo = [...history.undo, fieldsRef.current].slice(-MAX_FIELD_HISTORY);
    pendingHistoryRef.current = null;
    fieldsRef.current = next;
    setFields(next);
    setHistoryTick((prev) => prev + 1);
    setSelectedFieldId((currentId) =>
      currentId && next.some((field) => field.id === currentId) ? currentId : null,
    );
  }, [commitFieldHistory]);

  const clearWorkspace = useCallback(() => {
    setPdfDoc(null);
    setPageSizes({});
    setPageCount(0);
    setCurrentPage(1);
    setScale(1);
    setPendingPageJump(null);
    resetFieldHistory([]);
    setShowFields(true);
    setShowFieldNames(true);
    setShowFieldInfo(false);
    setConfidenceFilter({ high: true, medium: true, low: true });
    setSelectedFieldId(null);
    setProcessingMode(null);
    setMappingSessionId(null);
    setMappingInProgress(false);
    setHasMappedSchema(false);
    setCheckboxRules([]);
    setCheckboxHints([]);
    setSchemaError(null);
    setSchemaId(null);
    setPendingSchemaPayload(null);
    setDataSourceKind('none');
    setDataSourceLabel(null);
    setSchemaUploadInProgress(false);
    setDataColumns([]);
    setDataRows([]);
    setIdentifierKey(null);
    setShowSearchFill(false);
    setSearchFillSessionId((prev) => prev + 1);
    setSourceFile(null);
    setSourceFileName(null);
    setSourceFileIsDemo(false);
    setSaveInProgress(false);
    setActiveSavedFormId(null);
    setActiveSavedFormName(null);
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    pendingSaveActionRef.current = null;
    setShowSavedFormsLimitDialog(false);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
    setDetectSessionId(null);
    setRenameInProgress(false);
    setHasRenamedFields(false);
    setOpenAiError(null);
    setBannerNotice(null);
    detectionRetryRef.current.clear();
    if (dialogResolverRef.current) {
      const fallback =
        dialogRequest?.kind === 'confirm'
          ? false
          : dialogRequest?.kind === 'prompt'
            ? null
            : null;
      dialogResolverRef.current(fallback);
    }
    dialogResolverRef.current = null;
    setDialogRequest(null);
  }, [dialogRequest, resetFieldHistory]);

  const resolveDialog = useCallback((value: any) => {
    const resolver = dialogResolverRef.current;
    dialogResolverRef.current = null;
    setDialogRequest(null);
    if (resolver) {
      resolver(value);
    }
  }, []);

  const requestConfirm = useCallback((options: ConfirmDialogOptions) => {
    return new Promise<boolean>((resolve) => {
      dialogResolverRef.current = resolve;
      setDialogRequest({ kind: 'confirm', ...options });
    });
  }, []);

  const requestPrompt = useCallback((options: PromptDialogOptions) => {
    return new Promise<string | null>((resolve) => {
      dialogResolverRef.current = resolve;
      setDialogRequest({ kind: 'prompt', ...options });
    });
  }, []);

  const queueSaveAfterLimit = useCallback(
    (action: () => Promise<void>) => {
      pendingSaveActionRef.current = action;
      setShowSavedFormsLimitDialog(true);
      void refreshSavedForms({ allowRetry: true });
    },
    [refreshSavedForms],
  );

  const closeSavedFormsLimitDialog = useCallback(() => {
    pendingSaveActionRef.current = null;
    setShowSavedFormsLimitDialog(false);
  }, []);

  const handleSignOut = useCallback(async () => {
    await Auth.signOut();
    clearWorkspace();
    setSavedForms([]);
    setShowHomepage(true);
    setShowProfile(false);
    setDemoActive(false);
    setDemoStepIndex(null);
    setDemoCompletionOpen(false);
    setDemoSearchPreset(null);
  }, [clearWorkspace]);

  const handleNavigateHome = useCallback(() => {
    clearWorkspace();
    setLoadError(null);
    setShowHomepage(true);
    setDemoActive(false);
    setDemoStepIndex(null);
    setDemoCompletionOpen(false);
    setDemoSearchPreset(null);
  }, [clearWorkspace]);

  const handleOpenProfile = useCallback(() => {
    if (!verifiedUser) return;
    setShowProfile(true);
  }, [verifiedUser]);

  const handleCloseProfile = useCallback(() => {
    setShowProfile(false);
  }, []);

  const handleRefreshVerification = useCallback(async () => {
    const user = await Auth.refreshCurrentUser();
    await syncAuthSession(user, { forceTokenRefresh: true });
  }, [syncAuthSession]);

  const buildTemplateFields = useCallback(
    (sourceFields: PdfField[]) =>
      sourceFields.map((field) => ({
        name: field.name,
        type: field.type,
        page: field.page,
        rect: field.rect,
        groupKey: field.groupKey,
        optionKey: field.optionKey,
        optionLabel: field.optionLabel,
        groupLabel: field.groupLabel,
      })),
    [],
  );

  const commitPdfLoad = useCallback(
    (
      doc: PDFDocumentProxy,
      sizes: Record<number, PageSize>,
      initialFields: PdfField[],
      loadToken: number,
    ) => {
      if (loadTokenRef.current !== loadToken) return false;
      setPdfDoc(doc);
      setPageSizes(sizes);
      setPageCount(doc.numPages);
      setCurrentPage(1);
      setScale(1);
      setPendingPageJump(null);
      resetFieldHistory(initialFields);
      setSelectedFieldId(null);
      setIsProcessing(false);
      setProcessingMode(null);
      return true;
    },
    [resetFieldHistory],
  );

  const handleFillableUpload = useCallback(
    async (file: File, options: { isDemo?: boolean } = {}) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      setShowSearchFill(false);
      setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('fillable');
      setIsProcessing(true);
      setProcessingDetail(FILLABLE_TEMPLATE_PROCESSING_MESSAGE);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      setHasRenamedFields(false);
      setHasMappedSchema(false);
      setCheckboxRules([]);
      setCheckboxHints([]);
      setSchemaError(null);
      setOpenAiError(null);
      setSourceFile(file);
      setSourceFileName(file.name);
      setSourceFileIsDemo(Boolean(options.isDemo));
      setActiveSavedFormId(null);
      setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > profileLimits.fillableMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          setLoadError(
            `Fillable uploads are limited to ${profileLimits.fillableMaxPages} pages on your plan.`,
          );
          return;
        }
        const sizesPromise = loadPageSizes(doc);
        const existingFieldsPromise = (async () => {
          try {
            return await extractFieldsFromPdf(doc);
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
            return [];
          }
        })();
        const sizes = await sizesPromise;
        if (!commitPdfLoad(doc, sizes, [], loadToken)) return;

        void (async () => {
          const existingFields = await existingFieldsPromise;
          if (loadTokenRef.current !== loadToken) return;
          resetFieldHistory(existingFields);
          setSelectedFieldId(null);
          debugLog('Extracted existing PDF fields', { total: existingFields.length });
          debugLog('Loaded fillable PDF', { name: file.name, pages: doc.numPages, fields: existingFields.length });
          if (!existingFields.length) {
            return;
          }
          if (!verifiedUser) {
            return;
          }
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
            setBannerNotice({
              tone: 'info',
              message: 'Rename is unavailable for this template.',
              autoDismissMs: 8000,
            });
            debugLog('Failed to register template session', error);
          }
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [
      buildTemplateFields,
      clearWorkspace,
      commitPdfLoad,
      profileLimits.fillableMaxPages,
      resetFieldHistory,
      verifiedUser,
    ],
  );

  const handleSelectSavedForm = useCallback(
    async (formId: string) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      setShowSearchFill(false);
      setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('saved');
      setIsProcessing(true);
      setProcessingDetail(SAVED_FORM_PROCESSING_MESSAGE);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      setHasRenamedFields(false);
      setHasMappedSchema(false);
      setSchemaError(null);
      setOpenAiError(null);

      try {
        const [savedMeta, blob] = await Promise.all([
          ApiService.loadSavedForm(formId),
          ApiService.downloadSavedForm(formId),
        ]);
        const name = savedMeta?.name || 'saved-form.pdf';
        const file = new File([blob], name, { type: 'application/pdf' });
        setSourceFile(file);
        setSourceFileName(name);
        setSourceFileIsDemo(false);
        const doc = await loadPdfFromFile(file);
        const sizesPromise = loadPageSizes(doc);
        const existingFieldsPromise = (async () => {
          try {
            return await extractFieldsFromPdf(doc);
          } catch (error) {
            debugLog('Failed to extract saved form fields', error);
            return [];
          }
        })();
        const sizes = await sizesPromise;
        if (!commitPdfLoad(doc, sizes, [], loadToken)) return;
        setActiveSavedFormId(formId);
        setActiveSavedFormName(savedMeta?.name || null);
        const savedCheckboxRules = Array.isArray(savedMeta?.checkboxRules) ? savedMeta.checkboxRules : [];
        const savedCheckboxHints = Array.isArray(savedMeta?.checkboxHints) ? savedMeta.checkboxHints : [];
        setCheckboxRules(savedCheckboxRules);
        setCheckboxHints(savedCheckboxHints);

        void (async () => {
          const existingFields = await existingFieldsPromise;
          if (loadTokenRef.current !== loadToken) return;
          resetFieldHistory(existingFields);
          setSelectedFieldId(null);
          debugLog('Extracted saved form fields', { total: existingFields.length });
          debugLog('Loaded saved form', { name, pages: doc.numPages, fields: existingFields.length });
          if (!existingFields.length) {
            setBannerNotice({
              tone: 'info',
              message: 'No fields found in this saved form. Rename is unavailable.',
              autoDismissMs: 8000,
            });
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
            setBannerNotice({
              tone: 'info',
              message: 'Rename is unavailable for this saved form.',
              autoDismissMs: 8000,
            });
            debugLog('Failed to register saved form session', error);
          }
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load saved form.';
        clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        setLoadError(message);
        debugLog('Failed to load saved form', message);
      }
    },
    [buildTemplateFields, clearWorkspace, commitPdfLoad, resetFieldHistory, setBannerNotice],
  );

  const handleSelectSavedFormFromProfile = useCallback(
    (formId: string) => {
      setShowProfile(false);
      void handleSelectSavedForm(formId);
    },
    [handleSelectSavedForm],
  );

  const deleteSavedFormById = useCallback(
    async (formId: string): Promise<boolean> => {
      setDeletingFormId(formId);
      try {
        await ApiService.deleteSavedForm(formId);
        setSavedForms((prev) => prev.filter((form) => form.id !== formId));
        if (formId === activeSavedFormId) {
          setActiveSavedFormId(null);
          setActiveSavedFormName(null);
        }
        return true;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to delete saved form.';
        setBannerNotice({ tone: 'error', message });
        debugLog('Failed to delete saved form', message);
        return false;
      } finally {
        setDeletingFormId(null);
      }
    },
    [activeSavedFormId, setBannerNotice],
  );

  const handleDeleteSavedForm = useCallback(
    async (formId: string) => {
      const target = savedForms.find((form) => form.id === formId);
      const name = target?.name ? `"${target.name}"` : 'this saved form';
      const confirmDelete = await requestConfirm({
        title: 'Delete saved form?',
        message: `Delete ${name}? This removes it from your saved forms.`,
        confirmLabel: 'Delete',
        cancelLabel: 'Cancel',
        tone: 'danger',
      });
      if (!confirmDelete) return;

      await deleteSavedFormById(formId);
    },
    [deleteSavedFormById, requestConfirm, savedForms],
  );

  const handleSavedFormsLimitDelete = useCallback(
    async (formId: string) => {
      const removed = await deleteSavedFormById(formId);
      if (!removed) return;
      const pendingAction = pendingSaveActionRef.current;
      if (!pendingAction) return;
      pendingSaveActionRef.current = null;
      setShowSavedFormsLimitDialog(false);
      await pendingAction();
    },
    [deleteSavedFormById],
  );

  const saveFormToProfile = useCallback(
    async ({
      saveName,
      overwriteFormId,
    }: {
      saveName: string;
      overwriteFormId?: string | null;
    }): Promise<{ success: boolean; limitReached: boolean }> => {
      if (!pdfDoc) {
        setBannerNotice({ tone: 'error', message: 'No PDF is loaded to save.' });
        return { success: false, limitReached: false };
      }
      setSaveInProgress(true);
      try {
        let blob: Blob;
        if (sourceFile) {
          blob = sourceFile;
        } else {
          const data = await pdfDoc.getData();
          blob = new Blob([new Uint8Array(data)], { type: 'application/pdf' });
        }
        const fieldsForSave = prepareFieldsForMaterialize(fields);
        const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForSave);
        const rulesForSave = checkboxRules.length ? checkboxRules : undefined;
        const hintsForSave = checkboxHints.length ? checkboxHints : undefined;
        const payload = await ApiService.saveFormToProfile(
          generatedBlob,
          saveName,
          mappingSessionId || undefined,
          overwriteFormId || undefined,
          rulesForSave,
          hintsForSave,
        );
        setActiveSavedFormId(payload?.id || null);
        setActiveSavedFormName(payload?.name || saveName);
        await refreshSavedForms();
        return { success: true, limitReached: false };
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to save form to profile.';
        const limitReached =
          error instanceof ApiError && error.status === 403 && message.toLowerCase().includes('saved form limit');
        if (!limitReached) {
          setBannerNotice({ tone: 'error', message });
        }
        debugLog('Failed to save form', message);
        return { success: false, limitReached };
      } finally {
        setSaveInProgress(false);
      }
    },
    [checkboxHints, checkboxRules, fields, mappingSessionId, pdfDoc, refreshSavedForms, setBannerNotice, sourceFile],
  );

  const handleSaveToProfile = useCallback(async () => {
    if (!pdfDoc) {
      setBannerNotice({ tone: 'error', message: 'No PDF is loaded to save.' });
      return;
    }
    if (!verifiedUser) {
      setBannerNotice({ tone: 'error', message: 'Sign in to save this form to your profile.' });
      return;
    }
    const maxSavedForms = profileLimits.savedFormsMax;
    const savedFormsLimitReached = savedForms.length >= maxSavedForms;
    setLoadError(null);
    const defaultName = normaliseFormName(activeSavedFormName || sourceFileName || sourceFile?.name);
    const promptForName = async ({ forceSave = false }: { forceSave?: boolean } = {}) => {
      const raw = await requestPrompt({
        title: 'Name this saved form',
        message: 'Enter a name to store this PDF in your saved forms list.',
        defaultValue: defaultName,
        placeholder: 'Saved form name',
        confirmLabel: 'Save',
        cancelLabel: 'Cancel',
        requireValue: true,
      });
      if (raw === null) {
        return forceSave ? defaultName : null;
      }
      const trimmed = raw.trim();
      if (!trimmed) {
        if (forceSave) {
          return defaultName;
        }
        setBannerNotice({ tone: 'error', message: 'A form name is required to save.' });
        return null;
      }
      return normaliseFormName(trimmed);
    };

    const attemptSaveNew = async ({ forceSave = false }: { forceSave?: boolean } = {}) => {
      const nextName = await promptForName({ forceSave });
      if (!nextName) return;
      const result = await saveFormToProfile({ saveName: nextName });
      if (!result.success && result.limitReached) {
        queueSaveAfterLimit(() => attemptSaveNew({ forceSave: true }));
      }
    };

    let shouldOverwrite = false;
    if (activeSavedFormId) {
      const overwrite = await requestConfirm({
        title: 'Overwrite saved form?',
        message: 'This form is already saved. Overwrite it or save a new copy with a different name.',
        confirmLabel: 'Overwrite',
        cancelLabel: 'Save new copy',
        tone: 'danger',
      });
      if (overwrite) {
        shouldOverwrite = true;
      } else {
        if (savedFormsLimitReached) {
          queueSaveAfterLimit(() => attemptSaveNew({ forceSave: true }));
          return;
        }
        await attemptSaveNew();
        return;
      }
    } else {
      if (savedFormsLimitReached) {
        queueSaveAfterLimit(() => attemptSaveNew({ forceSave: true }));
        return;
      }
      await attemptSaveNew();
      return;
    }
    if (shouldOverwrite) {
      const result = await saveFormToProfile({ saveName: defaultName, overwriteFormId: activeSavedFormId });
      if (!result.success && result.limitReached) {
        setBannerNotice({ tone: 'error', message: 'Unable to overwrite saved form at the current limit.' });
      }
    }
  }, [
    activeSavedFormId,
    activeSavedFormName,
    pdfDoc,
    sourceFile,
    sourceFileName,
    profileLimits.savedFormsMax,
    verifiedUser,
    requestConfirm,
    requestPrompt,
    savedForms.length,
    setBannerNotice,
    queueSaveAfterLimit,
    saveFormToProfile,
  ]);

  const handleDownload = useCallback(async () => {
    if (!pdfDoc) {
      setLoadError('No PDF is loaded to download.');
      return;
    }
    if (!verifiedUser) {
      setLoadError('Sign in to download this form.');
      return;
    }
    setLoadError(null);
    setDownloadInProgress(true);
    try {
      let blob: Blob;
      if (sourceFile) {
        blob = sourceFile;
      } else {
        const data = await pdfDoc.getData();
        blob = new Blob([new Uint8Array(data)], { type: 'application/pdf' });
      }
      const fieldsForDownload = prepareFieldsForMaterialize(fields);
      const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForDownload);
      const baseName = normaliseFormName(activeSavedFormName || sourceFileName || sourceFile?.name);
      const filename = `${baseName}-fillable.pdf`;
      const url = URL.createObjectURL(generatedBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to download form.';
      setLoadError(message);
      debugLog('Failed to download form', message);
    } finally {
      setDownloadInProgress(false);
    }
  }, [activeSavedFormName, fields, pdfDoc, sourceFile, sourceFileName, verifiedUser]);

  const applyFieldNameUpdates = useCallback(
    (
      updatesByCurrentName: Map<string, NameQueue<FieldNameUpdate>>,
      checkboxMetaById?: Map<string, CheckboxMeta>,
    ) => {
      if (!updatesByCurrentName.size) return;
      updateFieldsWith((prev) => applyFieldNameUpdatesToList(prev, updatesByCurrentName, checkboxMetaById));
    },
    [updateFieldsWith],
  );

  const applyMappingResults = useCallback(
    (mappingResults?: any) => {
      if (!mappingResults) return;
      const mappings = mappingResults.mappings || [];
      const updates = new Map<string, NameQueue<FieldNameUpdate>>();
      const normalizedColumns = dataColumns.map((column) => normaliseDataKey(column)).filter(Boolean);
      const checkboxMetaById = computeCheckboxMeta(fieldsRef.current, normalizedColumns);

      for (const mapping of mappings) {
        if (!mapping || !mapping.pdfField) continue;
        const currentName = mapping.originalPdfField || mapping.pdfField;
        const desiredName = mapping.pdfField;
        if (!currentName) continue;
        const mappingConfidence =
          parseConfidence(mapping.confidence) ?? deriveMappingConfidence(currentName, desiredName);
        enqueueByName(updates, currentName, { newName: desiredName, mappingConfidence });
      }

      if (updates.size) {
        applyFieldNameUpdates(updates, checkboxMetaById);
        debugLog('Applied AI mappings', { total: updates.size });
      }

      const rules = Array.isArray(mappingResults.checkboxRules) ? mappingResults.checkboxRules : [];
      setCheckboxRules(rules);
      const hints = Array.isArray(mappingResults.checkboxHints) ? mappingResults.checkboxHints : [];
      setCheckboxHints(hints);
      const resolvedIdentifier = resolveIdentifierKey(
        mappingResults.identifierKey || mappingResults.identifier_key,
        dataColumns,
      );
      if (resolvedIdentifier) {
        setIdentifierKey(resolvedIdentifier);
      }
    },
    [applyFieldNameUpdates, dataColumns],
  );

  const applyRenameResults = useCallback(
    (renamedFieldsPayload?: Array<Record<string, any>>): PdfField[] | null => {
      if (!Array.isArray(renamedFieldsPayload) || !renamedFieldsPayload.length) return null;
      const renamesByOriginal = new Map<string, NameQueue<Record<string, any>>>();
      for (const entry of renamedFieldsPayload) {
        const original =
          entry.originalName || entry.original_name || entry.originalFieldName || entry.name;
        if (typeof original === 'string' && original.trim()) {
          enqueueByName(renamesByOriginal, original.trim(), entry);
        }
      }

      if (!renamesByOriginal.size) return null;

      const updated: PdfField[] = [];
      for (const field of fieldsRef.current) {
        const rename = takeNextByName(renamesByOriginal, field.name);
        if (!rename) {
          updated.push(field);
          continue;
        }
        const renameConfidence = parseConfidence(rename.renameConfidence ?? rename.rename_confidence);
        const fieldConfidence = parseConfidence(
          rename.isItAfieldConfidence ?? rename.is_it_a_field_confidence,
        );
        const hasMappingConfidence =
          Object.prototype.hasOwnProperty.call(rename, 'mappingConfidence') ||
          Object.prototype.hasOwnProperty.call(rename, 'mapping_confidence');
        const mappingConfidence = parseConfidence(
          rename.mappingConfidence ?? rename.mapping_confidence,
        );
        const nextName = String(rename.name || rename.suggestedRename || field.name).trim() || field.name;
        updated.push({
          ...field,
          name: nextName,
          mappingConfidence: hasMappingConfidence ? mappingConfidence : field.mappingConfidence,
          renameConfidence: renameConfidence ?? field.renameConfidence,
          fieldConfidence: fieldConfidence ?? field.fieldConfidence,
          groupKey: rename.groupKey ?? field.groupKey,
          optionKey: rename.optionKey ?? field.optionKey,
          optionLabel: rename.optionLabel ?? field.optionLabel,
          groupLabel: rename.groupLabel ?? field.groupLabel,
        });
      }
      resetFieldHistory(updated);
      setSelectedFieldId(null);
      return updated;
    },
    [resetFieldHistory],
  );

  const applySchemaMappings = useCallback(
    async ({
      fieldsOverride,
      schemaIdOverride,
    }: { fieldsOverride?: PdfField[]; schemaIdOverride?: string | null } = {}): Promise<boolean> => {
      if (!verifiedUser) {
        setSchemaError(ALERT_MESSAGES.signInToRunSchemaMapping);
        return false;
      }
      clearPendingAutoActions();
      const activeSchemaId = schemaIdOverride ?? schemaId;
      if (!activeSchemaId) {
        setSchemaError(ALERT_MESSAGES.schemaRequiredForMapping);
        return false;
      }
      const activeFields = fieldsOverride ?? fieldsRef.current;
      if (!activeFields.length) {
        setSchemaError(ALERT_MESSAGES.noPdfFieldsToMap);
        return false;
      }
      if (!detectSessionId && !activeSavedFormId) {
        setSchemaError('Template session is not ready yet. Try again in a moment.');
        return false;
      }

      setSchemaError(null);
      try {
        const mappingLoadToken = loadTokenRef.current;
        const templateFields = buildTemplateFields(activeFields);
        const mappingResult = await ApiService.mapSchema(
          activeSchemaId,
          templateFields,
          activeSavedFormId || undefined,
          detectSessionId || undefined,
        );
        if (loadTokenRef.current !== mappingLoadToken) {
          return false;
        }
        if (!mappingResult?.success) {
          throw new Error(mappingResult?.error || 'Mapping generation failed');
        }
        applyMappingResults(mappingResult.mappingResults);
        return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Schema mapping failed.';
      setSchemaError(message);
      debugLog('Schema mapping failed', message);
      return false;
    }
    },
    [
      activeSavedFormId,
      applyMappingResults,
      verifiedUser,
      buildTemplateFields,
      clearPendingAutoActions,
      detectSessionId,
      schemaId,
    ],
  );

  const handleMappingSuccess = useCallback(() => {
    setHasMappedSchema(true);
    setBannerNotice({
      tone: 'success',
      message: ALERT_MESSAGES.mappingDone,
      autoDismissMs: 5000,
    });
  }, []);

  const runOpenAiRename = useCallback(
    async ({
      confirm = true,
      allowDefer = false,
      sessionId,
      schemaId: renameSchemaId,
    }: {
      confirm?: boolean;
      allowDefer?: boolean;
      sessionId?: string | null;
      schemaId?: string | null;
    } = {}): Promise<PdfField[] | null> => {
      if (!verifiedUser) {
        setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRename);
        return null;
      }
      clearPendingAutoActions();
      const activeSessionId = sessionId || detectSessionId;
      if (!activeSessionId) {
        setOpenAiError(ALERT_MESSAGES.uploadPdfForRename);
        return null;
      }
      if (!fieldsRef.current.length) {
        if (allowDefer) {
          try {
            const statusPayload = await fetchDetectionStatus(activeSessionId);
            const status = String(statusPayload?.status || '').toLowerCase();
            if (status === 'queued' || status === 'running') {
              pendingAutoActionsRef.current = {
                loadToken: loadTokenRef.current,
                sessionId: activeSessionId,
                schemaId: renameSchemaId,
                autoRename: true,
                autoMap: Boolean(renameSchemaId),
              };
              setBannerNotice({
                tone: 'info',
                message: 'Detection is still running. Rename will start once fields are ready.',
                autoDismissMs: 8000,
              });
              return null;
            }
          } catch (error) {
            debugLog('Failed to fetch detection status for rename', error);
          }
        }
        setOpenAiError(ALERT_MESSAGES.noPdfFieldsToRename);
        return null;
      }
      const hasSchemaForMap = Boolean(renameSchemaId);
      if (confirm) {
        const ok = await requestConfirm({
          title: 'Send to OpenAI?',
          message: (
            <>
              This PDF and its field tags will be sent to OpenAI. No row data or field values are sent.
              {!hasSchemaForMap ? (
                <>
                  <br />
                  <br />
                  A base rename without a Map schema in the same step does not align to database columns. Explicit
                  yes/no checkbox columns will only fill if names already match, and complex checkbox groups will fail.
                </>
              ) : null}
            </>
          ),
          confirmLabel: 'Continue',
          cancelLabel: 'Cancel',
        });
        if (!ok) return null;
      }
      setOpenAiError(null);
      setMappingInProgress(true);
      setRenameInProgress(true);
      if (hasSchemaForMap) {
        setMapSchemaInProgress(true);
      }
      try {
        const renameLoadToken = loadTokenRef.current;
        const templateFields = buildTemplateFields(fieldsRef.current);
        const result = await ApiService.renameFields({
          sessionId: activeSessionId,
          schemaId: renameSchemaId || undefined,
          templateFields,
        });
        if (loadTokenRef.current !== renameLoadToken) {
          return null;
        }
        if (!result?.success) {
          throw new Error(result?.error || 'OpenAI rename failed.');
        }
        const updated = applyRenameResults(result.fields);
        if (!updated || updated.length === 0) {
          throw new Error('OpenAI rename returned no fields.');
        }
        setCheckboxRules(Array.isArray(result.checkboxRules) ? result.checkboxRules : []);
        if (!hasSchemaForMap) {
          setCheckboxHints([]);
        }
        if (!hasSchemaForMap) {
          setBannerNotice({
            tone: 'info',
            message:
              'Rename only standardizes field names. Complex checkbox groups and any checkbox columns that do not already match the field names may not fill.',
            autoDismissMs: 9000,
          });
        }
        setHasRenamedFields(true);
        return updated;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'OpenAI rename failed.';
        setOpenAiError(message);
        debugLog('OpenAI rename failed', message);
        return null;
      } finally {
        setRenameInProgress(false);
        setMappingInProgress(false);
        if (hasSchemaForMap) {
          setMapSchemaInProgress(false);
        }
      }
    },
    [
      applyRenameResults,
      verifiedUser,
      buildTemplateFields,
      clearPendingAutoActions,
      detectSessionId,
      requestConfirm,
    ],
  );

  const persistSchemaPayload = useCallback(
    async (payload: SchemaPayload): Promise<string | null> => {
      if (!verifiedUser) return null;
      if (schemaId) return schemaId;
      const fingerprint = JSON.stringify({
        name: payload.name,
        source: payload.source,
        sampleCount: payload.sampleCount,
        fields: payload.fields.map((field) => ({ name: field.name, type: field.type })),
      });
      if (
        schemaPersistPromiseRef.current &&
        schemaPersistFingerprintRef.current === fingerprint
      ) {
        return schemaPersistPromiseRef.current;
      }
      const persistPromise = (async () => {
        try {
          const created = await ApiService.createSchema(payload);
          const nextSchemaId = created.schemaId || null;
          setSchemaId(nextSchemaId);
          if (nextSchemaId) {
            setPendingSchemaPayload(null);
          }
          return nextSchemaId;
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Failed to store schema metadata.';
          setSchemaError(message);
          setSchemaId(null);
          return null;
        }
      })();
      schemaPersistPromiseRef.current = persistPromise;
      schemaPersistFingerprintRef.current = fingerprint;
      try {
        return await persistPromise;
      } finally {
        if (schemaPersistPromiseRef.current === persistPromise) {
          schemaPersistPromiseRef.current = null;
          schemaPersistFingerprintRef.current = null;
        }
      }
    },
    [schemaId, verifiedUser],
  );

  const resolveSchemaForMapping = useCallback(
    async (mode: 'map' | 'renameAndMap'): Promise<string | null> => {
      if (!verifiedUser) {
        if (mode === 'renameAndMap') {
          setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRenameAndMap);
        } else {
          setSchemaError(ALERT_MESSAGES.signInToRunSchemaMapping);
        }
        return null;
      }
      if (dataSourceKind === 'none') {
        const message =
          mode === 'renameAndMap'
            ? ALERT_MESSAGES.chooseSchemaFileForRenameAndMap
            : ALERT_MESSAGES.chooseSchemaFileForMapping;
        setSchemaError(message);
        return null;
      }
      if (
        (dataSourceKind === 'csv' ||
          dataSourceKind === 'excel' ||
          dataSourceKind === 'json' ||
          dataSourceKind === 'txt') &&
        dataColumns.length === 0
      ) {
        setSchemaError(buildImportFileBeforeMapping(dataSourceKind));
        return null;
      }
      if (schemaId) {
        return schemaId;
      }
      if (!pendingSchemaPayload) {
        const message =
          mode === 'renameAndMap'
            ? ALERT_MESSAGES.chooseSchemaFileForRenameAndMap
            : ALERT_MESSAGES.chooseSchemaFileForMapping;
        setSchemaError(message);
        return null;
      }
      setSchemaUploadInProgress(true);
      try {
        return await persistSchemaPayload(pendingSchemaPayload);
      } finally {
        setSchemaUploadInProgress(false);
      }
    },
    [
      dataColumns.length,
      dataSourceKind,
      pendingSchemaPayload,
      persistSchemaPayload,
      schemaId,
      verifiedUser,
    ],
  );

  const confirmRemap = useCallback(async () => {
    if (!hasMappedSchema) return true;
    return requestConfirm({
      title: 'Remap fields?',
      message: 'A mapping already exists for this schema. Do you want to map again?',
      confirmLabel: 'Remap',
      cancelLabel: 'Cancel',
    });
  }, [hasMappedSchema, requestConfirm]);

  const handleMapSchema = useCallback(async () => {
    const resolvedSchemaId = await resolveSchemaForMapping('map');
    if (!resolvedSchemaId) return;
    const ok = await requestConfirm({
      title: 'Send to OpenAI?',
      message:
        'Your database field headers and PDF field tags will be sent to OpenAI. No row data or field values are sent.',
      confirmLabel: 'Continue',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    const shouldRemap = await confirmRemap();
    if (!shouldRemap) return;

    setSchemaError(null);
    setOpenAiError(null);
    setMappingInProgress(true);
    setMapSchemaInProgress(true);
    try {
      const mapped = await applySchemaMappings({ schemaIdOverride: resolvedSchemaId });
      if (mapped) {
        handleMappingSuccess();
      }
    } finally {
      setMapSchemaInProgress(false);
      setMappingInProgress(false);
    }
  }, [
    applySchemaMappings,
    confirmRemap,
    handleMappingSuccess,
    requestConfirm,
    resolveSchemaForMapping,
  ]);

  const handleRename = useCallback(async () => {
    await runOpenAiRename({
      confirm: true,
    });
  }, [runOpenAiRename]);

  const handleRenameAndMap = useCallback(async () => {
    const resolvedSchemaId = await resolveSchemaForMapping('renameAndMap');
    if (!resolvedSchemaId) return;
    const ok = await requestConfirm({
      title: 'Send to OpenAI?',
      message:
        'This PDF and your database field headers will be sent to OpenAI. No row data or field values are sent.',
      confirmLabel: 'Continue',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    const shouldRemap = await confirmRemap();
    if (!shouldRemap) return;

    setSchemaError(null);
    setOpenAiError(null);
    const renamed = await runOpenAiRename({
      confirm: false,
      schemaId: resolvedSchemaId,
    });
    if (!renamed) return;
    handleMappingSuccess();
  }, [
    confirmRemap,
    handleMappingSuccess,
    requestConfirm,
    resolveSchemaForMapping,
    runOpenAiRename,
  ]);

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
            setBannerNotice({
              tone: 'info',
              message: 'Detection finished but no fields were found.',
              autoDismissMs: 8000,
            });
            return;
          }
          const hasEdits = historyRef.current.undo.length > 0;
          if (hasEdits) {
            updateFields(nextFields);
          } else {
            resetFieldHistory(nextFields);
          }
          setSelectedFieldId(null);
          setHasRenamedFields(false);
          setHasMappedSchema(false);
          setCheckboxRules([]);
          setCheckboxHints([]);
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
              const renamed = await runOpenAiRename({
                confirm: false,
                allowDefer: true,
                sessionId,
                schemaId: pendingAutoActions.schemaId,
              });
              if (renamed) {
                handleMappingSuccess();
              }
            } else if (pendingAutoActions.autoRename) {
              await runOpenAiRename({
                confirm: false,
                allowDefer: true,
                sessionId,
              });
            } else if (pendingAutoActions.autoMap) {
              if (!pendingAutoActions.schemaId) {
                setSchemaError('Upload a schema file before running mapping.');
              } else {
                const mapped = await applySchemaMappings({
                  schemaIdOverride: pendingAutoActions.schemaId,
                });
                if (mapped) {
                  handleMappingSuccess();
                }
              }
            }
          }
          setBannerNotice({
            tone: 'success',
            message: `Detection finished in the background (${nextFields.length} fields).`,
            autoDismissMs: 7000,
          });
          return;
        }
        if (status === 'failed') {
          detectionRetryRef.current.delete(sessionId);
          const message = payload?.error || 'Detection failed on the backend.';
          setBannerNotice({
            tone: 'error',
            message: String(message),
            autoDismissMs: 8000,
          });
          return;
        }
        if (payload?.timedOut) {
          setBannerNotice({
            tone: 'info',
            message: 'Detection is still running on the backend. It may take a few more minutes.',
            autoDismissMs: 8000,
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
          setBannerNotice({
            tone: 'error',
            message: error.message,
            autoDismissMs: 8000,
          });
          return;
        }
        const message =
          error instanceof Error ? error.message : 'Detection failed on the backend.';
        setBannerNotice({
          tone: 'error',
          message,
          autoDismissMs: 8000,
        });
        scheduleDetectionRetry(sessionId, loadToken);
      }
    },
    [
      scheduleDetectionRetry,
      applySchemaMappings,
      handleMappingSuccess,
      resetFieldHistory,
      runOpenAiRename,
      setBannerNotice,
      setCheckboxRules,
      setDetectSessionId,
      setHasMappedSchema,
      setHasRenamedFields,
      setMappingSessionId,
      setSelectedFieldId,
      setSchemaError,
      updateFields,
    ],
  );

  useEffect(() => {
    resumeDetectionPollingRef.current = resumeDetectionPolling;
  }, [resumeDetectionPolling]);

  const runDetectUpload = useCallback(
    async (
      file: File,
      options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null } = {},
    ) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      pendingAutoActionsRef.current = null;
      detectionRetryRef.current.clear();
      setShowSearchFill(false);
      setSearchFillSessionId((prev) => prev + 1);

      setProcessingMode('detect');
      setIsProcessing(true);
      setProcessingDetail(DEFAULT_PROCESSING_MESSAGE);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      setHasRenamedFields(false);
      setHasMappedSchema(false);
      setCheckboxRules([]);
      setCheckboxHints([]);
      setSchemaError(null);
      setOpenAiError(null);
      setSourceFile(file);
      setSourceFileName(file.name);
      setSourceFileIsDemo(false);
      setActiveSavedFormId(null);
      setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > profileLimits.detectMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          setLoadError(`Detection uploads are limited to ${profileLimits.detectMaxPages} pages on your plan.`);
          return;
        }
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        const activeSchemaId = options.schemaIdOverride ?? schemaId;

        let detectedFields: PdfField[] = [];
        let detectedSessionId: string | null = null;
        let detectionTimedOut = false;
        let detectionError: string | null = null;
        let authFailure: ApiError | null = null;

        try {
          const detection = await detectFields(file, {
            pipeline: detectionPipeline,
            onStatus: (payload) => {
              if (loadTokenRef.current !== loadToken) return;
              const message = resolveDetectionStatusMessage(payload);
              if (message) {
                setProcessingDetail(message);
              }
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
          clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          setLoadError(authFailure.message);
          setBannerNotice({
            tone: 'error',
            message: authFailure.message,
            autoDismissMs: 8000,
          });
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
          setBannerNotice({
            tone: 'error',
            message: `${detectionError} No embedded fields were found.`,
            autoDismissMs: 10000,
          });
        }
        if (detectionTimedOut) {
          setBannerNotice({
            tone: 'info',
            message: 'Detection is still running on the backend. Using embedded form fields for now.',
            autoDismissMs: 8000,
          });
          if (detectedSessionId) {
            void resumeDetectionPolling(detectedSessionId, loadToken);
          }
        }

        if (!commitPdfLoad(doc, sizes, detectedFields, loadToken)) return;
        setDetectSessionId(detectedSessionId);
        if (detectedSessionId) {
          setMappingSessionId(detectedSessionId);
        }
        debugLog('Loaded PDF', { name: file.name, pages: doc.numPages, fields: detectedFields.length });

        if (loadTokenRef.current !== loadToken) return;
        if (!options.autoRename && !options.autoMap) return;

        if (detectionTimedOut && detectedSessionId) {
          pendingAutoActionsRef.current = {
            loadToken,
            sessionId: detectedSessionId,
            schemaId: activeSchemaId,
            autoRename: Boolean(options.autoRename),
            autoMap: Boolean(options.autoMap),
          };
          setBannerNotice({
            tone: 'info',
            message: 'Detection is still running. OpenAI actions will start once fields are ready.',
            autoDismissMs: 8000,
          });
          return;
        }
        if (!detectedFields.length) {
          setBannerNotice({
            tone: 'info',
            message: 'No fields detected. OpenAI actions were skipped.',
            autoDismissMs: 8000,
          });
          return;
        }

        if (options.autoRename && options.autoMap) {
          const renamed = await runOpenAiRename({
            confirm: false,
            allowDefer: true,
            sessionId: detectedSessionId,
            schemaId: activeSchemaId,
          });
          if (renamed) {
            handleMappingSuccess();
          }
          return;
        }
        if (options.autoRename) {
          await runOpenAiRename({
            confirm: false,
            allowDefer: true,
            sessionId: detectedSessionId,
          });
        }
        if (options.autoMap) {
          const mapped = await applySchemaMappings({ schemaIdOverride: activeSchemaId });
          if (mapped) {
            handleMappingSuccess();
          }
        }
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [
      applySchemaMappings,
      clearWorkspace,
      commitPdfLoad,
      handleMappingSuccess,
      profileLimits.detectMaxPages,
      resumeDetectionPolling,
      runOpenAiRename,
      schemaId,
    ],
  );

  const handleDetectUpload = useCallback((file: File) => {
    setPendingDetectFile(file);
    setShowPipelineModal(true);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
  }, []);

  const handlePipelineCancel = useCallback(() => {
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
  }, []);

  const handlePipelineConfirm = useCallback(async () => {
    if (!pendingDetectFile) return;
    const wantsRename = uploadWantsRename;
    const wantsMap = uploadWantsMap;
    let resolvedSchemaId = wantsMap ? schemaId : null;
    if (wantsMap) {
      if (schemaUploadInProgress) {
        setPipelineError('Schema file is still processing. Please wait.');
        return;
      }
      if (!resolvedSchemaId) {
        if (!pendingSchemaPayload) {
          setPipelineError('Upload a schema file before running mapping.');
          return;
        }
        if (!verifiedUser) {
          setPipelineError('Sign in to upload a schema file before running mapping.');
          return;
        }
        setSchemaUploadInProgress(true);
        try {
          resolvedSchemaId = await persistSchemaPayload(pendingSchemaPayload);
        } finally {
          setSchemaUploadInProgress(false);
        }
        if (!resolvedSchemaId) {
          setPipelineError('Failed to store schema metadata. Please re-upload your schema file.');
          return;
        }
      }
    }
    const file = pendingDetectFile;
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
    void runDetectUpload(file, {
      autoRename: wantsRename,
      autoMap: wantsMap,
      schemaIdOverride: wantsMap ? resolvedSchemaId : null,
    });
  }, [
    pendingDetectFile,
    pendingSchemaPayload,
    persistSchemaPayload,
    runDetectUpload,
    schemaId,
    schemaUploadInProgress,
    uploadWantsMap,
    uploadWantsRename,
    verifiedUser,
  ]);

  const handleClearDataSource = useCallback(() => {
    setSchemaError(null);
    setSchemaId(null);
    setPendingSchemaPayload(null);
    setDataSourceKind('none');
    setDataSourceLabel(null);
    setSchemaUploadInProgress(false);
    setDataColumns([]);
    setDataRows([]);
    setIdentifierKey(null);
    setHasMappedSchema(false);
  }, []);

  const handleChooseDataSource = useCallback(
    (kind: Exclude<DataSourceKind, 'none'>) => {
      setSchemaError(null);
      if (kind === 'csv') {
        csvInputRef.current?.click();
        return;
      }
      if (kind === 'excel') {
        excelInputRef.current?.click();
        return;
      }
      if (kind === 'json') {
        jsonInputRef.current?.click();
        return;
      }
      if (kind === 'txt') {
        txtInputRef.current?.click();
      }
    },
    [],
  );

  const applySchemaMetadata = useCallback(
    async ({
      kind,
      label,
      schema,
      rows = [],
      fileName,
      source,
      skipPersist = false,
    }: {
      kind: Exclude<DataSourceKind, 'none'>;
      label: string;
      schema: { fields: Array<{ name: string; type?: string }>; sampleCount: number };
      rows?: Array<Record<string, unknown>>;
      fileName: string;
      source: 'csv' | 'excel' | 'json' | 'txt';
      skipPersist?: boolean;
    }) => {
      const columns = schema.fields.map((field) => field.name);
      setDataSourceKind(kind);
      setDataSourceLabel(label);
      setDataColumns(columns);
      setDataRows(rows);
      setIdentifierKey(pickIdentifierKey(columns));
      setHasMappedSchema(false);
      setSchemaId(null);
      const payload: SchemaPayload = {
        name: fileName,
        fields: schema.fields,
        source,
        sampleCount: schema.sampleCount,
      };
      setPendingSchemaPayload(payload);
      if (skipPersist || !verifiedUser) {
        return;
      }
      await persistSchemaPayload(payload);
    },
    [persistSchemaPayload, verifiedUser],
  );

  const applyParsedDataSource = useCallback(
    async ({
      kind,
      label,
      columns,
      rows,
      fileName,
      source,
      skipPersist = false,
    }: {
      kind: Exclude<DataSourceKind, 'none'>;
      label: string;
      columns: string[];
      rows: Array<Record<string, unknown>>;
      fileName: string;
      source: 'csv' | 'excel';
      skipPersist?: boolean;
    }) => {
      const schema = inferSchemaFromRows(columns, rows);
      await applySchemaMetadata({
        kind,
        label,
        schema,
        rows,
        fileName,
        source,
        skipPersist,
      });
    },
    [applySchemaMetadata],
  );

  const loadDemoAsset = useCallback(
    async (filename: string, mimeType: string) => {
      const cached = demoAssetCacheRef.current.get(filename);
      if (cached) return cached;
      const baseUrl = import.meta.env.BASE_URL ?? '/';
      const response = await fetch(`${baseUrl}demo/${filename}`);
      if (!response.ok) {
        throw new Error(`Failed to load demo asset: ${filename}`);
      }
      const blob = await response.blob();
      const file = new File([blob], filename, { type: mimeType });
      demoAssetCacheRef.current.set(filename, file);
      return file;
    },
    [],
  );

  const loadDemoPdf = useCallback(
    async (filename: string) => {
      const file = await loadDemoAsset(filename, 'application/pdf');
      await handleFillableUpload(file, { isDemo: true });
    },
    [handleFillableUpload, loadDemoAsset],
  );

  const notifyHeaderRenames = useCallback(
    (sourceLabel: string, fileName: string, headerRenames?: HeaderRename[]) => {
      if (!headerRenames?.length) return;
      const sample = headerRenames.slice(0, 3).map((entry) => `${entry.original} -> ${entry.renamed}`);
      const extra = headerRenames.length - sample.length;
      const suffix = extra > 0 ? ` (+${extra} more)` : '';
      setBannerNotice({
        tone: 'warning',
        message: `Duplicate ${sourceLabel} headers (after normalization) were renamed for ${fileName}: ${sample.join(', ')}${suffix}.`,
        autoDismissMs: 10000,
      });
    },
    [setBannerNotice],
  );

  const loadDemoCsv = useCallback(
    async (filename: string) => {
      const file = await loadDemoAsset(filename, 'text/csv');
      const text = await file.text();
      const parsed = parseCsv(text);
      if (!parsed.columns.length) {
        throw new Error('Demo CSV file has no header row.');
      }
      notifyHeaderRenames('CSV', file.name, parsed.headerRenames);
      await applyParsedDataSource({
        kind: 'csv',
        label: `CSV: ${file.name}`,
        columns: parsed.columns,
        rows: parsed.rows,
        fileName: file.name,
        source: 'csv',
        skipPersist: true,
      });
    },
    [applyParsedDataSource, loadDemoAsset, notifyHeaderRenames],
  );

  const startDemo = useCallback(() => {
    clearWorkspace();
    setLoadError(null);
    setShowHomepage(false);
    setDemoActive(true);
    setDemoStepIndex(0);
    setDemoCompletionOpen(false);
    setDemoSearchPreset(null);
    lastDemoStepRef.current = null;
  }, [clearWorkspace]);

  const exitDemo = useCallback(() => {
    setDemoActive(false);
    setDemoStepIndex(null);
    setShowSearchFill(false);
    setDemoCompletionOpen(false);
    setDemoSearchPreset(null);
  }, []);

  const handleDemoNext = useCallback(() => {
    if (demoStepIndex === null) return;
    if (demoStepIndex >= DEMO_STEPS.length - 1) return;
    setDemoStepIndex((prev) => (prev === null ? prev : prev + 1));
  }, [demoStepIndex]);

  const handleDemoBack = useCallback(() => {
    setDemoStepIndex((prev) => (prev && prev > 0 ? prev - 1 : prev));
  }, []);

  const handleDemoCompletion = useCallback(() => {
    setDemoActive(false);
    setDemoStepIndex(null);
    setDemoCompletionOpen(true);
    setDemoSearchPreset(null);
    setShowSearchFill(false);
  }, []);

  const handleDemoReplay = useCallback(() => {
    setDemoCompletionOpen(false);
    void startDemo();
  }, [startDemo]);

  const handleDemoContinue = useCallback(() => {
    setDemoCompletionOpen(false);
  }, []);

  useEffect(() => {
    if (!demoActive || demoStepIndex === null) return;
    if (lastDemoStepRef.current === demoStepIndex) return;
    lastDemoStepRef.current = demoStepIndex;

    const stepId = DEMO_STEPS[demoStepIndex]?.id;
    if (!stepId) return;

    void (async () => {
      try {
        setDemoSearchPreset(null);
        if (stepId === 'commonforms') {
          setShowSearchFill(false);
          await loadDemoPdf(DEMO_ASSETS.baseDetectionsPdf);
          return;
        }
        if (stepId === 'rename') {
          setShowSearchFill(false);
          return;
        }
        if (stepId === 'csv') {
          setShowSearchFill(false);
          await loadDemoCsv(DEMO_ASSETS.csv);
          return;
        }
        if (stepId === 'remap') {
          setShowSearchFill(false);
          return;
        }
        if (stepId === 'search-fill') {
          setShowSearchFill(false);
          await loadDemoPdf(DEMO_ASSETS.openAiRemapPdf);
          await loadDemoCsv(DEMO_ASSETS.csv);
          setDemoSearchPreset({
            query: 'Justin Thakral',
            searchKey: 'patient_name',
            searchMode: 'contains',
            autoRun: false,
            autoFillOnSearch: true,
            token: Date.now(),
          });
          setShowSearchFill(true);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to load demo assets.';
        setLoadError(message);
        exitDemo();
      }
    })();
  }, [demoActive, demoStepIndex, exitDemo, loadDemoCsv, loadDemoPdf]);

  const runSchemaUpload = useCallback(
    async (work: () => Promise<void>, fallbackMessage: string) => {
      setSchemaError(null);
      setMappingInProgress(true);
      setSchemaUploadInProgress(true);
      try {
        await work();
      } catch (error) {
        const message = error instanceof Error ? error.message : fallbackMessage;
        setSchemaError(message);
      } finally {
        setSchemaUploadInProgress(false);
        setMappingInProgress(false);
      }
    },
    [setMappingInProgress, setSchemaError, setSchemaUploadInProgress],
  );

  const handleCsvFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    await runSchemaUpload(
      async () => {
        const text = await file.text();
        const parsed = parseCsv(text);
        if (!parsed.columns.length) {
          throw new Error('CSV file has no header row.');
        }
        notifyHeaderRenames('CSV', file.name, parsed.headerRenames);
        await applyParsedDataSource({
          kind: 'csv',
          label: `CSV: ${file.name}`,
          columns: parsed.columns,
          rows: parsed.rows,
          fileName: file.name,
          source: 'csv',
        });
      },
      'Failed to import CSV file.',
    );
  }, [applyParsedDataSource, notifyHeaderRenames, runSchemaUpload]);

  const handleExcelFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    await runSchemaUpload(
      async () => {
        const buffer = await file.arrayBuffer();
        const parsed = await parseExcel(buffer);
        if (!parsed.columns.length) {
          throw new Error('Excel sheet has no header row.');
        }
        notifyHeaderRenames('Excel', file.name, parsed.headerRenames);
        await applyParsedDataSource({
          kind: 'excel',
          label: `Excel: ${file.name}${parsed.sheetName ? ` (${parsed.sheetName})` : ''}`,
          columns: parsed.columns,
          rows: parsed.rows,
          fileName: file.name,
          source: 'excel',
        });
      },
      'Failed to import Excel file.',
    );
  }, [applyParsedDataSource, notifyHeaderRenames, runSchemaUpload]);

  const handleJsonFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    await runSchemaUpload(
      async () => {
        const text = await file.text();
        const parsed = parseJsonDataSource(text);
        if (!parsed.schema.fields.length) {
          throw new Error('JSON schema has no field names.');
        }
        notifyHeaderRenames('JSON', file.name, parsed.headerRenames);
        await applySchemaMetadata({
          kind: 'json',
          label: `JSON: ${file.name}`,
          schema: parsed.schema,
          rows: parsed.rows,
          fileName: file.name,
          source: 'json',
        });
      },
      'Failed to import JSON file.',
    );
  }, [applySchemaMetadata, runSchemaUpload]);

  const handleTxtFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    await runSchemaUpload(
      async () => {
        const text = await file.text();
        const schema = parseSchemaText(text);
        if (!schema.fields.length) {
          throw new Error('TXT schema file has no field names.');
        }
        await applySchemaMetadata({
          kind: 'txt',
          label: `TXT: ${file.name}`,
          schema,
          rows: [],
          fileName: file.name,
          source: 'txt',
        });
      },
      'Failed to import TXT schema file.',
    );
  }, [applySchemaMetadata, runSchemaUpload]);

  const handleSelectField = useCallback(
    (fieldId: string) => {
      setSelectedFieldId(fieldId);
      const field = fieldsRef.current.find((entry) => entry.id === fieldId);
      if (!field) return;
      if (field.page && field.page !== currentPage) {
        setCurrentPage(field.page);
      }
    },
    [currentPage],
  );

  const handlePageJump = useCallback((page: number) => {
    setCurrentPage(page);
    setPendingPageJump(page);
    setSelectedFieldId((prev) => {
      if (!prev) return prev;
      const field = fieldsRef.current.find((entry) => entry.id === prev);
      if (!field) return prev;
      return field.page === page ? prev : null;
    });
  }, []);

  const handlePageScroll = useCallback((page: number) => {
    setCurrentPage(page);
    setSelectedFieldId((prev) => {
      if (!prev) return prev;
      const field = fieldsRef.current.find((entry) => entry.id === prev);
      if (!field) return prev;
      return field.page === page ? prev : null;
    });
  }, []);

  const handlePageJumpComplete = useCallback(() => {
    setPendingPageJump(null);
  }, []);

  const handleUpdateField = useCallback((fieldId: string, updates: Partial<PdfField>) => {
    updateFieldsWith((prev) =>
      prev.map((field) => {
        if (field.id !== fieldId) return field;
        return {
          ...field,
          ...updates,
          rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
        };
      }),
    );
    debugLog('Updated field', fieldId, updates);
  }, [updateFieldsWith]);

  const handleUpdateFieldDraft = useCallback(
    (fieldId: string, updates: Partial<PdfField>) => {
      updateFieldsWith(
        (prev) =>
          prev.map((field) => {
            if (field.id !== fieldId) return field;
            return {
              ...field,
              ...updates,
              rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
            };
          }),
        { trackHistory: false },
      );
      debugLog('Updated field (draft)', fieldId, updates);
    },
    [updateFieldsWith],
  );

  const handleUpdateFieldGeometry = useCallback(
    (fieldId: string, updates: Partial<PdfField>) => {
      updateFieldsWith(
        (prev) =>
          prev.map((field) => {
            if (field.id !== fieldId) return field;
            return {
              ...field,
              ...updates,
              rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
            };
          }),
        { trackHistory: false },
      );
    },
    [updateFieldsWith],
  );

  const handleDeleteField = useCallback((fieldId: string) => {
    updateFieldsWith((prev) => prev.filter((field) => field.id !== fieldId));
    setSelectedFieldId((prev) => (prev === fieldId ? null : prev));
    debugLog('Deleted field', fieldId);
  }, [updateFieldsWith]);

  const handleCreateField = useCallback(
    (type: FieldType) => {
      const pageSize = pageSizes[currentPage];
      if (!pageSize) return;
      const nextField = createField(type, currentPage, pageSize, fieldsRef.current);
      updateFieldsWith((prev) => [...prev, nextField]);
      setSelectedFieldId(nextField.id);
      debugLog('Created field', nextField);
    },
    [currentPage, pageSizes, updateFieldsWith],
  );

  const handleDismissBanner = useCallback(() => {
    if (openAiError || schemaError) {
      setSchemaError(null);
      setOpenAiError(null);
    }
    if (bannerNotice) {
      setBannerNotice(null);
    }
  }, [bannerNotice, openAiError, schemaError]);

  const handleFieldsChange = useCallback(
    (nextFields: PdfField[]) => {
      updateFields(nextFields);
    },
    [updateFields],
  );

  const hasFieldValues = useMemo(
    () =>
      fields.some((field) => {
        const value = field.value;
        if (value === null || value === undefined) return false;
        if (typeof value === 'string') return value.trim().length > 0;
        if (typeof value === 'boolean') return value;
        return true;
      }),
    [fields],
  );

  const handleClearFieldValues = useCallback(() => {
    updateFieldsWith((prev) => {
      let changed = false;
      const next = prev.map((field) => {
        const value = field.value;
        if (value === null || value === undefined) return field;
        if (typeof value === 'string' && value.trim().length === 0) return field;
        if (typeof value === 'boolean' && value === false) return field;
        changed = true;
        return { ...field, value: null };
      });
      return changed ? next : prev;
    });
  }, [updateFieldsWith]);

  const visibleFields = useMemo(
    () => fields.filter((field) => confidenceFilter[fieldConfidenceTierForField(field)]),
    [confidenceFilter, fields],
  );

  const canUndo = useMemo(() => historyRef.current.undo.length > 0, [historyTick]);
  const canRedo = useMemo(() => historyRef.current.redo.length > 0, [historyTick]);

  const handleConfidenceFilterChange = useCallback((tier: ConfidenceTier, enabled: boolean) => {
    setConfidenceFilter((prev) => ({
      ...prev,
      [tier]: enabled,
    }));
  }, []);

  const handleShowFieldsChange = useCallback((enabled: boolean) => {
    if (!enabled) {
      setShowFields(false);
      setShowFieldInfo(false);
      return;
    }
    setShowFields(true);
    const lastVisibility = lastFieldVisibilityRef.current;
    if (lastVisibility.showFieldInfo) {
      setShowFieldInfo(true);
      setShowFieldNames(false);
    } else {
      setShowFieldInfo(false);
      setShowFieldNames(lastVisibility.showFieldNames);
    }
  }, []);

  const handleShowFieldNamesChange = useCallback((enabled: boolean) => {
    setShowFieldNames(enabled);
    if (enabled) {
      setShowFieldInfo(false);
    }
  }, []);

  const handleShowFieldInfoChange = useCallback((enabled: boolean) => {
    setShowFieldInfo(enabled);
    if (enabled) {
      setShowFieldNames(false);
      setShowFields(true);
    }
  }, []);

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
      if (!modifier) return;
      const key = event.key.toLowerCase();
      if (key === 'z') {
        event.preventDefault();
        if (event.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      } else if (key === 'x') {
        if (!selectedFieldId) return;
        event.preventDefault();
        handleDeleteField(selectedFieldId);
      } else if (key === 'y') {
        event.preventDefault();
        handleRedo();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleDeleteField, handleRedo, handleUndo, pdfDoc, selectedFieldId]);

  const demoAssetNames = useMemo(() => new Set(Object.values(DEMO_ASSETS)), []);
  const isDemoAsset = useMemo(
    () => Boolean(sourceFileIsDemo && sourceFileName && demoAssetNames.has(sourceFileName)),
    [demoAssetNames, sourceFileIsDemo, sourceFileName],
  );
  const demoSessionSuppressed = demoActive || demoCompletionOpen || isDemoAsset;
  const demoUiLocked = demoCompletionOpen || (!demoActive && isDemoAsset);

  useEffect(() => {
    const sessionId = detectSessionId || mappingSessionId;
    if (!sessionId || !verifiedUser || !pdfDoc || demoSessionSuppressed) return;

    let cancelled = false;
    let intervalId: number | null = null;
    const intervalMs = 60_000;

    const reportExpired = () => {
      setBannerNotice({
        tone: 'info',
        message: 'This session expired. Re-upload the PDF to run Rename or Map again.',
        autoDismissMs: 8000,
      });
      setDetectSessionId(null);
      setMappingSessionId(null);
    };

    const ping = async () => {
      try {
        await ApiService.touchSession(sessionId);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
          reportExpired();
          return;
        }
        debugLog('Failed to refresh session TTL', error);
      }
    };

    const start = () => {
      if (intervalId !== null) return;
      intervalId = window.setInterval(() => {
        if (!document.hidden) {
          void ping();
        }
      }, intervalMs);
      void ping();
    };

    const stop = () => {
      if (intervalId === null) return;
      window.clearInterval(intervalId);
      intervalId = null;
    };

    const handleVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        start();
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    if (!document.hidden) {
      start();
    }

    return () => {
      cancelled = true;
      stop();
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [demoSessionSuppressed, detectSessionId, mappingSessionId, pdfDoc, setBannerNotice, verifiedUser]);

  useEffect(() => {
    if (!isDemoAsset) return;
    if (sourceFileName !== DEMO_ASSETS.openAiRemapPdf) return;
    if (!dataColumns.length || !fields.length) return;
    if (fields.length !== dataColumns.length) return;
    const needsMapping = fields.some((field, index) => field.name !== dataColumns[index]);
    if (!needsMapping) return;
    const mappedFields = fields.map((field, index) => ({
      ...field,
      name: dataColumns[index],
    }));
    resetFieldHistory(mappedFields);
    setSelectedFieldId(null);
  }, [dataColumns, fields, isDemoAsset, resetFieldHistory, setSelectedFieldId, sourceFileName]);

  const userEmail = useMemo(() => verifiedUser?.email ?? undefined, [verifiedUser]);
  const hasDocument = !!pdfDoc;
  const canSaveToProfile = Boolean(pdfDoc && verifiedUser);
  const canDownload = Boolean(pdfDoc && verifiedUser);
  const canMapSchema = useMemo(() => {
    if (!verifiedUser) return false;
    if (!hasDocument || fields.length === 0) return false;
    if (!detectSessionId && !activeSavedFormId) return false;
    if (
      dataSourceKind === 'csv' ||
      dataSourceKind === 'excel' ||
      dataSourceKind === 'json' ||
      dataSourceKind === 'txt'
    ) {
      return dataColumns.length > 0 && Boolean(schemaId || pendingSchemaPayload);
    }
    return false;
  }, [
    dataColumns.length,
    dataSourceKind,
    fields.length,
    hasDocument,
    pendingSchemaPayload,
    schemaId,
    verifiedUser,
  ]);
  const canRename = useMemo(() => {
    if (!verifiedUser) return false;
    if (!hasDocument || fields.length === 0) return false;
    if (!detectSessionId) return false;
    return true;
  }, [detectSessionId, fields.length, hasDocument, verifiedUser]);
  const canRenameAndMap = useMemo(() => {
    if (!canRename) return false;
    return canMapSchema;
  }, [canMapSchema, canRename]);
  const canSearchFill = useMemo(() => {
    if (!hasDocument) return false;
    if (dataSourceKind === 'none') return false;
    if (!['csv', 'excel', 'json'].includes(dataSourceKind)) return false;
    return dataRows.length > 0;
  }, [dataRows.length, dataSourceKind, hasDocument]);
  const activeErrorMessage = openAiError ?? schemaError;
  const bannerAlert: BannerNotice | null = activeErrorMessage
    ? { tone: 'error', message: activeErrorMessage }
    : bannerNotice;
  const handleDemoLockedAction = useCallback(() => {
    if (typeof window === 'undefined') return;
    window.alert(DEMO_DISABLED_MESSAGE);
  }, []);
  const handleDemoRename = useCallback(async () => {
    setShowSearchFill(false);
    await loadDemoPdf(DEMO_ASSETS.openAiRenamePdf);
  }, [loadDemoPdf]);
  const handleDemoMapSchema = useCallback(async () => {
    setShowSearchFill(false);
    if (!dataColumns.length) {
      await loadDemoCsv(DEMO_ASSETS.csv);
    }
    await loadDemoPdf(DEMO_ASSETS.openAiRemapPdf);
  }, [dataColumns.length, loadDemoCsv, loadDemoPdf]);
  const handleDemoRenameAndMap = useCallback(async () => {
    setShowSearchFill(false);
    if (!dataColumns.length) {
      await loadDemoCsv(DEMO_ASSETS.csv);
    }
    await loadDemoPdf(DEMO_ASSETS.openAiRemapPdf);
  }, [dataColumns.length, loadDemoCsv, loadDemoPdf]);
  const dialogContent = (() => {
    if (!dialogRequest) return null;
    if (dialogRequest.kind === 'confirm') {
      return (
        <ConfirmDialog
          open
          title={dialogRequest.title}
          description={dialogRequest.message}
          confirmLabel={dialogRequest.confirmLabel}
          cancelLabel={dialogRequest.cancelLabel}
          tone={dialogRequest.tone}
          onConfirm={() => resolveDialog(true)}
          onCancel={() => resolveDialog(false)}
        />
      );
    }
    if (dialogRequest.kind === 'prompt') {
      return (
        <PromptDialog
          open
          title={dialogRequest.title}
          description={dialogRequest.message}
          confirmLabel={dialogRequest.confirmLabel}
          cancelLabel={dialogRequest.cancelLabel}
          tone={dialogRequest.tone}
          defaultValue={dialogRequest.defaultValue}
          placeholder={dialogRequest.placeholder}
          requireValue={dialogRequest.requireValue}
          onSubmit={(value) => resolveDialog(value)}
          onCancel={() => resolveDialog(null)}
        />
      );
    }
    return null;
  })();

  const savedFormsLimitDialog = (
    <SavedFormsLimitDialog
      open={showSavedFormsLimitDialog}
      maxSavedForms={profileLimits.savedFormsMax}
      savedForms={savedForms}
      deletingFormId={deletingFormId}
      onDelete={handleSavedFormsLimitDelete}
      onClose={closeSavedFormsLimitDialog}
    />
  );
  const demoCompletionDialog = (
    <ConfirmDialog
      open={demoCompletionOpen}
      title="Demo complete"
      description="Replay the walkthrough or keep exploring the editor with the mapped PDF."
      confirmLabel="Replay demo"
      cancelLabel="Continue in editor"
      onConfirm={handleDemoReplay}
      onCancel={handleDemoContinue}
    />
  );
  const dataSourceInputs = (
    <>
      <input
        ref={csvInputRef}
        id="csv-file-input"
        name="csv-file"
        type="file"
        accept=".csv,text/csv"
        style={{ display: 'none' }}
        onChange={handleCsvFileSelected}
      />
      <input
        ref={excelInputRef}
        id="excel-file-input"
        name="excel-file"
        type="file"
        accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
        style={{ display: 'none' }}
        onChange={handleExcelFileSelected}
      />
      <input
        ref={jsonInputRef}
        id="json-file-input"
        name="json-file"
        type="file"
        accept=".json,application/json"
        style={{ display: 'none' }}
        onChange={handleJsonFileSelected}
      />
      <input
        ref={txtInputRef}
        id="txt-file-input"
        name="txt-file"
        type="file"
        accept=".txt,text/plain"
        style={{ display: 'none' }}
        onChange={handleTxtFileSelected}
      />
    </>
  );
  const currentView = showHomepage
    ? 'homepage'
    : isProcessing
      ? 'processing'
    : hasDocument
      ? 'editor'
      : 'upload';
  const activeDemoStep = demoStepIndex !== null ? DEMO_STEPS[demoStepIndex] : null;
  const showDemoTour = demoActive && currentView === 'editor';
  const shouldShowProcessingAd = processingMode === 'detect' && Boolean(PROCESSING_AD_VIDEO_URL);

  useEffect(() => {
    if (currentView === 'editor') return;
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  }, [currentView]);

  if (!authReady) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">Loading workspace…</div>
      </div>
    );
  }

  if (requiresEmailVerification) {
    return (
      <VerifyEmailPage
        email={authUser?.email ?? null}
        onRefresh={handleRefreshVerification}
        onSignOut={handleSignOut}
      />
    );
  }

  if (showLogin) {
    return (
      <LoginPage
        onAuthenticated={() => setShowLogin(false)}
        onCancel={() => setShowLogin(false)}
      />
    );
  }

  if (showProfile && verifiedUser) {
    return (
      <>
        {bannerAlert ? (
          <Alert
            tone={bannerAlert.tone}
            variant="banner"
            message={bannerAlert.message}
            onDismiss={handleDismissBanner}
          />
        ) : null}
        {savedFormsLimitDialog}
        {dialogContent}
        <ProfilePage
          email={userProfile?.email ?? verifiedUser.email}
          role={userProfile?.role ?? 'basic'}
          creditsRemaining={userProfile?.creditsRemaining ?? 0}
          isLoading={profileLoading}
          limits={profileLimits}
          savedForms={savedForms}
          onSelectSavedForm={handleSelectSavedFormFromProfile}
          onDeleteSavedForm={handleDeleteSavedForm}
          deletingFormId={deletingFormId}
          onClose={handleCloseProfile}
          onSignOut={handleSignOut}
        />
      </>
    );
  }

  if (currentView !== 'editor') {
    return (
      <div className="homepage-shell">
        {bannerAlert ? (
          <Alert
            tone={bannerAlert.tone}
            variant="banner"
            message={bannerAlert.message}
            onDismiss={handleDismissBanner}
          />
        ) : null}
        {savedFormsLimitDialog}
        {demoCompletionDialog}
        {dialogContent}
        <LegacyHeader
          currentView={currentView}
          onNavigateHome={handleNavigateHome}
          showBackButton={!showHomepage}
          userEmail={verifiedUser?.email ?? null}
          onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
          onSignOut={verifiedUser ? handleSignOut : undefined}
          onSignIn={!verifiedUser ? () => setShowLogin(true) : undefined}
        />
        <main className="landing-main">
          {currentView === 'homepage' && (
            <Homepage
              onStartWorkflow={() => setShowHomepage(false)}
              onStartDemo={startDemo}
              userEmail={verifiedUser?.email ?? null}
              onSignIn={!verifiedUser ? () => setShowLogin(true) : undefined}
              onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
            />
          )}
          {currentView === 'upload' && (
            <div className="upload-layout">
              {showPipelineModal && (
                <div
                  className="pipeline-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="pipeline-modal-title"
                >
                  <div className="pipeline-modal__card">
                    <div className="pipeline-modal__header">
                      <h2 id="pipeline-modal-title" className="pipeline-modal__title">
                        Choose your detection pipeline
                      </h2>
                      {pendingDetectFile && (
                        <p className="pipeline-modal__subtitle">{pendingDetectFile.name}</p>
                      )}
                    </div>
                    <div className="pipeline-modal__section">
                      <span className="pipeline-modal__section-title">Detection pipeline</span>
                      <label className="pipeline-modal__choice">
                        <input
                          type="radio"
                          name="pipeline"
                          value="commonforms"
                          checked
                          disabled
                        />
                        <CommonFormsAttribution suffix="(FFDNet-L)" />
                      </label>
                    </div>
                    <div className="pipeline-modal__section">
                      <span className="pipeline-modal__section-title">OpenAI actions</span>
                      <p className="pipeline-modal__notice">
                        Rename sends PDF pages and detected field tags. Mapping sends schema header names and field
                        tags. If both are selected, OpenAI receives the PDF pages and schema headers to standardize
                        names. No row data or field values are sent.
                      </p>
                      <label className="pipeline-modal__choice">
                        <input
                          type="checkbox"
                          id="pipeline-rename"
                          name="pipeline-rename"
                          checked={uploadWantsRename}
                          onChange={(event) => setUploadWantsRename(event.target.checked)}
                        />
                        Rename fields with OpenAI
                      </label>
                      <label className="pipeline-modal__choice">
                        <input
                          type="checkbox"
                          id="pipeline-map"
                          name="pipeline-map"
                          checked={uploadWantsMap}
                          onChange={(event) => setUploadWantsMap(event.target.checked)}
                        />
                        Map to schema (CSV/Excel/JSON/TXT)
                      </label>
                      {uploadWantsRename || uploadWantsMap ? (
                        <p className="pipeline-modal__hint">
                          {uploadWantsRename && uploadWantsMap
                            ? 'OpenAI will receive the PDF pages, detected field tags, and your database field headers. No row data or field values are sent.'
                            : uploadWantsRename
                              ? 'OpenAI will receive the PDF pages and detected field tags. No row data or field values are sent.'
                              : 'OpenAI will receive your database field headers and detected field tags. No row data or field values are sent.'}
                        </p>
                      ) : null}
                      {uploadWantsMap ? (
                        <div className="pipeline-modal__schema-block">
                          <div className="pipeline-modal__source-row">
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('csv')}
                            >
                              CSV
                            </button>
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('excel')}
                            >
                              Excel
                            </button>
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('json')}
                            >
                              JSON
                            </button>
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('txt')}
                            >
                              TXT
                            </button>
                          </div>
                          <span className="pipeline-modal__status pipeline-modal__status--center">
                            Schema file: {dataSourceLabel || 'None selected'}
                            {schemaUploadInProgress ? ' (processing)' : ''}
                          </span>
                        </div>
                      ) : null}
                    </div>
                    {pipelineError ? (
                      <div className="pipeline-modal__alert">
                        <Alert tone="error" variant="inline" size="sm" message={pipelineError} />
                      </div>
                    ) : null}
                    <div className="pipeline-modal__actions">
                      <button
                        className="ui-button ui-button--ghost"
                        type="button"
                        onClick={handlePipelineCancel}
                      >
                        Cancel
                      </button>
                      <button
                        className="ui-button ui-button--primary"
                        type="button"
                        onClick={handlePipelineConfirm}
                        disabled={!pendingDetectFile || (uploadWantsMap && schemaUploadInProgress)}
                      >
                        Continue
                      </button>
                    </div>
                  </div>
                </div>
              )}
              <div className="upload-primary-grid">
                <UploadComponent
                  variant="detect"
                  title="Upload PDF for Field Detection"
                  subtitle="Drag and drop your PDF file here, or"
                  onFileUpload={handleDetectUpload}
                  onValidationError={(message) => setLoadError(message)}
                />
                <UploadComponent
                  variant="fillable"
                  title="Upload Fillable PDF Template"
                  subtitle="Open your existing fillable PDF directly in the editor"
                  onFileUpload={handleFillableUpload}
                  onValidationError={(message) => setLoadError(message)}
                />
              </div>
              {verifiedUser && (
                <section className="saved-forms-section" aria-label="Open saved form">
                  <h2 className="saved-forms-title">Open Saved Form:</h2>
                  <UploadComponent
                    variant="saved"
                    title=""
                    subtitle=""
                    savedForms={savedForms}
                    onSelectSavedForm={handleSelectSavedForm}
                    onDeleteSavedForm={handleDeleteSavedForm}
                    deletingFormId={deletingFormId}
                  />
                </section>
              )}
              {loadError ? (
                <div className="upload-alert">
                  <Alert tone="error" variant="inline" message={loadError} />
                </div>
              ) : null}
            </div>
          )}
          {currentView === 'processing' && (
            <div className="processing-indicator">
              <div className="spinner"></div>
              <h3>Preparing your form…</h3>
              <p>{processingDetail}</p>
              {shouldShowProcessingAd ? (
                <div className="processing-ad" aria-live="polite">
                  <video
                    className="processing-ad__video"
                    src={PROCESSING_AD_VIDEO_URL}
                    poster={PROCESSING_AD_POSTER_URL || undefined}
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="auto"
                  />
                  <p className="processing-ad__note">
                    This short video runs while field detection finishes on the backend. It helps
                    cover hosting so the tool can stay free.
                  </p>
                </div>
              ) : null}
            </div>
          )}
        </main>
        {dataSourceInputs}
      </div>
    );
  }

  const appShellClassName = demoActive || demoCompletionOpen ? 'app app--demo-locked' : 'app';

  return (
    <div className={appShellClassName}>
      {bannerAlert ? (
        <Alert
          tone={bannerAlert.tone}
          variant="banner"
          message={bannerAlert.message}
          onDismiss={handleDismissBanner}
        />
      ) : null}
      {savedFormsLimitDialog}
      {demoCompletionDialog}
      {dialogContent}
      <HeaderBar
        pageCount={pageCount}
        currentPage={currentPage}
        scale={scale}
        onScaleChange={setScale}
        onNavigateHome={handleNavigateHome}
        mappingInProgress={mappingInProgress}
        mapSchemaInProgress={mapSchemaInProgress}
        hasMappedSchema={hasMappedSchema}
        renameInProgress={renameInProgress}
        hasRenamedFields={hasRenamedFields}
        dataSourceKind={dataSourceKind}
        dataSourceLabel={dataSourceLabel}
        onChooseDataSource={handleChooseDataSource}
        onClearDataSource={handleClearDataSource}
        onRename={demoActive ? handleDemoRename : handleRename}
        onRenameAndMap={demoActive ? handleDemoRenameAndMap : handleRenameAndMap}
        onMapSchema={demoActive ? handleDemoMapSchema : handleMapSchema}
        canMapSchema={demoActive ? true : canMapSchema}
        canRename={demoActive ? true : canRename}
        canRenameAndMap={demoActive ? true : canRenameAndMap}
        onOpenSearchFill={canSearchFill ? () => setShowSearchFill(true) : undefined}
        canSearchFill={canSearchFill}
        onDownload={handleDownload}
        onSaveToProfile={handleSaveToProfile}
        downloadInProgress={downloadInProgress}
        saveInProgress={saveInProgress}
        canDownload={canDownload}
        canSave={canSaveToProfile}
        userEmail={userEmail}
        onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
        onSignIn={!verifiedUser ? () => setShowLogin(true) : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
        demoLocked={demoUiLocked}
        onDemoLockedAction={handleDemoLockedAction}
      />
      <div className="app-shell">
        <FieldListPanel
          fields={visibleFields}
          selectedFieldId={selectedFieldId}
          currentPage={currentPage}
          pageCount={pageCount}
          showFields={showFields}
          showFieldNames={showFieldNames}
          showFieldInfo={showFieldInfo}
          onShowFieldsChange={handleShowFieldsChange}
          onShowFieldNamesChange={handleShowFieldNamesChange}
          onShowFieldInfoChange={handleShowFieldInfoChange}
          canClearInputs={hasFieldValues}
          onClearInputs={handleClearFieldValues}
          confidenceFilter={confidenceFilter}
          onConfidenceFilterChange={handleConfidenceFilterChange}
          onSelectField={handleSelectField}
          onPageChange={handlePageJump}
        />
        <main className="workspace">
          {loadError ? (
            <div className="viewer viewer--empty">
              <div className="viewer__placeholder viewer__placeholder--error">
                <h2>Unable to load PDF</h2>
                <Alert tone="error" variant="inline" message={loadError} />
              </div>
            </div>
          ) : (
            <PdfViewer
              pdfDoc={pdfDoc}
              pageNumber={currentPage}
              scale={scale}
              pageSizes={pageSizes}
              fields={visibleFields}
              showFields={showFields}
              showFieldNames={showFieldNames}
              showFieldInfo={showFieldInfo}
              selectedFieldId={selectedFieldId}
              onSelectField={handleSelectField}
              onUpdateField={handleUpdateField}
              onUpdateFieldGeometry={handleUpdateFieldGeometry}
              onBeginFieldChange={beginFieldHistory}
              onCommitFieldChange={commitFieldHistory}
              onPageChange={handlePageScroll}
              pendingPageJump={pendingPageJump}
              onPageJumpComplete={handlePageJumpComplete}
            />
          )}
        </main>
        <FieldInspectorPanel
          fields={fields}
          selectedFieldId={selectedFieldId}
          currentPage={currentPage}
          onUpdateField={handleUpdateField}
          onUpdateFieldDraft={handleUpdateFieldDraft}
          onDeleteField={handleDeleteField}
          onCreateField={handleCreateField}
          onBeginFieldChange={beginFieldHistory}
          onCommitFieldChange={commitFieldHistory}
          canUndo={canUndo}
          canRedo={canRedo}
          onUndo={handleUndo}
          onRedo={handleRedo}
        />
      </div>
      {showSearchFill ? (
        <SearchFillModal
          open={showSearchFill}
          onClose={() => setShowSearchFill(false)}
          sessionId={searchFillSessionId}
          dataSourceKind={dataSourceKind}
          dataSourceLabel={dataSourceLabel}
          columns={dataColumns}
          identifierKey={identifierKey}
          rows={dataRows}
          fields={fields}
          checkboxRules={checkboxRules}
          checkboxHints={checkboxHints}
          onFieldsChange={handleFieldsChange}
          onClearFields={handleClearFieldValues}
          onAfterFill={() => {
            setShowFieldInfo(true);
            setShowFieldNames(false);
            setShowFields(true);
            if (demoActive && DEMO_STEPS[demoStepIndex ?? -1]?.id === 'search-fill') {
              handleDemoCompletion();
            }
          }}
          onError={(message) => setSchemaError(message)}
          onRequestDataSource={(kind) => handleChooseDataSource(kind)}
          demoSearch={demoActive ? demoSearchPreset : null}
        />
      ) : null}
      {dataSourceInputs}
      {showDemoTour ? (
        <DemoTour
          open={showDemoTour}
          step={activeDemoStep}
          stepIndex={demoStepIndex ?? 0}
          stepCount={DEMO_STEPS.length}
          onNext={handleDemoNext}
          onBack={handleDemoBack}
          onClose={exitDemo}
        />
      ) : null}
    </div>
  );
}

export default App;
