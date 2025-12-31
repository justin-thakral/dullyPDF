import React, { useState, useRef } from 'react';
import { ApiService } from '../../api';
import { CONFIDENCE_THRESHOLDS, parseConfidence } from '../../utils/confidence';
import './FieldMapper.css';

const DEBUG_FIELD_MAPPER = false;
function debugLog(message: string, extra?: unknown) {
  if (!DEBUG_FIELD_MAPPER) return;
  console.log(`[field-mapper] ${message}`, extra ?? '');
}

function deriveMappingConfidence(originalName: string, nextName: string): number {
  const normalise = (value: string) =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  const left = normalise(originalName);
  const right = normalise(nextName);
  if (!left || !right) return 0.7;
  if (left === right) return 0.95;
  if (left.includes(right) || right.includes(left)) return 0.85;
  return 0.7;
}

interface FieldMapperProps {
  sessionId: string;
  pdfFormFields?: Array<{ name: string; type?: string; context?: string }>;
  onMappingsGenerated?: (mappings: any) => void;
  onFieldRenamed?: (oldName: string, newName: string, mappingConfidence?: number) => void;
}

interface MappingResult {
  databaseField: string;
  pdfField: string;
  originalPdfField?: string;
  confidence: number;
  reasoning: string;
  id: string;
  isManualOverride?: boolean;
}

interface UploadState {
  isUploading: boolean;
  filename: string | null;
  databaseFields: string[];
  error: string | null;
}

interface MappingState {
  isGenerating: boolean;
  mappings: MappingResult[];
  unmappedDatabase: string[];
  unmappedPdf: string[];
  overallConfidence: number;
  error: string | null;
}

