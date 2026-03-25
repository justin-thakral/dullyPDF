/**
 * Application-level constants extracted from App.tsx.
 */
import type { ProfileLimits } from '../services/api';
import type { DemoStep } from '../components/demo/DemoTour';
import { CommonFormsAttribution } from '../components/ui/CommonFormsAttribution';

export const MAX_FIELD_HISTORY = 10;
export const SAVED_FORMS_RETRY_LIMIT = 3;
export const SAVED_FORMS_RETRY_BASE_MS = 500;
export const SAVED_FORMS_RETRY_MAX_MS = 4000;
export const SAVED_FORMS_TIMEOUT_MS = 6000;
export const AUTH_READY_FALLBACK_MS = 5000;

export const DEMO_ASSETS = {
  rawPdf: 'new_patient_forms_1915ccb015.pdf',
  baseDetectionsFields: 'generated/baseFieldDetections.fields.json',
  openAiRenamePdf: 'openAiRename.pdf',
  openAiRemapPdf: 'openAiRemap.pdf',
  csv: 'new_patient_forms_1915ccb015_mock.csv',
  openAiRenameNameMap: 'generated/baseToOpenAiRenameNameMap.json',
  openAiRemapNameMap: 'generated/baseToOpenAiRemapNameMap.json',
};

export const DEMO_DISABLED_MESSAGE = 'Demo is view-only for save, schema, and publish actions. Upload or open your own form to use them.';

export const DEMO_STEPS: DemoStep[] = [
  {
    id: 'raw-pdf',
    title: 'Start with the raw intake PDF',
    body: 'Begin with the source form exactly as the clinic provides it.',
    variant: 'modal',
  },
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
    body: null,
    targetSelector: '[data-demo-target="search-fill-search"]',
    placement: 'right',
    showNext: false,
  },
];

const env = import.meta.env;

export const PROCESSING_AD_VIDEO_URL =
  typeof env.VITE_PROCESSING_AD_VIDEO_URL === 'string' ? env.VITE_PROCESSING_AD_VIDEO_URL.trim() : '';
export const PROCESSING_AD_POSTER_URL =
  typeof env.VITE_PROCESSING_AD_POSTER_URL === 'string' ? env.VITE_PROCESSING_AD_POSTER_URL.trim() : '';
export const DETECT_PROCESSING_TITLE = 'Preparing your form…';
export const FILLABLE_TEMPLATE_PROCESSING_TITLE = 'Opening your fillable PDF…';
export const SAVED_FORM_PROCESSING_TITLE = 'Loading form…';
export const SAVED_GROUP_PROCESSING_TITLE = 'Loading form…';
export const DEFAULT_PROCESSING_MESSAGE = 'Detecting fields and building the editor.';
export const DETECTION_WARMUP_MESSAGE = 'Warming up rename detector';
export const DETECTION_POST_WARMUP_MESSAGE = 'Detecting fields...';
export const DETECTION_WARMUP_DURATION_MS = 5_000;
export const DETECTION_WARMUP_DELAY_MS = 3_000;
export const DETECTION_WARMUP_PAGE_THRESHOLD = 3;
export const SAVED_FORM_PROCESSING_MESSAGE = '';
export const SAVED_GROUP_PROCESSING_MESSAGE = '';
export const FILLABLE_TEMPLATE_PROCESSING_MESSAGE = 'Opening your fillable PDF in the editor.';
export const QUEUE_WAIT_THRESHOLD_MS = 15000;

export const DETECTION_BACKGROUND_POLL_TIMEOUT_MS = (() => {
  const raw = env.VITE_DETECTION_BACKGROUND_TIMEOUT_MS;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && parsed >= 0) {
    return parsed;
  }
  return 10 * 60 * 1000;
})();

export const DETECTION_BACKGROUND_RETRY_BASE_MS = 5000;
export const DETECTION_BACKGROUND_RETRY_MAX_MS = 30000;
export const DETECTION_BACKGROUND_MAX_RETRIES = 5;

export const DEFAULT_PROFILE_LIMITS: ProfileLimits = {
  detectMaxPages: 5,
  fillableMaxPages: 50,
  savedFormsMax: 3,
  fillLinksActiveMax: 1,
  fillLinkResponsesMax: 5,
  templateApiActiveMax: 1,
  templateApiRequestsMonthlyMax: 250,
  templateApiMaxPages: 25,
};
