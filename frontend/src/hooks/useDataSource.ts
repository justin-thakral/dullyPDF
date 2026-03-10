import { useCallback, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import type { User } from 'firebase/auth';
import type { BannerNotice, DataSourceKind, SchemaPayload } from '../types';
import type { HeaderRename } from '../utils/dataSource';
import { pickIdentifierKey } from '../utils/dataSource';
import { parseCsv } from '../utils/csv';
import { parseExcel } from '../utils/excel';
import { parseJsonDataSource } from '../utils/json';
import { inferSchemaFromRows, parseSchemaText } from '../utils/schema';
import { ALERT_MESSAGES, buildImportFileBeforeMapping } from '../utils/alertMessages';
import { ApiService } from '../services/api';

const MAX_SCHEMA_IMPORT_FILE_BYTES = 10 * 1024 * 1024;

export function validateSchemaImportFileSize(file: File): void {
  if (file.size <= MAX_SCHEMA_IMPORT_FILE_BYTES) return;
  throw new Error('Schema import files must be 10MB or smaller.');
}

export function useDataSource(deps: {
  verifiedUser: User | null;
  hasDocument: boolean;
  setBannerNotice: (notice: BannerNotice | null) => void;
  setMappingInProgress: (value: boolean) => void;
  setOpenAiError: (value: string | null) => void;
}) {
  const [dataSourceKind, setDataSourceKind] = useState<DataSourceKind>('none');
  const [dataSourceLabel, setDataSourceLabel] = useState<string | null>(null);
  const [schemaId, setSchemaId] = useState<string | null>(null);
  const [pendingSchemaPayload, setPendingSchemaPayload] = useState<SchemaPayload | null>(null);
  const [schemaUploadInProgress, setSchemaUploadInProgress] = useState(false);
  const [dataColumns, setDataColumns] = useState<string[]>([]);
  const [dataRows, setDataRows] = useState<Array<Record<string, unknown>>>([]);
  const [identifierKey, setIdentifierKey] = useState<string | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const excelInputRef = useRef<HTMLInputElement>(null);
  const jsonInputRef = useRef<HTMLInputElement>(null);
  const txtInputRef = useRef<HTMLInputElement>(null);
  const schemaPersistPromiseRef = useRef<Promise<string | null> | null>(null);
  const schemaPersistFingerprintRef = useRef<string | null>(null);

  const handleChooseDataSource = useCallback(
    (kind: Exclude<DataSourceKind, 'none'>) => {
      setSchemaError(null);
      if (kind === 'csv') { csvInputRef.current?.click(); return; }
      if (kind === 'excel') { excelInputRef.current?.click(); return; }
      if (kind === 'json') { jsonInputRef.current?.click(); return; }
      if (kind === 'txt') { txtInputRef.current?.click(); }
    },
    [],
  );

  const handleClearDataSource = useCallback(() => {
    setSchemaError(null);
    setSchemaId(null);
    setPendingSchemaPayload(null);
    setDataSourceKind('none');
    setDataSourceLabel(null);
    setSchemaUploadInProgress(false);
    setDataColumns([]);
    setDataRows([]);
    setIdentifierKey(null);
  }, []);

  const persistSchemaPayload = useCallback(
    async (payload: SchemaPayload): Promise<string | null> => {
      if (!deps.verifiedUser) return null;
      if (schemaId) return schemaId;
      const fingerprint = JSON.stringify({
        name: payload.name,
        source: payload.source,
        sampleCount: payload.sampleCount,
        fields: payload.fields.map((field) => ({ name: field.name, type: field.type })),
      });
      if (
        schemaPersistPromiseRef.current &&
        schemaPersistFingerprintRef.current === fingerprint
      ) {
        return schemaPersistPromiseRef.current;
      }
      const persistPromise = (async () => {
        try {
          const created = await ApiService.createSchema(payload);
          const nextSchemaId = created.schemaId || null;
          setSchemaId(nextSchemaId);
          if (nextSchemaId) {
            setPendingSchemaPayload(null);
          }
          return nextSchemaId;
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Failed to store schema metadata.';
          setSchemaError(message);
          setSchemaId(null);
          return null;
        }
      })();
      schemaPersistPromiseRef.current = persistPromise;
      schemaPersistFingerprintRef.current = fingerprint;
      try {
        return await persistPromise;
      } finally {
        if (schemaPersistPromiseRef.current === persistPromise) {
          schemaPersistPromiseRef.current = null;
          schemaPersistFingerprintRef.current = null;
        }
      }
    },
    [schemaId, deps.verifiedUser],
  );

  const resolveSchemaForMapping = useCallback(
    async (mode: 'map' | 'renameAndMap'): Promise<string | null> => {
      if (!deps.verifiedUser) {
        if (mode === 'renameAndMap') {
          deps.setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRenameAndMap);
        } else {
          setSchemaError(ALERT_MESSAGES.signInToRunSchemaMapping);
        }
        return null;
      }
      if (dataSourceKind === 'none') {
        const message =
          mode === 'renameAndMap'
            ? ALERT_MESSAGES.chooseSchemaFileForRenameAndMap
            : ALERT_MESSAGES.chooseSchemaFileForMapping;
        setSchemaError(message);
        return null;
      }
      if (
        (dataSourceKind === 'csv' ||
          dataSourceKind === 'excel' ||
          dataSourceKind === 'json' ||
          dataSourceKind === 'txt') &&
        dataColumns.length === 0
      ) {
        setSchemaError(buildImportFileBeforeMapping(dataSourceKind));
        return null;
      }
      if (schemaId) {
        return schemaId;
      }
      if (!pendingSchemaPayload) {
        const message =
          mode === 'renameAndMap'
            ? ALERT_MESSAGES.chooseSchemaFileForRenameAndMap
            : ALERT_MESSAGES.chooseSchemaFileForMapping;
        setSchemaError(message);
        return null;
      }
      setSchemaUploadInProgress(true);
      try {
        return await persistSchemaPayload(pendingSchemaPayload);
      } finally {
        setSchemaUploadInProgress(false);
      }
    },
    [dataColumns.length, dataSourceKind, pendingSchemaPayload, persistSchemaPayload, schemaId, deps],
  );

  const applySchemaMetadata = useCallback(
    async ({
      kind,
      label,
      schema,
      rows = [],
      fileName,
      source,
      skipPersist = false,
    }: {
      kind: Exclude<DataSourceKind, 'none'>;
      label: string;
      schema: { fields: Array<{ name: string; type?: string }>; sampleCount: number };
      rows?: Array<Record<string, unknown>>;
      fileName: string;
      source: 'csv' | 'excel' | 'json' | 'txt';
      skipPersist?: boolean;
    }) => {
      const columns = schema.fields.map((field) => field.name);
      setDataSourceKind(kind);
      setDataSourceLabel(label);
      setDataColumns(columns);
      setDataRows(rows);
      setIdentifierKey(pickIdentifierKey(columns));
      setSchemaId(null);
      const payload: SchemaPayload = {
        name: fileName,
        fields: schema.fields,
        source,
        sampleCount: schema.sampleCount,
      };
      setPendingSchemaPayload(payload);
      if (skipPersist || !deps.verifiedUser) {
        return;
      }
      await persistSchemaPayload(payload);
    },
    [persistSchemaPayload, deps.verifiedUser],
  );

  const applyParsedDataSource = useCallback(
    async ({
      kind,
      label,
      columns,
      rows,
      fileName,
      source,
      skipPersist = false,
    }: {
      kind: Exclude<DataSourceKind, 'none'>;
      label: string;
      columns: string[];
      rows: Array<Record<string, unknown>>;
      fileName: string;
      source: 'csv' | 'excel';
      skipPersist?: boolean;
    }) => {
      const schema = inferSchemaFromRows(columns, rows);
      await applySchemaMetadata({
        kind,
        label,
        schema,
        rows,
        fileName,
        source,
        skipPersist,
      });
    },
    [applySchemaMetadata],
  );

  const applyStructuredDataSource = useCallback(
    ({
      kind,
      label,
      rows,
      columns,
      identifierKey: identifierOverride,
    }: {
      kind: Extract<DataSourceKind, 'csv' | 'excel' | 'json' | 'respondent'>;
      label: string;
      rows: Array<Record<string, unknown>>;
      columns?: string[];
      identifierKey?: string | null;
    }) => {
      const nextColumns = columns && columns.length > 0
        ? columns
        : Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
      setSchemaError(null);
      setSchemaId(null);
      setPendingSchemaPayload(null);
      setDataSourceKind(kind);
      setDataSourceLabel(label);
      setSchemaUploadInProgress(false);
      setDataColumns(nextColumns);
      setDataRows(rows);
      setIdentifierKey(identifierOverride ?? pickIdentifierKey(nextColumns));
    },
    [],
  );

  const notifyHeaderRenames = useCallback(
    (sourceLabel: string, fileName: string, headerRenames?: HeaderRename[]) => {
      if (!headerRenames?.length) return;
      const sample = headerRenames.slice(0, 3).map((entry) => `${entry.original} -> ${entry.renamed}`);
      const extra = headerRenames.length - sample.length;
      const suffix = extra > 0 ? ` (+${extra} more)` : '';
      deps.setBannerNotice({
        tone: 'warning',
        message: `Duplicate ${sourceLabel} headers (after normalization) were renamed for ${fileName}: ${sample.join(', ')}${suffix}.`,
        autoDismissMs: 10000,
      });
    },
    [deps],
  );

  const runSchemaUpload = useCallback(
    async (work: () => Promise<void>, fallbackMessage: string) => {
      setSchemaError(null);
      deps.setMappingInProgress(true);
      setSchemaUploadInProgress(true);
      try {
        await work();
      } catch (error) {
        const message = error instanceof Error ? error.message : fallbackMessage;
        setSchemaError(message);
      } finally {
        setSchemaUploadInProgress(false);
        deps.setMappingInProgress(false);
      }
    },
    [deps],
  );

  const handleCsvFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    validateSchemaImportFileSize(file);
    await runSchemaUpload(
      async () => {
        const text = await file.text();
        const parsed = parseCsv(text);
        if (!parsed.columns.length) throw new Error('CSV file has no header row.');
        notifyHeaderRenames('CSV', file.name, parsed.headerRenames);
        await applyParsedDataSource({
          kind: 'csv', label: `CSV: ${file.name}`, columns: parsed.columns, rows: parsed.rows,
          fileName: file.name, source: 'csv',
        });
      },
      'Failed to import CSV file.',
    );
  }, [applyParsedDataSource, notifyHeaderRenames, runSchemaUpload]);

  const handleExcelFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    validateSchemaImportFileSize(file);
    await runSchemaUpload(
      async () => {
        const buffer = await file.arrayBuffer();
        const parsed = await parseExcel(buffer);
        if (!parsed.columns.length) throw new Error('Excel sheet has no header row.');
        notifyHeaderRenames('Excel', file.name, parsed.headerRenames);
        await applyParsedDataSource({
          kind: 'excel',
          label: `Excel: ${file.name}${parsed.sheetName ? ` (${parsed.sheetName})` : ''}`,
          columns: parsed.columns, rows: parsed.rows, fileName: file.name, source: 'excel',
        });
      },
      'Failed to import Excel file.',
    );
  }, [applyParsedDataSource, notifyHeaderRenames, runSchemaUpload]);

  const handleJsonFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    validateSchemaImportFileSize(file);
    await runSchemaUpload(
      async () => {
        const text = await file.text();
        const parsed = parseJsonDataSource(text);
        if (!parsed.schema.fields.length) throw new Error('JSON schema has no field names.');
        notifyHeaderRenames('JSON', file.name, parsed.headerRenames);
        await applySchemaMetadata({
          kind: 'json', label: `JSON: ${file.name}`, schema: parsed.schema, rows: parsed.rows,
          fileName: file.name, source: 'json',
        });
      },
      'Failed to import JSON file.',
    );
  }, [applySchemaMetadata, notifyHeaderRenames, runSchemaUpload]);

  const handleTxtFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    validateSchemaImportFileSize(file);
    await runSchemaUpload(
      async () => {
        const text = await file.text();
        const schema = parseSchemaText(text);
        if (!schema.fields.length) throw new Error('TXT schema file has no field names.');
        await applySchemaMetadata({
          kind: 'txt', label: `TXT: ${file.name}`, schema, rows: [],
          fileName: file.name, source: 'txt',
        });
      },
      'Failed to import TXT schema file.',
    );
  }, [applySchemaMetadata, runSchemaUpload]);

  const canSearchFill = useMemo(() => {
    if (!deps.hasDocument || dataSourceKind === 'none') return false;
    if (!['csv', 'excel', 'json', 'respondent'].includes(dataSourceKind)) return false;
    return dataRows.length > 0;
  }, [dataRows.length, dataSourceKind, deps.hasDocument]);

  const reset = useCallback(() => {
    setSchemaError(null);
    setSchemaId(null);
    setPendingSchemaPayload(null);
    setDataSourceKind('none');
    setDataSourceLabel(null);
    setSchemaUploadInProgress(false);
    setDataColumns([]);
    setDataRows([]);
    setIdentifierKey(null);
  }, []);

  return {
    dataSourceKind, setDataSourceKind,
    dataSourceLabel, setDataSourceLabel,
    schemaId, setSchemaId,
    pendingSchemaPayload, setPendingSchemaPayload,
    schemaUploadInProgress, setSchemaUploadInProgress,
    dataColumns, setDataColumns,
    dataRows, setDataRows,
    identifierKey, setIdentifierKey,
    schemaError, setSchemaError,
    csvInputRef, excelInputRef, jsonInputRef, txtInputRef,
    handleChooseDataSource,
    handleClearDataSource,
    persistSchemaPayload,
    resolveSchemaForMapping,
    applySchemaMetadata,
    applyParsedDataSource,
    applyStructuredDataSource,
    notifyHeaderRenames,
    handleCsvFileSelected,
    handleExcelFileSelected,
    handleJsonFileSelected,
    handleTxtFileSelected,
    canSearchFill,
    reset,
  };
}
