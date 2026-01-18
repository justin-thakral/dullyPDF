/**
 * Detection API helpers for field extraction.
 */
import { apiFetch, apiJsonFetch } from './apiConfig';

const DEFAULT_DETECTION_API = 'http://localhost:8000';

/**
 * Resolve the detection API base URL from env with fallback.
 */
export function getDetectionApiBase(): string {
  const env = (import.meta as any)?.env;
  const raw = env?.VITE_DETECTION_API_URL || env?.VITE_SANDBOX_API_URL;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  const normalised = trimmed ? trimmed.replace(/\/+$/, '') : DEFAULT_DETECTION_API;
  return normalised || DEFAULT_DETECTION_API;
}

type DetectOptions = {
  pipeline?: 'commonforms';
};

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

  const response = await apiFetch('POST', `${getDetectionApiBase()}/detect-fields`, {
    body: formData,
  });

  return apiJsonFetch(response);
}
