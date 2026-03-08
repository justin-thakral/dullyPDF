/**
 * Detection response parsing and status helpers.
 */
import type { FieldType, PdfField } from '../types';
import { parseConfidence } from './confidence';
import { makeId } from './fields';
import { rectToBox } from './coords';

export const DETECTION_WAITING_DETECTOR_MESSAGE = 'Waiting for detector to start...';
export const DETECTION_RUNNING_DETECTOR_MESSAGE = 'Detecting fields...';
export const DETECTION_WAITING_STANDARD_CPU_MESSAGE = 'Waiting for standard CPU to start...';
export const DETECTION_RUNNING_STANDARD_CPU_MESSAGE = 'Detecting fields on the standard CPU...';
export const DETECTION_RUNNING_HEAVY_CPU_MESSAGE = 'Detecting fields on the high-capacity CPU...';
export const DETECTION_WAITING_GPU_MESSAGE = 'Waiting for GPU detector to start...';
export const DETECTION_RUNNING_GPU_MESSAGE = 'Detecting fields on the GPU...';

type DetectionRuntime = 'cpu' | 'gpu' | 'unknown';

function resolveDetectionRuntime(payload: any): DetectionRuntime {
  const serviceUrl = String(payload?.detectionServiceUrl || '').trim().toLowerCase();
  if (!serviceUrl) return 'unknown';
  if (serviceUrl.includes('-gpu')) return 'gpu';
  return 'cpu';
}

/**
 * Normalize backend field types into UI field categories.
 */
export function normaliseFieldType(raw: unknown): FieldType {
  const candidate = String(raw || '').toLowerCase();
  if (candidate === 'checkbox') return 'checkbox';
  if (candidate === 'signature') return 'signature';
  if (candidate === 'date') return 'date';
  return 'text';
}

/**
 * Convert backend detection payloads into client field models.
 */
export function mapDetectionFields(payload: any): PdfField[] {
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

export function parseIsoTimestamp(value: unknown): number | null {
  if (typeof value !== 'string' || !value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export function resolveDetectionStatusMessage(
  payload: any,
  queueWaitThresholdMs: number,
): string | null {
  const status = String(payload?.status || '').toLowerCase();
  if (!status) return null;
  const profile = String(payload?.detectionProfile || '').toLowerCase();
  const runtime = resolveDetectionRuntime(payload);
  const profileLabel =
    runtime === 'gpu'
      ? 'GPU'
      : runtime === 'cpu'
        ? profile === 'heavy'
          ? 'high-capacity CPU'
          : profile === 'light'
            ? 'standard CPU'
            : 'CPU'
        : 'detector';
  if (status === 'queued') {
    const startedAt = parseIsoTimestamp(payload?.detectionStartedAt);
    if (!startedAt) {
      const queuedAt = parseIsoTimestamp(payload?.detectionQueuedAt);
      if (queuedAt && Date.now() - queuedAt > queueWaitThresholdMs) {
        return `Waiting for an available ${profileLabel}...`;
      }
      if (runtime === 'gpu') return DETECTION_WAITING_GPU_MESSAGE;
      if (runtime === 'cpu' && profile === 'light') return DETECTION_WAITING_STANDARD_CPU_MESSAGE;
      if (runtime === 'unknown') return DETECTION_WAITING_DETECTOR_MESSAGE;
      return `Waiting for ${profileLabel} to start...`;
    }
  }
  if (status === 'running') {
    if (runtime === 'gpu') return DETECTION_RUNNING_GPU_MESSAGE;
    if (runtime === 'cpu' && profile === 'light') return DETECTION_RUNNING_STANDARD_CPU_MESSAGE;
    if (runtime === 'cpu' && profile === 'heavy') return DETECTION_RUNNING_HEAVY_CPU_MESSAGE;
    if (runtime === 'cpu') return 'Detecting fields on the CPU...';
    return DETECTION_RUNNING_DETECTOR_MESSAGE;
  }
  return null;
}
