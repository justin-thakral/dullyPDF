import { apiFetch, apiJsonFetch } from './apiConfig';

const DEFAULT_DETECTION_API = 'http://localhost:8000';

export function getDetectionApiBase(): string {
  const env = (import.meta as any)?.env;
  const raw = env?.VITE_DETECTION_API_URL || env?.VITE_SANDBOX_API_URL;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  const normalised = trimmed ? trimmed.replace(/\/+$/, '') : DEFAULT_DETECTION_API;
  return normalised || DEFAULT_DETECTION_API;
}

type DetectOptions = {
  useOpenAI?: boolean;
  pipeline?: 'sandbox' | 'commonforms';
};

export async function detectFields(
  file: File,
  options: DetectOptions = {},
): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);
  if (options.pipeline) {
    formData.append('pipeline', options.pipeline);
  }
  if (options.useOpenAI) {
    formData.append('use_openai', 'true');
  }

  const params = new URLSearchParams();
  if (options.useOpenAI) {
    params.set('openai', 'true');
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';

  const response = await apiFetch('POST', `${getDetectionApiBase()}/detect-fields${suffix}`, {
    body: formData,
  });

  return apiJsonFetch(response);
}
