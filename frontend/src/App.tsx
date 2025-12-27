import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import './App.css';
import type { FieldType, PageSize, PdfField } from './types';
import { createField, ensureUniqueFieldName, makeId } from './utils/fields';
import { extractFieldsFromPdf, loadPageSizes, loadPdfFromFile } from './utils/pdf';
import { detectFields } from './services/detectionApi';
import { Auth } from './services/auth';
import { setAuthToken } from './services/authTokenStore';
import { ApiService } from './api';
import { DB } from './services/db';
import Homepage from './components/pages/Homepage';
import LoginPage from './components/pages/LoginPage';
import { HeaderBar } from './components/layout/HeaderBar';
import LegacyHeader from './components/layout/LegacyHeader';
import ConnectDB from './components/features/ConnectDB';
import FieldMapper from './components/features/FieldMapper';
import { FieldInspectorPanel } from './components/panels/FieldInspectorPanel';
import { FieldListPanel } from './components/panels/FieldListPanel';
import { PdfViewer } from './components/viewer/PdfViewer';
import UploadComponent from './components/features/UploadComponent';

const DEBUG_UI = false;

function debugLog(...args: unknown[]) {
  if (!DEBUG_UI) return;
  console.log('[dullypdf-ui]', ...args);
}

function normaliseFieldType(raw: unknown): FieldType {
  const candidate = String(raw || '').toLowerCase();
  if (candidate === 'checkbox') return 'checkbox';
  if (candidate === 'signature') return 'signature';
  if (candidate === 'date') return 'date';
  return 'text';
}

function rectToBox(rect: unknown): { x: number; y: number; width: number; height: number } | null {
  if (!rect) return null;
  if (Array.isArray(rect) && rect.length === 4) {
    const [x1, y1, x2, y2] = rect.map((value) => Number(value));
    if ([x1, y1, x2, y2].some((val) => Number.isNaN(val))) return null;
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
  }
  if (typeof rect === 'object') {
    const candidate = rect as { x?: number; y?: number; width?: number; height?: number };
    if (
      typeof candidate.x === 'number' &&
      typeof candidate.y === 'number' &&
      typeof candidate.width === 'number' &&
      typeof candidate.height === 'number'
    ) {
      return {
        x: candidate.x,
        y: candidate.y,
        width: candidate.width,
        height: candidate.height,
      };
    }
  }
  return null;
}

function normaliseFormName(raw: string | null | undefined): string {
  const trimmed = String(raw || '').trim();
  if (!trimmed.length) return 'Saved form';
  return trimmed.replace(/\.pdf$/i, '');
}

function mapDetectionFields(payload: any): PdfField[] {
  const rawFields = Array.isArray(payload?.fields) ? payload.fields : [];
  return rawFields
    .map((field: any, index: number) => {
      const rect = rectToBox(field?.rect || field?.bbox);
      if (!rect) return null;
      return {
        id: makeId(),
        name: String(field?.name || `field_${index + 1}`),
        type: normaliseFieldType(field?.type),
        page: Number(field?.page) || 1,
        rect,
      } as PdfField;
    })
    .filter(Boolean) as PdfField[];
}

