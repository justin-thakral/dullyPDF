import { getAuthToken } from './authTokenStore';

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
};

export async function detectFields(
  file: File,
  options: DetectOptions = {},
): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);

  const params = new URLSearchParams();
  if (options.useOpenAI) {
    params.set('openai', 'true');
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';

  const response = await fetch(`${getDetectionApiBase()}/detect-fields${suffix}`, {
    method: 'POST',
    headers: (() => {
      const headers = new Headers();
      const token = getAuthToken();
      if (token) headers.set('Authorization', `Bearer ${token}`);
      return headers;
    })(),
    body: formData,
  });

  if (!response.ok) {
    let message = `Field detection failed (${response.status})`;
    try {
      const data = await response.json();
      if (data?.detail) message = data.detail;
      if (data?.error) message = data.error;
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }

  return response.json();
}
