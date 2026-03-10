/**
 * Detection API helpers for field extraction.
 */
import { apiFetch, apiJsonFetch } from './apiConfig';

const DEFAULT_DETECTION_API = 'http://localhost:8000';
const DETECTION_POLL_INTERVAL_MS = 1500;
const DEFAULT_DETECTION_POLL_TIMEOUT_MS = 120000;
const DETECTION_TTL_TOUCH_INTERVAL_MS = 60000;

function resolveDetectionPollTimeoutMs(): number {
  const env = import.meta.env;
  const raw = env?.VITE_DETECTION_POLL_TIMEOUT_MS;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && parsed >= 0) {
    return parsed;
  }
  return DEFAULT_DETECTION_POLL_TIMEOUT_MS;
}

const DETECTION_POLL_TIMEOUT_MS = resolveDetectionPollTimeoutMs();

type PollOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
  onStatus?: (payload: any) => void;
};

/**
 * Resolve the detection API base URL from env with fallback.
 */
export function getDetectionApiBase(): string {
  const env = import.meta.env;
  const raw = env?.VITE_DETECTION_API_URL || env?.VITE_SANDBOX_API_URL;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  const normalised = trimmed ? trimmed.replace(/\/+$/, '') : DEFAULT_DETECTION_API;
  return normalised || DEFAULT_DETECTION_API;
}

type DetectOptions = {
  pipeline?: 'commonforms';
  prewarmRename?: boolean;
  prewarmRemap?: boolean;
  signal?: AbortSignal;
  onStatus?: (payload: any) => void;
};

class DetectionFailedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DetectionFailedError';
  }
}

/**
 * Upload a PDF and request field detection.
 */
export async function detectFields(
  file: File,
  options: DetectOptions = {},
): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);
  if (options.pipeline) {
    formData.append('pipeline', options.pipeline);
  }
  if (options.prewarmRename) {
    formData.append('prewarmRename', 'true');
  }
  if (options.prewarmRemap) {
    formData.append('prewarmRemap', 'true');
  }

  const response = await apiFetch('POST', `${getDetectionApiBase()}/detect-fields`, {
    body: formData,
    signal: options.signal,
  });
  const startPayload = await apiJsonFetch(response);
  const sessionId = startPayload?.sessionId;
  const status = String(startPayload?.status || '').toLowerCase();
  if (!sessionId) {
    return startPayload;
  }
  if (status === 'complete' && Array.isArray(startPayload?.fields)) {
    return startPayload;
  }

  // Important: do not mask polling errors as "timed out".
  // Auth failures and backend errors should surface so the UI can prompt re-auth / show a real error.
  return pollDetection(sessionId, startPayload, {
    onStatus: options.onStatus,
    signal: options.signal,
  });
}

export async function pollDetectionStatus(
  sessionId: string,
  options: PollOptions = {},
): Promise<any> {
  return pollDetection(sessionId, { sessionId, status: 'running' }, options);
}

export async function fetchDetectionStatus(sessionId: string): Promise<any> {
  const response = await apiFetch('GET', `${getDetectionApiBase()}/detect-fields/${sessionId}`);
  return apiJsonFetch(response);
}

async function pollDetection(
  sessionId: string,
  fallbackPayload: any,
  options: PollOptions = {},
): Promise<any> {
  const timeoutMs = options.timeoutMs ?? DETECTION_POLL_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  let attempt = 0;
  let lastPayload: any = fallbackPayload;
  let nextTouchAt = Date.now();
  if (options.onStatus && fallbackPayload) {
    options.onStatus(fallbackPayload);
  }
  while (Date.now() < deadline) {
    if (options.signal?.aborted) {
      throw new DOMException('Detection polling aborted.', 'AbortError');
    }
    if (Date.now() >= nextTouchAt) {
      void touchDetectionSession(sessionId);
      nextTouchAt = Date.now() + DETECTION_TTL_TOUCH_INTERVAL_MS;
    }
    const response = await apiFetch('GET', `${getDetectionApiBase()}/detect-fields/${sessionId}`, {
      signal: options.signal,
    });
    const payload = await apiJsonFetch(response);
    lastPayload = payload;
    if (options.onStatus) {
      options.onStatus(payload);
    }
    const status = String(payload?.status || '').toLowerCase();
    if (status === 'complete') {
      return payload;
    }
    if (status === 'failed') {
      const message = payload?.error || 'Detection failed';
      throw new DetectionFailedError(String(message));
    }
    attempt += 1;
    await sleep(Math.min(DETECTION_POLL_INTERVAL_MS * attempt, 6000), options.signal);
  }
  const status = String(lastPayload?.status || '').toLowerCase();
  const basePayload =
    lastPayload && typeof lastPayload === 'object' ? lastPayload : { sessionId, status };
  return {
    ...basePayload,
    status: status || 'running',
    timedOut: true,
  };
}

function sleep(durationMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      cleanup();
      resolve();
    }, durationMs);
    const cleanup = () => {
      clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(new DOMException('Detection polling aborted.', 'AbortError'));
    };
    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function touchDetectionSession(sessionId: string): Promise<void> {
  try {
    await apiFetch('POST', `${getDetectionApiBase()}/api/sessions/${encodeURIComponent(sessionId)}/touch`);
  } catch {
    // Best-effort; detection polling should continue even if touch fails.
  }
}