function App() {
  const [authReady, setAuthReady] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showHomepage, setShowHomepage] = useState(true);

  // Keep document metadata and field geometry together so the viewer and inspector stay in sync.
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  // Page sizes are cached by page number to avoid recomputing viewports on every render.
  const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [pendingPageJump, setPendingPageJump] = useState<number | null>(null);
  // All fields live in one array so the list and page overlay share a single source of truth.
  const [fields, setFields] = useState<PdfField[]>([]);
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savedForms, setSavedForms] = useState<Array<{ id: string; name: string; createdAt: string }>>([]);
  const [activeSavedFormId, setActiveSavedFormId] = useState<string | null>(null);
  const [activeSavedFormName, setActiveSavedFormName] = useState<string | null>(null);
  const [deletingFormId, setDeletingFormId] = useState<string | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<string | null>(null);
  const [mappingInProgress, setMappingInProgress] = useState(false);
  const [mapDbInProgress, setMapDbInProgress] = useState(false);
  const [dbError, setDbError] = useState<string | null>(null);
  const [connId, setConnId] = useState<string | null>(null);
  const [showConnectDb, setShowConnectDb] = useState(false);
  const [showFieldMapper, setShowFieldMapper] = useState(false);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceFileName, setSourceFileName] = useState<string | null>(null);
  const [saveInProgress, setSaveInProgress] = useState(false);
  const [downloadInProgress, setDownloadInProgress] = useState(false);
  const loadTokenRef = useRef(0);

  useEffect(() => {
    const unsubscribe = Auth.onAuthStateChanged(async (user) => {
      setAuthUser(user);
      setAuthReady(true);

      if (!user) {
        setSavedForms([]);
        return;
      }

      try {
        const token = await user.getIdToken();
        setAuthToken(token);
        const forms = await ApiService.getSavedForms();
        setSavedForms(forms || []);
      } catch (error) {
        console.error('Failed to load saved forms', error);
      }
    });
    return () => unsubscribe();
  }, []);

  const clearWorkspace = useCallback(() => {
    setPdfDoc(null);
    setPageSizes({});
    setPageCount(0);
    setCurrentPage(1);
    setScale(1);
    setPendingPageJump(null);
    setFields([]);
    setSelectedFieldId(null);
    setMappingSessionId(null);
    setMappingInProgress(false);
    setDbError(null);
    setConnId(null);
    setShowConnectDb(false);
    setShowFieldMapper(false);
    setSourceFile(null);
    setSourceFileName(null);
    setSaveInProgress(false);
    setActiveSavedFormId(null);
    setActiveSavedFormName(null);
  }, []);

  const ensureMappingSessionId = useCallback(() => {
    if (mappingSessionId) return mappingSessionId;
    const nextId = crypto.randomUUID();
    setMappingSessionId(nextId);
    return nextId;
  }, [mappingSessionId]);

  const handleSignOut = useCallback(async () => {
    await Auth.signOut();
    clearWorkspace();
    setSavedForms([]);
    setShowHomepage(true);
  }, [clearWorkspace]);

  const handleNavigateHome = useCallback(() => {
    clearWorkspace();
    setLoadError(null);
    setShowHomepage(true);
  }, [clearWorkspace]);

  const handleDetectUpload = useCallback(
    async (file: File) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      const shouldUseOpenAI = window.confirm(
        'Enable OpenAI rename? This uses AI to refine field names and remove low-confidence candidates.',
      );

      setIsProcessing(true);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(crypto.randomUUID());
      setDbError(null);
      setSourceFile(file);
      setSourceFileName(file.name);
      setActiveSavedFormId(null);
      setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;

        let detectedFields: PdfField[] = [];

        try {
          const detection = await detectFields(file, { useOpenAI: shouldUseOpenAI });
          if (detection?.openaiError) {
            debugLog('OpenAI rename failed', detection.openaiError);
          }
          detectedFields = mapDetectionFields(detection);
          debugLog('Field detection returned', { total: detectedFields.length });
        } catch (error) {
          debugLog('Field detection failed', error);
        }

        if (!detectedFields.length) {
          try {
            detectedFields = await extractFieldsFromPdf(doc);
            debugLog('Fallback PDF field extraction returned', { total: detectedFields.length });
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
          }
        }

        if (loadTokenRef.current !== loadToken) return;
        setPdfDoc(doc);
        setPageSizes(sizes);
        setPageCount(doc.numPages);
        setCurrentPage(1);
        setScale(1);
        setPendingPageJump(null);
        setFields(detectedFields);
        setSelectedFieldId(null);
        setIsProcessing(false);
        debugLog('Loaded PDF', { name: file.name, pages: doc.numPages, fields: detectedFields.length });
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        clearWorkspace();
        setIsProcessing(false);
        setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [clearWorkspace],
  );

  const handleFillableUpload = useCallback(
    async (file: File) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      setIsProcessing(true);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(crypto.randomUUID());
      setDbError(null);
      setSourceFile(file);
      setSourceFileName(file.name);
      setActiveSavedFormId(null);
      setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        setPdfDoc(doc);
        setPageSizes(sizes);
        setPageCount(doc.numPages);
        setCurrentPage(1);
        setScale(1);
        setPendingPageJump(null);
        setFields([]);
        setSelectedFieldId(null);
        setIsProcessing(false);

        void (async () => {
          let existingFields: PdfField[] = [];

          try {
            existingFields = await extractFieldsFromPdf(doc);
            debugLog('Extracted existing PDF fields', { total: existingFields.length });
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
          }

          if (loadTokenRef.current !== loadToken) return;
          setFields(existingFields);
          setSelectedFieldId(null);
          debugLog('Loaded fillable PDF', { name: file.name, pages: doc.numPages, fields: existingFields.length });
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        clearWorkspace();
        setIsProcessing(false);
        setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [clearWorkspace],
  );

  const handleSelectSavedForm = useCallback(
    async (formId: string) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      setIsProcessing(true);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(crypto.randomUUID());
      setDbError(null);

      try {
        const savedMeta = await ApiService.loadSavedForm(formId);
        const blob = await ApiService.downloadSavedForm(formId);
        const name = savedMeta?.name || 'saved-form.pdf';
        const file = new File([blob], name, { type: 'application/pdf' });
        setSourceFile(file);
        setSourceFileName(name);
        const doc = await loadPdfFromFile(file);
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        setPdfDoc(doc);
        setPageSizes(sizes);
        setPageCount(doc.numPages);
        setCurrentPage(1);
        setScale(1);
        setPendingPageJump(null);
        setFields([]);
        setSelectedFieldId(null);
        setIsProcessing(false);
        setActiveSavedFormId(formId);
        setActiveSavedFormName(savedMeta?.name || null);

        void (async () => {
          let existingFields: PdfField[] = [];

          try {
            existingFields = await extractFieldsFromPdf(doc);
            debugLog('Extracted saved form fields', { total: existingFields.length });
          } catch (error) {
            debugLog('Failed to extract saved form fields', error);
          }

          if (loadTokenRef.current !== loadToken) return;
          setFields(existingFields);
          setSelectedFieldId(null);
          debugLog('Loaded saved form', { name, pages: doc.numPages, fields: existingFields.length });
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load saved form.';
        clearWorkspace();
        setIsProcessing(false);
        setLoadError(message);
        debugLog('Failed to load saved form', message);
      }
    },
    [clearWorkspace],
  );

  const handleDeleteSavedForm = useCallback(
    async (formId: string) => {
      const target = savedForms.find((form) => form.id === formId);
      const name = target?.name ? `"${target.name}"` : 'this saved form';
      const confirmDelete = window.confirm(`Delete ${name}? This removes it from your saved forms.`);
      if (!confirmDelete) return;

      setDeletingFormId(formId);
      try {
        await ApiService.deleteSavedForm(formId);
        setSavedForms((prev) => prev.filter((form) => form.id !== formId));
        if (formId === activeSavedFormId) {
          setActiveSavedFormId(null);
          setActiveSavedFormName(null);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to delete saved form.';
        setLoadError(message);
        debugLog('Failed to delete saved form', message);
      } finally {
        setDeletingFormId(null);
      }
    },
    [activeSavedFormId, savedForms],
  );

  const handleSaveToProfile = useCallback(async () => {
    if (!pdfDoc) {
      setLoadError('No PDF is loaded to save.');
      return;
    }
    if (!authUser) {
      setLoadError('Sign in to save this form to your profile.');
      return;
    }
    setLoadError(null);
    const defaultName = normaliseFormName(activeSavedFormName || sourceFileName || sourceFile?.name);
    const promptForName = () => {
      const raw = window.prompt('Name this saved form:', defaultName);
      if (raw === null) return null;
      const trimmed = raw.trim();
      if (!trimmed) {
        setLoadError('A form name is required to save.');
        return null;
      }
      return normaliseFormName(trimmed);
    };

    let saveName = defaultName;
    let shouldOverwrite = false;
    if (activeSavedFormId) {
      const overwrite = window.confirm(
        'This form is already saved. Click OK to overwrite it, or Cancel to save a new copy.',
      );
      if (overwrite) {
        shouldOverwrite = true;
      } else {
        const nextName = promptForName();
        if (!nextName) return;
        saveName = nextName;
      }
    } else {
      const nextName = promptForName();
      if (!nextName) return;
      saveName = nextName;
    }

    const deleteAfterSaveId = shouldOverwrite ? activeSavedFormId : null;
    setSaveInProgress(true);
    try {
      let blob: Blob;
      if (sourceFile) {
        blob = sourceFile;
      } else {
        const data = await pdfDoc.getData();
        blob = new Blob([data], { type: 'application/pdf' });
      }
      const generatedBlob = await ApiService.materializeFormPdf(blob, fields);
      const payload = await ApiService.saveFormToProfile(generatedBlob, saveName, mappingSessionId || undefined);
      if (deleteAfterSaveId && payload?.id && payload.id !== deleteAfterSaveId) {
        await ApiService.deleteSavedForm(deleteAfterSaveId);
      }
      setActiveSavedFormId(payload?.id || null);
      setActiveSavedFormName(saveName);
      const forms = await ApiService.getSavedForms();
      setSavedForms(forms || []);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to save form to profile.';
      setLoadError(message);
      debugLog('Failed to save form', message);
    } finally {
      setSaveInProgress(false);
    }
  }, [
    activeSavedFormId,
    activeSavedFormName,
    authUser,
    fields,
    mappingSessionId,
    pdfDoc,
    sourceFile,
    sourceFileName,
  ]);

  const handleDownload = useCallback(async () => {
    if (!pdfDoc) {
      setLoadError('No PDF is loaded to download.');
      return;
    }
    if (!authUser) {
      setLoadError('Sign in to download this form.');
      return;
    }
    setLoadError(null);
    setDownloadInProgress(true);
    try {
      let blob: Blob;
      if (sourceFile) {
        blob = sourceFile;
      } else {
        const data = await pdfDoc.getData();
        blob = new Blob([data], { type: 'application/pdf' });
      }
      const generatedBlob = await ApiService.materializeFormPdf(blob, fields);
      const baseName = normaliseFormName(activeSavedFormName || sourceFileName || sourceFile?.name);
      const filename = `${baseName}-fillable.pdf`;
      const url = URL.createObjectURL(generatedBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to download form.';
      setLoadError(message);
      debugLog('Failed to download form', message);
    } finally {
      setDownloadInProgress(false);
    }
  }, [activeSavedFormName, authUser, fields, pdfDoc, sourceFile, sourceFileName]);

  const applyRenameMap = useCallback((renameMap: Map<string, string>) => {
    if (!renameMap.size) return;

    setFields((prev) => {
      // Track existing names to avoid collisions when applying AI rename suggestions.
      const existingNames = new Set(prev.map((field) => field.name));
      return prev.map((field) => {
        const desiredName = renameMap.get(field.name);
        if (!desiredName || desiredName === field.name) {
          return field;
        }

        existingNames.delete(field.name);
        const uniqueName = ensureUniqueFieldName(desiredName, existingNames);
        existingNames.add(uniqueName);

        return {
          ...field,
          name: uniqueName,
        };
      });
    });
  }, []);

  const handleManualRename = useCallback(
    (oldName: string, newName: string) => {
      const renameMap = new Map<string, string>([[oldName, newName]]);
      applyRenameMap(renameMap);
    },
    [applyRenameMap],
  );

  const applyAiMappings = useCallback(
    async (databaseFields: string[]): Promise<boolean> => {
      if (!databaseFields.length) {
        setDbError('No database fields available for mapping.');
        return false;
      }

      if (!fields.length) {
        setDbError('No PDF fields available to map.');
        return false;
      }

      setDbError(null);
      try {
        const sessionId = ensureMappingSessionId();
        const pdfFormFields = fields.map((field) => ({
          name: field.name,
          type: field.type,
        }));
        const mappingResult = await ApiService.mapFields(sessionId, databaseFields, pdfFormFields);
        if (!mappingResult?.success) {
          throw new Error(mappingResult?.error || 'Mapping generation failed');
        }

        const mappings = mappingResult.mappingResults?.mappings || [];
        const renameMap = new Map<string, string>();

        for (const mapping of mappings) {
          if (!mapping || !mapping.pdfField) continue;
          const currentName = mapping.originalPdfField || mapping.pdfField;
          const desiredName = mapping.pdfField;
          if (currentName && desiredName && currentName !== desiredName) {
            renameMap.set(currentName, desiredName);
          }
        }

        applyRenameMap(renameMap);
        debugLog('Applied AI mappings', { total: renameMap.size });
        return true;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'AI mapping failed.';
        setDbError(message);
        debugLog('AI mapping failed', message);
        return false;
      }
    },
    [applyRenameMap, ensureMappingSessionId, fields],
  );

  const handleConnectDb = useCallback(() => {
    setDbError(null);
    setShowConnectDb(true);
  }, []);

  const handleDisconnectDb = useCallback(async () => {
    if (!connId) return;
    setMappingInProgress(true);
    setDbError(null);
    try {
      await DB.disconnect(connId);
      setConnId(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to disconnect database.';
      setDbError(message);
    } finally {
      setMappingInProgress(false);
    }
  }, [connId]);

  const handleMapFromDb = useCallback(async () => {
    if (!connId) {
      setDbError('Connect a database before running AI mapping.');
      return;
    }
    setDbError(null);
    setMappingInProgress(true);
    setMapDbInProgress(true);
    try {
      const columns = await DB.fetchColumns(connId);
      const mapped = await applyAiMappings(columns);
      if (mapped) {
        window.alert('Field mapping is done.');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch database columns.';
      setDbError(message);
    } finally {
      setMapDbInProgress(false);
      setMappingInProgress(false);
    }
  }, [applyAiMappings, connId]);

  const handleOpenFieldMapper = useCallback(() => {
    if (!mappingSessionId) {
      setDbError('Upload a PDF before running AI mapping.');
      return;
    }
    setDbError(null);
    setShowFieldMapper(true);
  }, [mappingSessionId]);

  const handleCloseFieldMapper = useCallback(() => {
    setShowFieldMapper(false);
  }, []);

  const handleSelectField = useCallback((fieldId: string) => {
    setSelectedFieldId(fieldId);
  }, []);

  const handlePageJump = useCallback((page: number) => {
    setCurrentPage(page);
    setPendingPageJump(page);
  }, []);

  const handlePageScroll = useCallback((page: number) => {
    setCurrentPage(page);
  }, []);

  const handlePageJumpComplete = useCallback(() => {
    setPendingPageJump(null);
  }, []);

  const handleUpdateField = useCallback((fieldId: string, updates: Partial<PdfField>) => {
    setFields((prev) =>
      prev.map((field) => {
        if (field.id !== fieldId) return field;
        return {
          ...field,
          ...updates,
          rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
        };
      }),
    );
    debugLog('Updated field', fieldId, updates);
  }, []);

  const handleDeleteField = useCallback((fieldId: string) => {
    setFields((prev) => prev.filter((field) => field.id !== fieldId));
    setSelectedFieldId((prev) => (prev === fieldId ? null : prev));
    debugLog('Deleted field', fieldId);
  }, []);

  const handleCreateField = useCallback(
    (type: FieldType) => {
      const pageSize = pageSizes[currentPage];
      if (!pageSize) return;
      const nextField = createField(type, currentPage, pageSize, fields);
      setFields((prev) => [...prev, nextField]);
      setSelectedFieldId(nextField.id);
      debugLog('Created field', nextField);
    },
    [currentPage, fields, pageSizes],
  );

  const userEmail = useMemo(() => authUser?.email ?? undefined, [authUser]);
  const hasDocument = !!pdfDoc;
  const canSaveToProfile = Boolean(pdfDoc && authUser);
  const canDownload = Boolean(pdfDoc && authUser);
  const currentView = showHomepage
    ? 'homepage'
    : isProcessing
      ? 'processing'
    : hasDocument
      ? 'editor'
      : 'upload';

  if (!authReady) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">Loading workspace…</div>
      </div>
    );
  }

  if (showLogin) {
    return (
      <LoginPage
        onAuthenticated={() => setShowLogin(false)}
        onCancel={() => setShowLogin(false)}
      />
    );
  }

  if (currentView !== 'editor') {
    return (
      <div className="homepage-shell">
        <LegacyHeader
          currentView={currentView}
          onNavigateHome={handleNavigateHome}
          showBackButton={!showHomepage}
          userEmail={authUser?.email ?? null}
          onSignOut={authUser ? handleSignOut : undefined}
          onSignIn={!authUser ? () => setShowLogin(true) : undefined}
        />
        <main className="landing-main">
          {currentView === 'homepage' && (
            <Homepage onStartWorkflow={() => setShowHomepage(false)} />
          )}
          {currentView === 'upload' && (
            <div className="upload-layout">
              <div className="upload-primary-grid">
                <UploadComponent
                  variant="detect"
                  title="Upload PDF for Field Detection"
                  subtitle="Drag and drop your PDF file here, or"
                  onFileUpload={handleDetectUpload}
                  onValidationError={(message) => setLoadError(message)}
                />
                <UploadComponent
                  variant="fillable"
                  title="Upload Fillable PDF Template"
                  subtitle="Open your existing fillable PDF directly in the editor"
                  onFileUpload={handleFillableUpload}
                  onValidationError={(message) => setLoadError(message)}
                />
              </div>
              {authUser && (
                <section className="saved-forms-section" aria-label="Open saved form">
                  <h2 className="saved-forms-title">Open Saved Form:</h2>
                  <UploadComponent
                    variant="saved"
                    title=""
                    subtitle=""
                    savedForms={savedForms}
                    onSelectSavedForm={handleSelectSavedForm}
                    onDeleteSavedForm={handleDeleteSavedForm}
                    deletingFormId={deletingFormId}
                  />
                </section>
              )}
              {loadError && <div className="upload-error">{loadError}</div>}
            </div>
          )}
          {currentView === 'processing' && (
            <div className="processing-indicator">
              <div className="spinner"></div>
              <h3>Preparing your form…</h3>
              <p>Detecting fields and building the editor.</p>
            </div>
          )}
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <HeaderBar
        pageCount={pageCount}
        currentPage={currentPage}
        scale={scale}
        onScaleChange={setScale}
        onNavigateHome={handleNavigateHome}
        connId={connId}
        mappingInProgress={mappingInProgress}
        mapDbInProgress={mapDbInProgress}
        mappingError={dbError}
        onConnectDb={handleConnectDb}
        onDisconnectDb={handleDisconnectDb}
        onMapDb={handleMapFromDb}
        onOpenFieldMapper={handleOpenFieldMapper}
        onDownload={handleDownload}
        onSaveToProfile={handleSaveToProfile}
        downloadInProgress={downloadInProgress}
        saveInProgress={saveInProgress}
        canDownload={canDownload}
        canSave={canSaveToProfile}
        userEmail={userEmail}
        onSignIn={!authUser ? () => setShowLogin(true) : undefined}
        onSignOut={authUser ? handleSignOut : undefined}
      />
      <div className="app-shell">
        <FieldListPanel
          fields={fields}
          selectedFieldId={selectedFieldId}
          currentPage={currentPage}
          pageCount={pageCount}
          onSelectField={handleSelectField}
          onPageChange={handlePageJump}
        />
        <main className="workspace">
          {loadError ? (
            <div className="viewer viewer--empty">
              <div className="viewer__placeholder viewer__placeholder--error">
                <h2>Unable to load PDF</h2>
                <p>{loadError}</p>
              </div>
            </div>
          ) : (
            <PdfViewer
              pdfDoc={pdfDoc}
              pageNumber={currentPage}
              scale={scale}
              pageSizes={pageSizes}
              fields={fields}
              selectedFieldId={selectedFieldId}
              onSelectField={handleSelectField}
              onUpdateField={handleUpdateField}
              onPageChange={handlePageScroll}
              pendingPageJump={pendingPageJump}
              onPageJumpComplete={handlePageJumpComplete}
            />
          )}
        </main>
        <FieldInspectorPanel
          fields={fields}
          selectedFieldId={selectedFieldId}
          currentPage={currentPage}
          onUpdateField={handleUpdateField}
          onDeleteField={handleDeleteField}
          onCreateField={handleCreateField}
        />
      </div>
      {showConnectDb && (
        <ConnectDB
          open={showConnectDb}
          onClose={() => setShowConnectDb(false)}
          onConnected={({ connId: id }) => {
            setConnId(id);
          }}
        />
      )}
      {showFieldMapper && mappingSessionId && (
        <div className="mapper-modal" role="dialog" aria-modal="true">
          <div className="mapper-backdrop" onClick={handleCloseFieldMapper} />
          <div className="mapper-panel">
            <div className="mapper-header">
              <div>
                <h3>AI Field Mapper</h3>
                <p>Upload database field names and apply AI renames.</p>
              </div>
              <button type="button" className="mapper-close" onClick={handleCloseFieldMapper}>
                ×
              </button>
            </div>
            {dbError ? <div className="mapper-error">{dbError}</div> : null}
            <div className="mapper-body">
              <FieldMapper
                sessionId={mappingSessionId}
                pdfFormFields={fields.map((field) => ({ name: field.name, type: field.type }))}
                onFieldRenamed={handleManualRename}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
