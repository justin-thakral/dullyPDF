import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  clearWorkspaceResumeState,
  findMatchingWorkspaceResumeState,
  readWorkspaceResumeState,
  writeWorkspaceResumeState,
} from '../../../src/utils/workspaceResumeState';

describe('workspaceResumeState', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    window.sessionStorage.clear();
  });

  it('round-trips a saved form resume payload', () => {
    writeWorkspaceResumeState({
      version: 1,
      userId: 'user-1',
      route: { kind: 'saved-form', formId: 'saved-1' },
      currentPage: 2,
      scale: 1.25,
      detectSessionId: 'session-1',
      mappingSessionId: 'session-1',
      fieldCount: 5,
      pageCount: 3,
      updatedAtMs: 123,
    });

    expect(readWorkspaceResumeState()).toEqual({
      version: 1,
      userId: 'user-1',
      route: { kind: 'saved-form', formId: 'saved-1' },
      currentPage: 2,
      scale: 1.25,
      detectSessionId: 'session-1',
      mappingSessionId: 'session-1',
      fieldCount: 5,
      pageCount: 3,
      updatedAtMs: 123,
    });
  });

  it('matches only the same route and user id', () => {
    writeWorkspaceResumeState({
      version: 1,
      userId: 'user-1',
      route: { kind: 'group', groupId: 'group-1', templateId: 'saved-2' },
      currentPage: 1,
      scale: 1,
      detectSessionId: 'session-2',
      mappingSessionId: 'session-2',
      fieldCount: 2,
      pageCount: 1,
      updatedAtMs: Date.now(),
    });

    expect(findMatchingWorkspaceResumeState(
      { kind: 'group', groupId: 'group-1', templateId: 'saved-2' },
      'user-1',
    )?.detectSessionId).toBe('session-2');
    expect(findMatchingWorkspaceResumeState(
      { kind: 'group', groupId: 'group-1', templateId: 'saved-1' },
      'user-1',
    )).toBeNull();
    expect(findMatchingWorkspaceResumeState(
      { kind: 'group', groupId: 'group-1', templateId: 'saved-2' },
      'user-2',
    )).toBeNull();
  });

  it('clears persisted state', () => {
    writeWorkspaceResumeState({
      version: 1,
      userId: 'user-1',
      route: { kind: 'upload-root' },
      currentPage: null,
      scale: null,
      detectSessionId: null,
      mappingSessionId: null,
      fieldCount: null,
      pageCount: null,
      updatedAtMs: Date.now(),
    });

    clearWorkspaceResumeState();
    expect(readWorkspaceResumeState()).toBeNull();
  });
});
