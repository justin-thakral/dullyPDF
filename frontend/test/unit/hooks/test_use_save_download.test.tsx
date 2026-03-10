import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useSaveDownload, type UseSaveDownloadDeps } from '../../../src/hooks/useSaveDownload';

const materializeFormPdfMock = vi.hoisted(() => vi.fn());
const saveFormToProfileMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    materializeFormPdf: materializeFormPdfMock,
    saveFormToProfile: saveFormToProfileMock,
  },
}));

function createDeps(overrides: Partial<UseSaveDownloadDeps> = {}): UseSaveDownloadDeps {
  return {
    pdfDoc: {
      getData: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
    } as any,
    sourceFile: new File(['pdf'], 'template.pdf', { type: 'application/pdf' }),
    sourceFileName: 'template.pdf',
    fields: [{
      id: 'field-1',
      name: 'Field 1',
      type: 'text',
      page: 1,
      rect: { x: 10, y: 10, width: 100, height: 20 },
      value: null,
    }],
    pageSizes: {
      1: { width: 612, height: 792 },
    },
    pageCount: 1,
    checkboxRules: [],
    checkboxHints: [],
    textTransformRules: [],
    hasRenamedFields: false,
    hasMappedSchema: false,
    mappingSessionId: 'mapping-session-1',
    activeSavedFormId: 'saved-form-1',
    activeSavedFormName: 'Template A',
    activeGroupId: 'group-1',
    activeGroupName: 'Admissions',
    savedFormsCount: 1,
    savedFormsMax: 10,
    verifiedUser: { uid: 'user-1' } as any,
    setBannerNotice: vi.fn(),
    setLoadError: vi.fn(),
    requestConfirm: vi.fn().mockResolvedValue(true),
    requestPrompt: vi.fn().mockResolvedValue('Copy Name'),
    refreshSavedForms: vi.fn().mockResolvedValue(undefined),
    refreshGroups: vi.fn().mockResolvedValue(undefined),
    refreshProfile: vi.fn().mockResolvedValue(undefined),
    setActiveSavedFormId: vi.fn(),
    setActiveSavedFormName: vi.fn(),
    markGroupTemplatesPersisted: vi.fn(),
    queueSaveAfterLimit: vi.fn(),
    allowAnonymousDownload: false,
    onSaveSuccess: vi.fn(),
    ...overrides,
  };
}

function renderHookHarness(deps: UseSaveDownloadDeps) {
  let latest: ReturnType<typeof useSaveDownload> | null = null;

  function Harness() {
    latest = useSaveDownload(deps);
    return null;
  }

  render(<Harness />);

  return {
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useSaveDownload', () => {
  beforeEach(() => {
    materializeFormPdfMock.mockReset();
    saveFormToProfileMock.mockReset();
  });

  it('blocks save-new-copy when a group template is open and only allows overwrite', async () => {
    const deps = createDeps({
      requestConfirm: vi.fn().mockResolvedValue(false),
    });
    const hook = renderHookHarness(deps);

    await act(async () => {
      await hook.current.handleSaveToProfile();
    });

    expect(deps.requestConfirm).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Overwrite group template?',
    }));
    expect(deps.requestPrompt).not.toHaveBeenCalled();
    expect(materializeFormPdfMock).not.toHaveBeenCalled();
    expect(saveFormToProfileMock).not.toHaveBeenCalled();
  });

  it('overwrites the active group template and marks it persisted after save', async () => {
    materializeFormPdfMock.mockResolvedValue(new Blob(['generated']));
    saveFormToProfileMock.mockResolvedValue({ id: 'saved-form-1', name: 'Template A' });
    const deps = createDeps();
    const hook = renderHookHarness(deps);

    await act(async () => {
      await hook.current.handleSaveToProfile();
    });

    expect(deps.requestConfirm).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Overwrite group template?',
    }));
    expect(deps.requestPrompt).not.toHaveBeenCalled();
    expect(saveFormToProfileMock).toHaveBeenCalledWith(
      expect.any(Blob),
      'Template A',
      'mapping-session-1',
      'saved-form-1',
      [],
      [],
      [],
      expect.objectContaining({
        version: 1,
        pageCount: 1,
        hasRenamedFields: false,
        hasMappedSchema: false,
      }),
    );
    expect(deps.markGroupTemplatesPersisted).toHaveBeenCalledWith(['saved-form-1']);
  });
});
