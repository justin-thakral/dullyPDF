/**
 * Homepage Component for PDF Form Generator
 *
 * Displays the main landing page with project description and call-to-action.
 * Features a left panel with enhanced project description and a right panel
 * with a prominent "Try Now" button that navigates to the upload workflow.
 *
 * Layout Design:
 * - Split screen layout with description on left, action on right
 * - Black, white, and blue color scheme consistent with detected field colors
 * - Responsive design that stacks on mobile devices
 * - Professional presentation suitable for a technical PDF processing tool
 */

import React from 'react';
import './Homepage.css';

interface HomepageProps {
  onStartWorkflow: () => void;
}

/**
 * Landing page describing the end-to-end workflow.
 */
const Homepage: React.FC<HomepageProps> = ({ onStartWorkflow }) => {
  return (
    <div className="homepage-container">
      <div className="homepage-content">
        {/* Left Panel - Project Description */}
        <div className="description-panel">
          <div className="description-content">
            <h2>AI-Powered PDF Form Generator</h2>

            <div className="description-text">
              <p className="lead-description">
                This software converts raw PDFs into fillable forms with writable areas at all input fields.
                Once you have your fillable form, you can upload a CSV, Excel, or TXT schema file locally and map
                field names to the PDF. CSV/Excel rows stay in the browser for Search &amp; Fill.
              </p>

              <div className="features-section">
                <h3>Complete Workflow Process</h3>
                <div className="feature-list">
                  <div className="feature-item">
                    <span className="feature-number">1</span>
                    <div className="feature-content">
                      <h4>Upload PDF Document</h4>
                      <p>
                        Upload any PDF document containing text fields, checkboxes, signature areas,
                        or any regions where users should input information. Supports files up to 50MB.
                      </p>
                    </div>
                  </div>

                  <div className="feature-item">
                    <span className="feature-number">2</span>
                    <div className="feature-content">
                      <h4>AI-Powered Field Detection</h4>
                      <p>
                        The detection pipeline analyzes your document and automatically identifies
                        potential form fields with confidence scoring and context hints pulled from nearby labels.
                      </p>
                    </div>
                  </div>

                  <div className="feature-item">
                    <span className="feature-number">3</span>
                    <div className="feature-content">
                      <h4>Interactive Visual Editing</h4>
                      <p>
                        Review and refine detected fields using the Form Field Editor.
                        Resize, rename, reposition, and adjust field properties with precision tools for
                        accurate, production-ready templates.
                      </p>
                    </div>
                  </div>

                  <div className="feature-item">
                    <span className="feature-number">4</span>
                    <div className="feature-content">
                      <h4>Schema Mapping & Auto-Fill</h4>
                      <p>
                        Upload a CSV/Excel/TXT schema file locally, map PDF field names to your schema, and
                        choose a local record to populate the form for streamlined data entry.
                      </p>
                    </div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>

        {/* Right Panel - Call to Action */}
        <div className="action-panel">
          <div className="action-content">
            <div className="cta-section">
              <h3>Ready to Get Started?</h3>
              <p className="cta-description">
                Upload your PDF document and experience the power of AI-driven
                form field detection and generation.
              </p>

              <button
                onClick={onStartWorkflow}
                className="try-now-button"
              >
                Try Now
              </button>

              <div className="quick-info">
                <div className="info-item">
                  <span className="info-label">Supported:</span>
                  <span className="info-value">PDF files up to 50MB</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Processing:</span>
                  <span className="info-value">Typically under 30 seconds</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Output:</span>
                  <span className="info-value">Editable field template</span>
                </div>
              </div>
            </div>

            <div className="tech-note">
              <h4>Powered by Advanced Technology</h4>
              <p>
                Built using PDF.js rendering for precision geometry,
                React for responsive interfaces, and AI workflows
                for intelligent field detection and naming.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Homepage;
