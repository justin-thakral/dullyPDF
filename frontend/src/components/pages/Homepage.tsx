/**
 * Homepage Component for DullyPDF
 *
 * Desktop keeps the original two-panel layout.
 * Mobile shows a dedicated walkthrough-only experience.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import './Homepage.css';

interface HomepageProps {
  onStartWorkflow: () => void;
  onStartDemo?: () => void;
  userEmail?: string | null;
  onSignIn?: () => void;
  onOpenProfile?: () => void;
}

const DEMO_WALKTHROUGH = [
  {
    id: 'raw-pdf',
    title: 'Start with the raw intake PDF',
    description:
      'Begin with the source form exactly as the clinic provides it. DullyPDF reads the layout before any edits.',
    image: '/demo/mobile-raw-pdf.png',
    alt: 'Raw PDF intake form with blank fields and section headers.',
  },
  {
    id: 'commonforms',
    title: 'CommonForms highlights candidate fields',
    description:
      'The ML detector finds input regions and labels them with confidence-scored field tags for review.',
    image: '/demo/mobile-commonforms.png',
    alt: 'Detected fields overlayed on the PDF with CommonForms tag labels.',
  },
  {
    id: 'inspector',
    title: 'Inspector for precise edits',
    description:
      'Use the inspector to add, rename, and adjust field types without touching the PDF source.',
    image: '/demo/mobile-inspector.png',
    alt: 'Field inspector panel showing add field actions and edit controls.',
  },
  {
    id: 'field-list',
    title: 'Field list to filter and audit',
    description:
      'Review every detected field, filter by confidence, and verify sizes or pages with quick scanning.',
    image: '/demo/mobile-field-list.png',
    alt: 'Field list panel with confidence filters and detected field entries.',
  },
  {
    id: 'rename-remap',
    title: 'OpenAI rename + OpenAI remap',
    description:
      'OpenAI rename standardizes field names, and OpenAI remap aligns them to database columns so the template is ready for database plug-ins.',
    image: '/demo/mobile-rename-remap.png',
    alt: 'PDF overlay showing standardized field names after rename and remap.',
  },
  {
    id: 'filled',
    title: 'Search & Fill completes the form',
    description:
      'Pull a record from your data source and populate every mapped field in seconds.',
    image: '/demo/mobile-filled.png',
    alt: 'Completed PDF form with patient data filled into the detected fields.',
  },
];

/**
 * Landing page describing the end-to-end workflow.
 */