const FieldMapper: React.FC<FieldMapperProps> = ({
  sessionId,
  pdfFormFields,
  onMappingsGenerated,
  onFieldRenamed,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [uploadState, setUploadState] = useState<UploadState>({
    isUploading: false,
    filename: null,
    databaseFields: [],
    error: null,
  });

  const [mappingState, setMappingState] = useState<MappingState>({
    isGenerating: false,
    mappings: [],
    unmappedDatabase: [],
    unmappedPdf: [],
    overallConfidence: 0,
    error: null,
  });

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.txt') && file.type !== 'text/plain') {
      setUploadState((prev) => ({
        ...prev,
        error: 'Please upload a .txt file containing database field names',
      }));
      return;
    }

    setUploadState((prev) => ({
      ...prev,
      isUploading: true,
      error: null,
    }));

    try {
      debugLog('Uploading database fields file', { name: file.name });
      const result = await ApiService.uploadDatabaseFields(file);

      setUploadState({
        isUploading: false,
        filename: result.filename,
        databaseFields: result.databaseFields,
        error: null,
      });

      debugLog('Database fields uploaded successfully', { totalFields: result.totalFields });
    } catch (error) {
      console.error('Database fields upload failed:', error);
      setUploadState((prev) => ({
        ...prev,
        isUploading: false,
        error: error instanceof Error ? error.message : 'Upload failed',
      }));
    }
  };

  const generateMappings = async () => {
    if (uploadState.databaseFields.length === 0) {
      setMappingState((prev) => ({
        ...prev,
        error: 'Please upload database fields first',
      }));
      return;
    }

    setMappingState((prev) => ({
      ...prev,
      isGenerating: true,
      error: null,
    }));

    try {
      debugLog('Generating AI field mappings...');
      const result = await ApiService.mapFields(sessionId, uploadState.databaseFields, pdfFormFields);

      if (result.success) {
        const mappingResults = result.mappingResults;
        setMappingState({
          isGenerating: false,
          mappings: mappingResults.mappings || [],
          unmappedDatabase: mappingResults.unmappedDatabaseFields || [],
          unmappedPdf: mappingResults.unmappedPdfFields || [],
          overallConfidence: mappingResults.confidence || 0,
          error: null,
        });

        onMappingsGenerated?.(mappingResults);
        debugLog('AI field mappings generated', { count: mappingResults.mappings?.length || 0 });
      } else {
        throw new Error(result.error || 'Mapping generation failed');
      }
    } catch (error) {
      console.error('Field mapping generation failed:', error);
      setMappingState((prev) => ({
        ...prev,
        isGenerating: false,
        error: error instanceof Error ? error.message : 'Mapping generation failed',
      }));
    }
  };

  const applyMapping = async (mapping: MappingResult) => {
    try {
      const currentName = mapping.originalPdfField || mapping.pdfField || '';
      const desiredName = mapping.pdfField || '';
      debugLog('Applying mapping', { currentName, desiredName, databaseField: mapping.databaseField });
      const mappingConfidence =
        parseConfidence(mapping.confidence) ?? deriveMappingConfidence(currentName, desiredName);
      onFieldRenamed?.(currentName, desiredName, mappingConfidence);

      setMappingState((prev) => ({
        ...prev,
        mappings: prev.mappings.map((m) =>
          m.id === mapping.id ? { ...m, isApplied: true } : m,
        ),
      }));

      debugLog('Field mapping applied successfully');
    } catch (error) {
      console.error('Failed to apply mapping:', error);
    }
  };

  const reset = () => {
    setUploadState({
      isUploading: false,
      filename: null,
      databaseFields: [],
      error: null,
    });
    setMappingState({
      isGenerating: false,
      mappings: [],
      unmappedDatabase: [],
      unmappedPdf: [],
      overallConfidence: 0,
      error: null,
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const getConfidenceColor = (confidence: number): string => {
    if (confidence >= CONFIDENCE_THRESHOLDS.high) return '#10b981';
    if (confidence >= CONFIDENCE_THRESHOLDS.low) return '#f59e0b';
    return '#ef4444';
  };

  return (
    <div className="field-mapper-container">
      <div className="field-mapper-header">
        <h3>Database Field Mapping</h3>
        <p>Upload database field names and let AI map them to PDF form fields</p>
      </div>

      <div className="upload-section">
        <div className="upload-area">
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,text/plain"
            onChange={handleFileUpload}
            className="file-input"
            id="fields-upload"
            disabled={uploadState.isUploading}
          />
          <label htmlFor="fields-upload" className="upload-label">
            <div className="upload-icon" aria-hidden="true">TXT</div>
            <div className="upload-text">
              {uploadState.isUploading ? (
                <span>Uploading...</span>
              ) : uploadState.filename ? (
                <span>Uploaded: {uploadState.filename}</span>
              ) : (
                <span>Choose database fields file (.txt)</span>
              )}
            </div>
          </label>
        </div>

        {uploadState.error && (
          <div className="error-message">
            {uploadState.error}
          </div>
        )}

        {uploadState.databaseFields.length > 0 && (
          <div className="upload-success">
            <div className="success-header">
              Loaded {uploadState.databaseFields.length} database fields
            </div>
            <div className="fields-preview">
              {uploadState.databaseFields.slice(0, 5).map((field, index) => (
                <span key={index} className="field-tag">{field}</span>
              ))}
              {uploadState.databaseFields.length > 5 && (
                <span className="field-tag-more">+{uploadState.databaseFields.length - 5} more</span>
              )}
            </div>
          </div>
        )}
      </div>

      {uploadState.databaseFields.length > 0 && (
        <div className="mapping-section">
          <button
            onClick={generateMappings}
            disabled={mappingState.isGenerating}
            className="generate-button"
          >
            {mappingState.isGenerating ? (
              <>
                <div className="spinner" />
                Generating AI Mappings...
              </>
            ) : (
              <>Generate AI Mappings</>
            )}
          </button>

          {mappingState.error && (
            <div className="error-message">
              {mappingState.error}
            </div>
          )}
        </div>
      )}

      {mappingState.mappings.length > 0 && (
        <div className="mappings-results">
          <div className="results-header">
            <h4>AI-Generated Field Mappings</h4>
            <div className="confidence-score">
              Overall Confidence:
              <span
                className="confidence-value"
                style={{ color: getConfidenceColor(mappingState.overallConfidence) }}
              >
                {Math.round(mappingState.overallConfidence * 100)}%
              </span>
            </div>
          </div>

          <div className="mappings-list">
            {mappingState.mappings.map((mapping) => (
              <div key={mapping.id} className="mapping-item">
                <div className="mapping-content">
                  <div className="mapping-arrow">
                    <div className="database-field">{mapping.databaseField}</div>
                    <div className="arrow">→</div>
                    <div className="pdf-field">{mapping.pdfField}</div>
                  </div>

                  <div className="mapping-details">
                    <div
                      className="confidence-badge"
                      style={{
                        backgroundColor: getConfidenceColor(mapping.confidence),
                        color: 'white',
                      }}
                    >
                      {Math.round(mapping.confidence * 100)}%
                    </div>
                    <div className="reasoning">{mapping.reasoning}</div>
                  </div>
                </div>

                <button
                  onClick={() => applyMapping(mapping)}
                  className={`apply-button ${(mapping as any).isApplied ? 'applied' : ''}`}
                  disabled={(mapping as any).isApplied}
                >
                  {(mapping as any).isApplied ? 'Applied' : 'Apply Mapping'}
                </button>
              </div>
            ))}
          </div>

          {(mappingState.unmappedDatabase.length > 0 || mappingState.unmappedPdf.length > 0) && (
            <div className="unmapped-section">
              <h5>Unmapped Fields</h5>

              {mappingState.unmappedDatabase.length > 0 && (
                <div className="unmapped-group">
                  <div className="unmapped-title">Database fields without matches:</div>
                  <div className="unmapped-list">
                    {mappingState.unmappedDatabase.map((field, index) => (
                      <span key={index} className="unmapped-field">{field}</span>
                    ))}
                  </div>
                </div>
              )}

              {mappingState.unmappedPdf.length > 0 && (
                <div className="unmapped-group">
                  <div className="unmapped-title">PDF fields without matches:</div>
                  <div className="unmapped-list">
                    {mappingState.unmappedPdf.map((field, index) => (
                      <span key={index} className="unmapped-field">{field}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="actions-section">
            <button onClick={reset} className="reset-button">
              Start Over
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default FieldMapper;
