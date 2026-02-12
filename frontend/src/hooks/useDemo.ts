import { useCallback, useEffect, useRef, useState } from 'react';
import type { DemoSearchPreset, PdfField } from '../types';
import type { HeaderRename } from '../utils/dataSource';
import { ensureUniqueFieldName } from '../utils/fields';
import { extractFieldsFromPdf, loadPdfFromFile } from '../utils/pdf';
import { parseCsv } from '../utils/csv';
import { debugLog } from '../utils/debug';
import { DEMO_ASSETS, DEMO_STEPS } from '../config/appConstants';

export interface UseDemoDeps {
  pdfDoc: any;
  sourceFileName: string | null;
  dataColumns: string[];
  resetFieldHistory: (fields?: PdfField[]) => void;
  setSelectedFieldId: (id: string | null) => void;
  setShowFields: (value: boolean) => void;
  setShowFieldNames: (value: boolean) => void;
  setShowFieldInfo: (value: boolean) => void;
  setHasRenamedFields: (value: boolean) => void;
  setHasMappedSchema: (value: boolean) => void;
  setShowSearchFill: (value: boolean) => void;
  setShowHomepage: (value: boolean) => void;
  setLoadError: (message: string | null) => void;
  clearWorkspace: () => void;
  handleFillableUpload: (file: File, options?: { isDemo?: boolean; skipExistingFields?: boolean }) => Promise<void>;
  applyParsedDataSource: (options: {
    kind: 'csv';
    label: string;
    columns: string[];
    rows: Array<Record<string, unknown>>;
    fileName: string;
    source: 'csv';
    skipPersist?: boolean;
  }) => Promise<void>;
  notifyHeaderRenames: (sourceLabel: string, fileName: string, headerRenames?: HeaderRename[]) => void;
}