const Homepage: React.FC<HomepageProps> = ({
  onStartWorkflow,
  onStartDemo,
  userEmail,
  onSignIn,
  onOpenProfile,
}) => {
  const demoRef = useRef<HTMLDivElement | null>(null);
  const demoNavRef = useRef<HTMLDivElement | null>(null);
  const [activeDemoIndex, setActiveDemoIndex] = useState(0);
  const [demoFocusActive, setDemoFocusActive] = useState(false);
  const userInitial = useMemo(() => (userEmail ? userEmail.charAt(0).toUpperCase() : null), [userEmail]);

  const activeStep = DEMO_WALKTHROUGH[activeDemoIndex];
  const hasPrev = activeDemoIndex > 0;
  const hasNext = activeDemoIndex < DEMO_WALKTHROUGH.length - 1;

  const scrollToDemoNav = (behavior: ScrollBehavior) => {
    const target = demoNavRef.current ?? demoRef.current;
    target?.scrollIntoView({ behavior, block: 'end' });
  };

  const handleScrollToDemo = () => {
    setDemoFocusActive(true);
    scrollToDemoNav('smooth');
  };

  const handlePrevStep = () => {
    setDemoFocusActive(true);
    setActiveDemoIndex((prev) => Math.max(0, prev - 1));
  };

  const handleNextStep = () => {
    setDemoFocusActive(true);
    setActiveDemoIndex((prev) => Math.min(DEMO_WALKTHROUGH.length - 1, prev + 1));
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!window.matchMedia('(max-width: 900px)').matches) return;
    if (!demoFocusActive) return;
    if (!demoNavRef.current) return;
    requestAnimationFrame(() => {
      scrollToDemoNav('auto');
    });
  }, [activeDemoIndex, demoFocusActive]);

  const authAction = userEmail ? (
    <button
      type="button"
      className="homepage-auth-button homepage-auth-button--active"
      onClick={onOpenProfile}
      title={userEmail}
    >
      {userInitial ? <span className="homepage-auth-avatar">{userInitial}</span> : null}
      <span className="homepage-auth-label">Profile</span>
    </button>
  ) : onSignIn ? (
    <button type="button" className="homepage-auth-button" onClick={onSignIn}>
      Sign in
    </button>
  ) : null;

  return (
    <div className="homepage-container">
      <header className="homepage-mobile-header">
        <div className="homepage-mobile-header__row">
          <span className="homepage-mobile-tagline">Automatic PDF-&gt;Template</span>
          <div className="homepage-mobile-actions">
            {authAction}
            <div className="homepage-mobile-logo">
              <img className="homepage-logo-image" src="/DullyPDFLogoImproved.png" alt="DullyPDF" />
              <span className="homepage-logo-text">DullyPDF</span>
            </div>
          </div>
        </div>
      </header>

      <section className="homepage-mobile-layout">
        <div className="mobile-cta">
          <p className="mobile-warning">
            mobile device detected, please open on computer for full functionality. Mobile site is for explanation and
            demo only
          </p>
          <button type="button" className="mobile-demo-button" onClick={handleScrollToDemo}>
            Demo
          </button>
        </div>

        <div className="mobile-copy">
          <p className="mobile-description">
            DullyPDF converts raw PDFs into editable templates with precise form fields. Upload a CSV, Excel, JSON, or
            TXT schema locally, standardize field names with OpenAI, and map them to your database columns for Search
            &amp; Fill.
          </p>
        </div>

        <div className="mobile-steps">
          <h3>Workflow overview</h3>
          <div className="feature-list">
            <div className="feature-item">
              <span className="feature-number">1</span>
              <div className="feature-content">
                <h4>Upload the PDF</h4>
                <p>Bring in any intake form, contract, or template PDF with blank fields.</p>
              </div>
            </div>
            <div className="feature-item">
              <span className="feature-number">2</span>
              <div className="feature-content">
                <h4>Detect fields with CommonForms</h4>
                <p>The detector finds input regions and matches them to nearby labels.</p>
              </div>
            </div>
            <div className="feature-item">
              <span className="feature-number">3</span>
              <div className="feature-content">
                <h4>Refine in the editor</h4>
                <p>Resize, rename, and retype fields before finalizing the template.</p>
              </div>
            </div>
            <div className="feature-item">
              <span className="feature-number">4</span>
              <div className="feature-content">
                <h4>Map schema + Search &amp; Fill</h4>
                <p>Connect your data headers and populate a selected record instantly.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="homepage-mobile-demo" ref={demoRef} id="homepage-demo">
        <div className="mobile-demo-header">
          <p className="demo-kicker">Demo walkthrough</p>
          <h3>See the pipeline on mobile</h3>
          <p>
            Use the arrows to move through each state and see how DullyPDF prepares a database-ready template.
          </p>
        </div>
        <div className="mobile-demo-card">
          <div className="mobile-demo-media">
            <img src={activeStep.image} alt={activeStep.alt} loading="lazy" />
          </div>
          <div className="mobile-demo-content">
            <span className="mobile-demo-step">Step {activeDemoIndex + 1} of {DEMO_WALKTHROUGH.length}</span>
            <h4>{activeStep.title}</h4>
            <p>{activeStep.description}</p>
          </div>
          <div className="mobile-demo-nav" ref={demoNavRef}>
            <button
              type="button"
              className="mobile-demo-arrow"
              onClick={handlePrevStep}
              disabled={!hasPrev}
              aria-label="Previous demo step"
            >
              ←
            </button>
            <div className="mobile-demo-progress">
              {activeDemoIndex + 1} / {DEMO_WALKTHROUGH.length}
            </div>
            <button
              type="button"
              className="mobile-demo-arrow"
              onClick={handleNextStep}
              disabled={!hasNext}
              aria-label="Next demo step"
            >
              →
            </button>
          </div>
        </div>
      </section>

      <div className="homepage-content homepage-desktop-layout">
        {/* Left Panel - Project Description */}
        <div className="description-panel">
          <div className="description-content">
            <h2>AI-Powered PDF Form Generator</h2>

            <div className="description-text">
              <p className="lead-description">
                This software converts raw PDFs into fillable forms with writable areas at all input fields.
                Once you have your fillable form, you can upload a CSV, Excel, JSON, or TXT schema file locally and map
                field names to the PDF. CSV/Excel/JSON rows stay in the browser for Search &amp; Fill.
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
                      <h4>Schema Mapping &amp; Auto-Fill</h4>
                      <p>
                        Upload a CSV/Excel/JSON/TXT schema file locally, map PDF field names to your schema, and
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

              <div className="cta-buttons">
                <button
                  onClick={onStartWorkflow}
                  className="try-now-button"
                >
                  Try Now
                </button>
                {onStartDemo ? (
                  <button
                    onClick={onStartDemo}
                    className="demo-button"
                    type="button"
                  >
                    Demo
                  </button>
                ) : null}
              </div>

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
