import { describe, expect, it } from 'vitest';

import { ALERT_MESSAGES, buildImportFileBeforeMapping } from '../../../src/utils/alertMessages';

describe('alertMessages', () => {
  it('keeps shared alert constants stable for auth and mapping flows', () => {
    expect(ALERT_MESSAGES).toEqual({
      signInToRunSchemaMapping: 'Sign in to run schema mapping.',
      signInToRunOpenAiRename: 'Sign in to run OpenAI rename.',
      signInToRunOpenAiRenameAndMap: 'Sign in to run OpenAI rename and mapping.',
      uploadPdfForRename: 'Upload a PDF to create a session before renaming.',
      noPdfFieldsToRename: 'No PDF fields available to rename.',
      noPdfFieldsToMap: 'No PDF fields available to map.',
      schemaRequiredForMapping: 'Import a CSV, Excel, JSON, or TXT file to create a schema first.',
      chooseSchemaFileForMapping: 'Connect a CSV, Excel, JSON, or TXT file before running AI mapping.',
      chooseSchemaFileForRenameAndMap:
        'Connect a CSV, Excel, JSON, or TXT schema file before running mapping.',
      mappingDone: 'Field mapping is done.',
    });
  });

  it('formats import-before-mapping messages for each supported source kind', () => {
    expect(buildImportFileBeforeMapping('csv')).toBe('Import a CSV file before running AI mapping.');
    expect(buildImportFileBeforeMapping('excel')).toBe(
      'Import a EXCEL file before running AI mapping.',
    );
    expect(buildImportFileBeforeMapping('json')).toBe('Import a JSON file before running AI mapping.');
    expect(buildImportFileBeforeMapping('txt')).toBe('Import a TXT file before running AI mapping.');
  });

  it('uppercases dynamic kinds without altering the surrounding sentence shape', () => {
    expect(buildImportFileBeforeMapping('Xml File')).toBe(
      'Import a XML FILE file before running AI mapping.',
    );
  });
});
