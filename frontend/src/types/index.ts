/** Shared type definitions for the frontend. */
import type { ReactNode } from 'react';
import type { AlertTone } from '../components/ui/Alert';
import type { DialogTone } from '../components/ui/Dialog';

// Re-export component types so consumers can import from one place.
export type { AlertTone } from '../components/ui/Alert';
export type { DialogTone } from '../components/ui/Dialog';

// Supported field categories used by the editor and overlay styling.
export type FieldType = 'text' | 'checkbox' | 'signature' | 'date';

export type ConfidenceTier = 'high' | 'medium' | 'low';

export type ConfidenceFilter = Record<ConfidenceTier, boolean>;

// Geometry is expressed in PDF points with a top-left origin.
export type FieldRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

// Client-side representation of a form field, kept in memory until export is implemented.
export type PdfField = {
  id: string;
  name: string;
  type: FieldType;
  page: number;
  rect: FieldRect;
  /**
   * Confidence that this is a real field (0..1). Populated by detection.
   * When OpenAI rename runs, this should represent "isItAfieldConfidence" if present.
   */
  fieldConfidence?: number;
  /**
   * Confidence of the schema mapping/rename suggestion (0..1).
   */
  mappingConfidence?: number;
  /**
   * Confidence of the OpenAI rename suggestion (0..1).
   */
  renameConfidence?: number;
  /**
   * Optional field value to inject when generating a filled PDF.
   */
  value?: string | number | boolean | null;
  /**
   * Checkbox grouping metadata used for schema mapping and search/fill rules.
   */
  groupKey?: string;
  optionKey?: string;
  optionLabel?: string;
  groupLabel?: string;
};

export type CheckboxRule = {
  databaseField: string;
  groupKey: string;
  operation: 'yes_no' | 'enum' | 'list' | 'presence';
  trueOption?: string;
  falseOption?: string;
  valueMap?: Record<string, string>;
  confidence?: number;
  reasoning?: string;
};

export type CheckboxHint = {
  databaseField: string;
  groupKey: string;
  operation?: 'yes_no' | 'enum' | 'list' | 'presence';
  directBooleanPossible?: boolean;
};

export type TextTransformRuleOperation =
  | 'copy'
  | 'concat'
  | 'split_name_first_rest'
  | 'split_delimiter';

export type TextTransformRule = {
  targetField: string;
  operation: TextTransformRuleOperation;
  sources: string[];
  separator?: string;
  delimiter?: string;
  part?: 'first' | 'rest' | 'last';
  index?: number;
  confidence?: number;
  requiresReview?: boolean;
  reasoning?: string;
};

export type FillRules = {
  version?: number;
  checkboxRules?: CheckboxRule[];
  checkboxHints?: CheckboxHint[];
  textTransformRules?: TextTransformRule[];
};

// Cached page dimensions for rendering and clamping.
export type PageSize = {
  width: number;
  height: number;
};

export type SavedFormEditorSnapshot = {
  version: number;
  pageCount: number;
  pageSizes: Record<number, PageSize>;
  fields: PdfField[];
  hasRenamedFields: boolean;
  hasMappedSchema: boolean;
};

// Data source selector options.
export type DataSourceKind = 'csv' | 'excel' | 'json' | 'txt' | 'respondent' | 'none';

// Processing pipeline mode.
export type ProcessingMode = 'detect' | 'fillable' | 'saved' | null;

// Payload sent to the backend when persisting a schema.
export type SchemaPayload = {
  name?: string;
  fields: Array<{ name: string; type?: string }>;
  source?: string;
  sampleCount?: number;
};

// Queued auto-actions that run after background detection completes.
export type PendingAutoActions = {
  loadToken: number;
  sessionId: string;
  schemaId: string | null;
  autoRename: boolean;
  autoMap: boolean;
};

// Search preset passed to SearchFillModal for demos and respondent jumps.
export type SearchFillPreset = {
  query: string;
  searchKey?: string;
  searchMode?: 'contains' | 'equals';
  autoRun?: boolean;
  autoFillOnSearch?: boolean;
  highlightResult?: boolean;
  token: number;
};

export type DemoSearchPreset = SearchFillPreset;

// Banner notification displayed at the top of the app.
export type BannerNotice = {
  tone: AlertTone;
  message: string;
  autoDismissMs?: number;
};

// Options for the confirm dialog.
export type ConfirmDialogOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
};

// Options for the prompt dialog.
export type PromptDialogOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
  defaultValue?: string;
  placeholder?: string;
  requireValue?: boolean;
};

// Discriminated union for dialog requests.
export type DialogRequest =
  | ({ kind: 'confirm' } & ConfirmDialogOptions)
  | ({ kind: 'prompt' } & PromptDialogOptions);

// A single field name update from rename or mapping.
export type FieldNameUpdate = {
  newName?: string;
  mappingConfidence?: unknown;
};

// Queue bucket for batching updates by name.
export type NameQueue<T> = {
  entries: T[];
  index: number;
};
