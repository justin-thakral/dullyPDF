import { useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import { createRoot } from 'react-dom/client';
import { HeaderBar } from '../components/layout/HeaderBar';
import { Alert } from '../components/ui/Alert';
import { ConfirmDialog } from '../components/ui/Dialog';
import { useDialog } from '../hooks/useDialog';
import { useOpenAiPipeline } from '../hooks/useOpenAiPipeline';
import type { BannerNotice, PdfField } from '../types';
import { ApiService, type OpenAiRenameResult } from '../services/api';
import { resolveConfirmDialogResult } from '../utils/dialogResult';

type RenameHarnessConfig = {
  renameResponse?: OpenAiRenameResult;
};

type RenameHarnessState = {
  renameCalls: Array<Record<string, unknown>>;
  fields: Array<Pick<PdfField, 'id' | 'name' | 'type' | 'page'>>;
  checkboxRuleCount: number;
  bannerNotice: BannerNotice | null;
  openAiError: string | null;
};

type HarnessWindow = Window & {
  __PW_RENAME_CONFIG__?: RenameHarnessConfig;
  __PW_RENAME_CALLS__?: Array<Record<string, unknown>>;
  __getRenameHarnessState__?: () => RenameHarnessState;
};

const harnessWindow = window as HarnessWindow;

const INITIAL_FIELDS: PdfField[] = [
  {
    id: 'field-text-1',
    name: 'field_1',
    type: 'text',
    page: 1,
    rect: { x: 36, y: 72, width: 180, height: 24 },
  },
  {
    id: 'field-checkbox-1',
    name: 'field_2',
    type: 'checkbox',
    page: 1,
    rect: { x: 36, y: 120, width: 14, height: 14 },
  },
];

function cloneFields(fields: PdfField[]): PdfField[] {
  return fields.map((field) => ({
    ...field,
    rect: { ...field.rect },
  }));
}

function defaultRenameResponse() {
  return {
    success: true,
    fields: [
      {
        originalName: 'field_1',
        name: 'patient_first_name',
        renameConfidence: 0.96,
      },
      {
        originalName: 'field_2',
        name: 'patient_consent_yes',
        renameConfidence: 0.93,
        groupKey: 'patient_consent',
        optionKey: 'yes',
        optionLabel: 'Yes',
        groupLabel: 'Patient Consent',
      },
    ],
    checkboxRules: [
      {
        databaseField: 'patient_consent',
        groupKey: 'patient_consent',
        operation: 'yes_no' as const,
        trueOption: 'yes',
        falseOption: 'no',
        confidence: 0.91,
      },
    ],
  };
}

function recordRenameCall(payload: Record<string, unknown>): void {
  harnessWindow.__PW_RENAME_CALLS__ = [...(harnessWindow.__PW_RENAME_CALLS__ || []), payload];
}

export function RenameHarnessApp() {
  const dialog = useDialog();
  const [fields, setFields] = useState<PdfField[]>(() => cloneFields(INITIAL_FIELDS));
  const [detectSessionId, setDetectSessionId] = useState<string | null>('session_playwright_rename');
  const [mappingSessionId, setMappingSessionId] = useState<string | null>('session_playwright_rename');
  const fieldsRef = useRef<PdfField[]>(fields);
  const loadTokenRef = useRef(1);
  const pendingAutoActionsRef = useRef(null);
  const verifiedUser = useMemo(() => ({ uid: 'playwright-user', email: 'playwright@example.com' } as User), []);
  const renameConfig = harnessWindow.__PW_RENAME_CONFIG__ || {};
  const renameResponse = renameConfig.renameResponse || defaultRenameResponse();

  useEffect(() => {
    fieldsRef.current = fields;
  }, [fields]);

  useEffect(() => {
    const originalRenameFields = ApiService.renameFields;
    ApiService.renameFields = async (payload) => {
      recordRenameCall(payload as Record<string, unknown>);
      return renameResponse;
    };

    return () => {
      ApiService.renameFields = originalRenameFields;
    };
  }, [renameResponse]);

  const resetFieldHistory = (nextFields?: PdfField[]) => {
    const resolved = cloneFields(nextFields || fieldsRef.current);
    fieldsRef.current = resolved;
    setFields(resolved);
  };

  const updateFieldsWith = (updater: (prev: PdfField[]) => PdfField[]) => {
    const nextFields = cloneFields(updater(fieldsRef.current));
    fieldsRef.current = nextFields;
    setFields(nextFields);
  };

  const pipeline = useOpenAiPipeline({
    verifiedUser,
    fieldsRef,
    loadTokenRef,
    detectSessionId,
    setDetectSessionId,
    setMappingSessionId,
    activeSavedFormId: null,
    pageCount: 1,
    dataColumns: [],
    schemaId: null,
    pendingAutoActionsRef,
    setBannerNotice: dialog.setBannerNotice,
    requestConfirm: dialog.requestConfirm,
    resolveSourcePdfBytes: async () => new Uint8Array([1, 2, 3]),
    loadUserProfile: async () => null,
    resetFieldHistory,
    updateFieldsWith,
    setIdentifierKey: () => {},
    hasDocument: true,
    fieldsCount: fields.length,
    dataSourceKind: 'none',
    hasSchemaOrPending: false,
  });

  useEffect(() => {
    harnessWindow.__getRenameHarnessState__ = () => ({
      renameCalls: Array.from(harnessWindow.__PW_RENAME_CALLS__ || []),
      fields: fieldsRef.current.map((field) => ({
        id: field.id,
        name: field.name,
        type: field.type,
        page: field.page,
      })),
      checkboxRuleCount: pipeline.checkboxRules.length,
      bannerNotice: dialog.bannerNotice,
      openAiError: pipeline.openAiError,
    });

    return () => {
      delete harnessWindow.__getRenameHarnessState__;
    };
  }, [dialog.bannerNotice, pipeline.checkboxRules.length, pipeline.openAiError]);

  const confirmDialog = (() => {
    if (dialog.dialogRequest?.kind !== 'confirm') {
      return null;
    }
    const cancelResult = resolveConfirmDialogResult(dialog.dialogRequest, 'cancelResult', false);
    const dismissResult = resolveConfirmDialogResult(dialog.dialogRequest, 'dismissResult', cancelResult);
    return (
      <ConfirmDialog
        open
        title={dialog.dialogRequest.title}
        description={dialog.dialogRequest.message}
        confirmLabel={dialog.dialogRequest.confirmLabel}
        cancelLabel={dialog.dialogRequest.cancelLabel}
        tone={dialog.dialogRequest.tone}
        onConfirm={() => dialog.resolveDialog(true)}
        onCancel={() => dialog.resolveDialog(cancelResult)}
        onClose={() => dialog.resolveDialog(dismissResult)}
      />
    );
  })();

  return (
    <div style={{ padding: '24px', background: '#eef3f8', minHeight: '100vh' }}>
      <HeaderBar
        pageCount={1}
        currentPage={1}
        scale={1}
        userEmail="playwright@example.com"
        onScaleChange={() => {}}
        onNavigateHome={() => {}}
        onRename={pipeline.handleRename}
        canRename={pipeline.canRename}
        renameInProgress={pipeline.renameInProgress}
        hasRenamedFields={pipeline.hasRenamedFields}
        renameDisabledReason={pipeline.renameDisabledReason}
        canMapSchema={false}
        canRenameAndMap={false}
      />
      <main style={{ padding: '24px 12px' }}>
        <section aria-label="Rename harness state" style={{ maxWidth: '720px' }}>
          <h2>Rename Harness</h2>
          <p>This harness mounts the real OpenAI rename hook and header button with a mocked rename API.</p>
          {dialog.bannerNotice ? (
            <Alert tone={dialog.bannerNotice.tone} variant="banner" message={dialog.bannerNotice.message} />
          ) : null}
          {pipeline.openAiError ? <Alert tone="error" message={pipeline.openAiError} /> : null}
          <p data-testid="mapping-session-id">Mapping session: {mappingSessionId || 'none'}</p>
          <p data-testid="checkbox-rule-count">Checkbox rules: {pipeline.checkboxRules.length}</p>
          <ul aria-label="Renamed fields">
            {fields.map((field) => (
              <li key={field.id} data-field-id={field.id}>
                {field.name} ({field.type})
              </li>
            ))}
          </ul>
        </section>
      </main>
      {confirmDialog}
    </div>
  );
}

harnessWindow.__PW_RENAME_CALLS__ = [];
document.body.innerHTML = '<div id="pw-rename-root"></div>';
createRoot(document.getElementById('pw-rename-root') as HTMLElement).render(<RenameHarnessApp />);
