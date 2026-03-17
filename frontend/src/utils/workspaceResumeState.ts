import type { WorkspaceBrowserRoute } from './workspaceRoutes';
import { areWorkspaceBrowserRoutesEqual } from './workspaceRoutes';

const WORKSPACE_RESUME_STORAGE_KEY = 'dullypdf.workspaceResumeState';
const WORKSPACE_RESUME_VERSION = 1;

type PersistedWorkspaceRoute = Exclude<WorkspaceBrowserRoute, { kind: 'homepage' }>;

export type WorkspaceResumeState = {
  version: 1;
  userId: string;
  route: PersistedWorkspaceRoute;
  currentPage: number | null;
  scale: number | null;
  detectSessionId: string | null;
  mappingSessionId: string | null;
  fieldCount: number | null;
  pageCount: number | null;
  updatedAtMs: number;
};

function getSessionStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function isPersistedWorkspaceRoute(value: unknown): value is PersistedWorkspaceRoute {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const route = value as Record<string, unknown>;
  const kind = route.kind;
  if (kind === 'upload-root' || kind === 'ui-root' || kind === 'profile') {
    return true;
  }
  if (kind === 'saved-form') {
    return typeof route.formId === 'string' && route.formId.trim().length > 0;
  }
  if (kind === 'group') {
    return (
      typeof route.groupId === 'string' &&
      route.groupId.trim().length > 0 &&
      (route.templateId === null || typeof route.templateId === 'string')
    );
  }
  return false;
}

function normalizeNullableString(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function normalizeNullableNumber(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return value;
}

export function readWorkspaceResumeState(): WorkspaceResumeState | null {
  const storage = getSessionStorage();
  if (!storage) {
    return null;
  }
  const raw = storage.getItem(WORKSPACE_RESUME_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed.version !== WORKSPACE_RESUME_VERSION) {
      return null;
    }
    if (typeof parsed.userId !== 'string' || !parsed.userId.trim()) {
      return null;
    }
    if (!isPersistedWorkspaceRoute(parsed.route)) {
      return null;
    }
    const updatedAtMs = normalizeNullableNumber(parsed.updatedAtMs);
    if (updatedAtMs === null) {
      return null;
    }
    return {
      version: 1,
      userId: parsed.userId,
      route: parsed.route,
      currentPage: normalizeNullableNumber(parsed.currentPage),
      scale: normalizeNullableNumber(parsed.scale),
      detectSessionId: normalizeNullableString(parsed.detectSessionId),
      mappingSessionId: normalizeNullableString(parsed.mappingSessionId),
      fieldCount: normalizeNullableNumber(parsed.fieldCount),
      pageCount: normalizeNullableNumber(parsed.pageCount),
      updatedAtMs,
    };
  } catch {
    return null;
  }
}

export function writeWorkspaceResumeState(state: WorkspaceResumeState): void {
  const storage = getSessionStorage();
  if (!storage) {
    return;
  }
  storage.setItem(WORKSPACE_RESUME_STORAGE_KEY, JSON.stringify(state));
}

export function clearWorkspaceResumeState(): void {
  const storage = getSessionStorage();
  if (!storage) {
    return;
  }
  storage.removeItem(WORKSPACE_RESUME_STORAGE_KEY);
}

export function findMatchingWorkspaceResumeState(
  route: WorkspaceBrowserRoute,
  userId: string | null | undefined,
): WorkspaceResumeState | null {
  if (!userId || route.kind === 'homepage') {
    return null;
  }
  const resumeState = readWorkspaceResumeState();
  if (!resumeState || resumeState.userId !== userId) {
    return null;
  }
  if (!areWorkspaceBrowserRoutesEqual(resumeState.route, route)) {
    return null;
  }
  return resumeState;
}