export function useDemo(deps: UseDemoDeps) {
  const [demoActive, setDemoActive] = useState(false);
  const [demoStepIndex, setDemoStepIndex] = useState<number | null>(null);
  const [demoCompletionOpen, setDemoCompletionOpen] = useState(false);
  const [demoSearchPreset, setDemoSearchPreset] = useState<DemoSearchPreset | null>(null);
  const demoAssetCacheRef = useRef<Map<string, File>>(new Map());
  const demoPdfFieldCacheRef = useRef<Map<string, PdfField[]>>(new Map());
  const demoPdfFieldPromiseCacheRef = useRef<Map<string, Promise<PdfField[]>>>(new Map());
  const demoNameMapCacheRef = useRef<Map<string, Record<string, string>>>(new Map());
  const demoNameMapPromiseCacheRef = useRef<Map<string, Promise<Record<string, string>>>>(new Map());
  const demoStepTokenRef = useRef(0);
  const lastDemoStepRef = useRef<number | null>(null);

  useEffect(() => {
    if (!demoActive && !demoCompletionOpen) return;
    const prevBodyOverflow = document.body.style.overflow;
    const prevHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prevBodyOverflow;
      document.documentElement.style.overflow = prevHtmlOverflow;
    };
  }, [demoActive, demoCompletionOpen]);

  const loadDemoAsset = useCallback(
    async (filename: string, mimeType: string) => {
      const cached = demoAssetCacheRef.current.get(filename);
      if (cached) return cached;
      const baseUrl = import.meta.env.BASE_URL ?? '/';
      const response = await fetch(`${baseUrl}demo/${filename}`);
      if (!response.ok) throw new Error(`Failed to load demo asset: ${filename}`);
      const blob = await response.blob();
      const file = new File([blob], filename, { type: mimeType });
      demoAssetCacheRef.current.set(filename, file);
      return file;
    },
    [],
  );

  const loadDemoPdf = useCallback(
    async (filename: string, options: { skipExistingFields?: boolean } = {}) => {
      const file = await loadDemoAsset(filename, 'application/pdf');
      await deps.handleFillableUpload(file, { isDemo: true, skipExistingFields: options.skipExistingFields });
    },
    [deps.handleFillableUpload, loadDemoAsset],
  );

  const loadDemoPdfFields = useCallback(
    async (filename: string): Promise<PdfField[]> => {
      const cached = demoPdfFieldCacheRef.current.get(filename);
      if (cached) return cached;
      const pending = demoPdfFieldPromiseCacheRef.current.get(filename);
      if (pending) return pending;

      const loadDemoNameMap = async (nameMapFilename: string): Promise<Record<string, string>> => {
        const cachedMap = demoNameMapCacheRef.current.get(nameMapFilename);
        if (cachedMap) return cachedMap;
        const pendingMap = demoNameMapPromiseCacheRef.current.get(nameMapFilename);
        if (pendingMap) return pendingMap;
        const promiseMap = (async () => {
          const file = await loadDemoAsset(nameMapFilename, 'application/json');
          const text = await file.text();
          const parsed = JSON.parse(text) as unknown;
          if (!parsed || typeof parsed !== 'object') throw new Error(`Invalid demo name map: ${nameMapFilename}`);
          const candidate = (parsed as { map?: unknown }).map ?? parsed;
          if (!candidate || typeof candidate !== 'object') throw new Error(`Invalid demo name map payload: ${nameMapFilename}`);
          const output: Record<string, string> = {};
          for (const [key, value] of Object.entries(candidate as Record<string, unknown>)) {
            if (typeof value === 'string') output[key] = value;
          }
          if (!Object.keys(output).length) throw new Error(`Demo name map is empty: ${nameMapFilename}`);
          return output;
        })();
        demoNameMapPromiseCacheRef.current.set(nameMapFilename, promiseMap);
        try {
          const resolved = await promiseMap;
          demoNameMapCacheRef.current.set(nameMapFilename, resolved);
          return resolved;
        } finally {
          demoNameMapPromiseCacheRef.current.delete(nameMapFilename);
        }
      };

      const applyNameMap = (baseFields: PdfField[], nameMap: Record<string, string>): PdfField[] => {
        const seen = new Set<string>();
        return baseFields.map((field) => {
          const desiredName = nameMap[field.name] ?? field.name;
          const name = ensureUniqueFieldName(desiredName, seen);
          return { ...field, name };
        });
      };

      const promise = (async () => {
        const extractFromPdf = async (): Promise<PdfField[]> => {
          const file = await loadDemoAsset(filename, 'application/pdf');
          const doc = await loadPdfFromFile(file);
          try { return await extractFieldsFromPdf(doc); }
          finally { try { await doc.destroy(); } catch { /* best effort */ } }
        };

        if (filename === DEMO_ASSETS.openAiRenamePdf) {
          try {
            const [baseFields, nameMap] = await Promise.all([
              loadDemoPdfFields(DEMO_ASSETS.baseDetectionsPdf),
              loadDemoNameMap(DEMO_ASSETS.openAiRenameNameMap),
            ]);
            return applyNameMap(baseFields, nameMap);
          } catch (error) {
            debugLog('Failed to apply demo rename map; falling back to PDF extraction.', error);
            return await extractFromPdf();
          }
        }

        if (filename === DEMO_ASSETS.openAiRemapPdf) {
          try {
            const [baseFields, nameMap] = await Promise.all([
              loadDemoPdfFields(DEMO_ASSETS.baseDetectionsPdf),
              loadDemoNameMap(DEMO_ASSETS.openAiRemapNameMap),
            ]);
            return applyNameMap(baseFields, nameMap);
          } catch (error) {
            debugLog('Failed to apply demo remap map; falling back to PDF extraction.', error);
            return await extractFromPdf();
          }
        }

        return await extractFromPdf();
      })();

      demoPdfFieldPromiseCacheRef.current.set(filename, promise);
      try {
        const fields = await promise;
        demoPdfFieldCacheRef.current.set(filename, fields);
        return fields;
      } finally {
        demoPdfFieldPromiseCacheRef.current.delete(filename);
      }
    },
    [loadDemoAsset],
  );

  const ensureDemoBasePdf = useCallback(async () => {
    if (deps.pdfDoc && deps.sourceFileName === DEMO_ASSETS.rawPdf) return;
    await loadDemoPdf(DEMO_ASSETS.rawPdf, { skipExistingFields: true });
  }, [loadDemoPdf, deps.pdfDoc, deps.sourceFileName]);

  const applyDemoOverlayFromPdf = useCallback(
    async (filename: string, options: { guardToken?: number } = {}) => {
      const guardToken = options.guardToken;
      await ensureDemoBasePdf();
      if (guardToken !== undefined && demoStepTokenRef.current !== guardToken) return;
      const overlayFields = await loadDemoPdfFields(filename);
      if (guardToken !== undefined && demoStepTokenRef.current !== guardToken) return;
      deps.resetFieldHistory(overlayFields);
      deps.setSelectedFieldId(null);
      deps.setShowFields(true);
      deps.setShowFieldNames(true);
      deps.setShowFieldInfo(false);
    },
    [ensureDemoBasePdf, loadDemoPdfFields, deps],
  );

  const loadDemoCsv = useCallback(
    async (filename: string) => {
      const file = await loadDemoAsset(filename, 'text/csv');
      const text = await file.text();
      const parsed = parseCsv(text);
      if (!parsed.columns.length) throw new Error('Demo CSV file has no header row.');
      deps.notifyHeaderRenames('CSV', file.name, parsed.headerRenames);
      await deps.applyParsedDataSource({
        kind: 'csv', label: `CSV: ${file.name}`, columns: parsed.columns, rows: parsed.rows,
        fileName: file.name, source: 'csv', skipPersist: true,
      });
    },
    [deps, loadDemoAsset],
  );

  const startDemo = useCallback(() => {
    deps.clearWorkspace();
    deps.setLoadError(null);
    deps.setShowHomepage(false);
    setDemoActive(true);
    setDemoStepIndex(0);
    setDemoCompletionOpen(false);
    setDemoSearchPreset(null);
    void loadDemoPdfFields(DEMO_ASSETS.baseDetectionsPdf);
    void loadDemoPdfFields(DEMO_ASSETS.openAiRenamePdf);
    void loadDemoPdfFields(DEMO_ASSETS.openAiRemapPdf);
    lastDemoStepRef.current = null;
  }, [deps, loadDemoPdfFields]);

  const exitDemo = useCallback(() => {
    setDemoActive(false);
    setDemoStepIndex(null);
    deps.setShowSearchFill(false);
    setDemoCompletionOpen(false);
    setDemoSearchPreset(null);
  }, [deps]);

  const handleDemoNext = useCallback(() => {
    if (demoStepIndex === null) return;
    if (demoStepIndex >= DEMO_STEPS.length - 1) return;
    setDemoStepIndex((prev) => (prev === null ? prev : prev + 1));
  }, [demoStepIndex]);

  const handleDemoBack = useCallback(() => {
    setDemoStepIndex((prev) => (prev && prev > 0 ? prev - 1 : prev));
  }, []);

  const handleDemoCompletion = useCallback(() => {
    setDemoActive(false);
    setDemoStepIndex(null);
    setDemoCompletionOpen(true);
    setDemoSearchPreset(null);
    deps.setShowSearchFill(false);
  }, [deps]);

  const handleDemoReplay = useCallback(() => {
    setDemoCompletionOpen(false);
    void startDemo();
  }, [startDemo]);

  const handleDemoContinue = useCallback(() => {
    setDemoCompletionOpen(false);
  }, []);

  const handleDemoRename = useCallback(async () => {
    deps.setShowSearchFill(false);
    await applyDemoOverlayFromPdf(DEMO_ASSETS.openAiRenamePdf);
    deps.setHasRenamedFields(true);
    deps.setHasMappedSchema(false);
  }, [applyDemoOverlayFromPdf, deps]);

  const handleDemoMapSchema = useCallback(async () => {
    deps.setShowSearchFill(false);
    if (!deps.dataColumns.length) await loadDemoCsv(DEMO_ASSETS.csv);
    await applyDemoOverlayFromPdf(DEMO_ASSETS.openAiRemapPdf);
    deps.setHasRenamedFields(true);
    deps.setHasMappedSchema(true);
  }, [applyDemoOverlayFromPdf, deps, loadDemoCsv]);

  const handleDemoRenameAndMap = useCallback(async () => {
    deps.setShowSearchFill(false);
    if (!deps.dataColumns.length) await loadDemoCsv(DEMO_ASSETS.csv);
    await applyDemoOverlayFromPdf(DEMO_ASSETS.openAiRemapPdf);
    deps.setHasRenamedFields(true);
    deps.setHasMappedSchema(true);
  }, [applyDemoOverlayFromPdf, deps, loadDemoCsv]);

  // Demo step transition effect
  useEffect(() => {
    if (!demoActive || demoStepIndex === null) return;
    if (lastDemoStepRef.current === demoStepIndex) return;
    lastDemoStepRef.current = demoStepIndex;

    const stepId = DEMO_STEPS[demoStepIndex]?.id;
    if (!stepId) return;

    const token = demoStepTokenRef.current + 1;
    demoStepTokenRef.current = token;

    void (async () => {
      try {
        setDemoSearchPreset(null);
        deps.setShowSearchFill(false);
        if (stepId === 'raw-pdf') {
          await ensureDemoBasePdf();
          if (demoStepTokenRef.current !== token) return;
          deps.resetFieldHistory([]);
          deps.setSelectedFieldId(null);
          deps.setHasRenamedFields(false);
          deps.setHasMappedSchema(false);
          return;
        }
        if (stepId === 'commonforms') {
          await applyDemoOverlayFromPdf(DEMO_ASSETS.baseDetectionsPdf, { guardToken: token });
          if (demoStepTokenRef.current !== token) return;
          deps.setHasRenamedFields(false);
          deps.setHasMappedSchema(false);
          return;
        }
        if (stepId === 'rename') {
          await applyDemoOverlayFromPdf(DEMO_ASSETS.openAiRenamePdf, { guardToken: token });
          if (demoStepTokenRef.current !== token) return;
          deps.setHasRenamedFields(true);
          deps.setHasMappedSchema(false);
          return;
        }
        if (stepId === 'csv') {
          await loadDemoCsv(DEMO_ASSETS.csv);
          return;
        }
        if (stepId === 'remap') {
          if (!deps.dataColumns.length) {
            await loadDemoCsv(DEMO_ASSETS.csv);
            if (demoStepTokenRef.current !== token) return;
          }
          await applyDemoOverlayFromPdf(DEMO_ASSETS.openAiRemapPdf, { guardToken: token });
          if (demoStepTokenRef.current !== token) return;
          deps.setHasRenamedFields(true);
          deps.setHasMappedSchema(true);
          return;
        }
        if (stepId === 'search-fill') {
          if (!deps.dataColumns.length) {
            await loadDemoCsv(DEMO_ASSETS.csv);
            if (demoStepTokenRef.current !== token) return;
          }
          await applyDemoOverlayFromPdf(DEMO_ASSETS.openAiRemapPdf, { guardToken: token });
          if (demoStepTokenRef.current !== token) return;
          deps.setHasRenamedFields(true);
          deps.setHasMappedSchema(true);
          setDemoSearchPreset({
            query: 'Justin Thakral',
            searchKey: 'patient_name',
            searchMode: 'contains',
            autoRun: false,
            autoFillOnSearch: true,
            token: Date.now(),
          });
          deps.setShowSearchFill(true);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to load demo assets.';
        deps.setLoadError(message);
        exitDemo();
      }
    })();
  }, [
    applyDemoOverlayFromPdf,
    deps,
    demoActive,
    demoStepIndex,
    ensureDemoBasePdf,
    exitDemo,
    loadDemoCsv,
  ]);

  return {
    demoActive, setDemoActive,
    demoStepIndex, setDemoStepIndex,
    demoCompletionOpen, setDemoCompletionOpen,
    demoSearchPreset, setDemoSearchPreset,
    startDemo,
    exitDemo,
    handleDemoNext,
    handleDemoBack,
    handleDemoCompletion,
    handleDemoReplay,
    handleDemoContinue,
    handleDemoRename,
    handleDemoMapSchema,
    handleDemoRenameAndMap,
    loadDemoAsset,
    loadDemoPdf,
    loadDemoPdfFields,
    loadDemoCsv,
    applyDemoOverlayFromPdf,
    ensureDemoBasePdf,
  };
}
