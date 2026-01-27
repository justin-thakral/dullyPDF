export const ALERT_MESSAGES = {
  signInToRunSchemaMapping: 'Sign in to run schema mapping.',
  signInToRunOpenAiRename: 'Sign in to run OpenAI rename.',
  signInToRunOpenAiRenameAndMap: 'Sign in to run OpenAI rename and mapping.',
  uploadPdfForRename: 'Upload a PDF to create a session before renaming.',
  noPdfFieldsToRename: 'No PDF fields available to rename.',
  noPdfFieldsToMap: 'No PDF fields available to map.',
  schemaRequiredForMapping: 'Import a CSV, Excel, JSON, or TXT file to create a schema first.',
  chooseSchemaFileForMapping: 'Connect a CSV, Excel, JSON, or TXT file before running AI mapping.',
  chooseSchemaFileForRenameAndMap: 'Connect a CSV, Excel, JSON, or TXT schema file before running mapping.',
  mappingDone: 'Field mapping is done.',
} as const;

export const buildImportFileBeforeMapping = (dataSourceKind: string) =>
  `Import a ${dataSourceKind.toUpperCase()} file before running AI mapping.`;
