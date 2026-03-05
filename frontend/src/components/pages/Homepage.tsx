/**
 * Homepage Component for DullyPDF
 *
 * Desktop keeps the original two-panel layout.
 * Mobile shows a dedicated walkthrough-only experience.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import './Homepage.css';
import { CommonFormsAttribution } from '../ui/CommonFormsAttribution';
import { ContactDialog } from '../features/ContactDialog';
import { SiteFooter } from '../ui/SiteFooter';

interface HomepageProps {
  onStartWorkflow: () => void;
  onStartDemo?: () => void;
  userEmail?: string | null;
  onSignIn?: () => void;
  onOpenProfile?: () => void;
}

type DemoWalkthroughStep = {
  id: string;
  title: ReactNode;
  description: ReactNode;
  imageWebp: string;
  imagePng: string;
  alt: string;
};

const DEMO_WALKTHROUGH: DemoWalkthroughStep[] = [
  {
    id: 'raw-pdf',
    title: 'Start with the raw intake PDF',
    description:
      'Begin with the source form exactly as the clinic provides it. DullyPDF reads the layout before any edits.',
    imageWebp: '/demo/mobile-raw-pdf.webp',
    imagePng: '/demo/mobile-raw-pdf.png',
    alt: 'Raw PDF intake form with blank fields and section headers.',
  },
  {
    id: 'commonforms',
    title: (
      <>
        Candidate fields highlighted with <CommonFormsAttribution />
      </>
    ),
    description:
      'The ML detector finds input regions and labels them with confidence-scored field tags for review.',
    imageWebp: '/demo/mobile-commonforms.webp',
    imagePng: '/demo/mobile-commonforms.png',
    alt: 'Detected fields overlayed on the PDF with CommonForms by jbarrow tag labels.',
  },
  {
    id: 'inspector',
    title: 'Inspector for precise edits',
    description:
      'Use the inspector to add, rename, and adjust field types without touching the PDF source.',
    imageWebp: '/demo/mobile-inspector.webp',
    imagePng: '/demo/mobile-inspector.png',
    alt: 'Field inspector panel showing add field actions and edit controls.',
  },
  {
    id: 'field-list',
    title: 'Field list to filter and audit',
    description:
      'Review every detected field, filter by confidence, and verify sizes or pages with quick scanning.',
    imageWebp: '/demo/mobile-field-list.webp',
    imagePng: '/demo/mobile-field-list.png',
    alt: 'Field list panel with confidence filters and detected field entries.',
  },
  {
    id: 'rename-remap',
    title: 'OpenAI rename + OpenAI remap',
    description:
      'OpenAI rename standardizes field names, and OpenAI remap aligns them to database columns so the template is ready for database plug-ins.',
    imageWebp: '/demo/mobile-rename-remap.webp',
    imagePng: '/demo/mobile-rename-remap.png',
    alt: 'PDF overlay showing standardized field names after rename and remap.',
  },
  {
    id: 'filled',
    title: 'Search & Fill completes the form',
    description:
      'Pull a record from your data source and populate every mapped field in seconds.',
    imageWebp: '/demo/mobile-filled.webp',
    imagePng: '/demo/mobile-filled.png',
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
  const descriptionPanelRef = useRef<HTMLDivElement | null>(null);
  const descriptionContentRef = useRef<HTMLDivElement | null>(null);
  const actionPanelRef = useRef<HTMLDivElement | null>(null);
  const actionContentRef = useRef<HTMLDivElement | null>(null);
  const [activeDemoIndex, setActiveDemoIndex] = useState(0);
  const [demoFocusActive, setDemoFocusActive] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [desktopFitScale, setDesktopFitScale] = useState(1);
  const userInitial = useMemo(() => (userEmail ? userEmail.charAt(0).toUpperCase() : null), [userEmail]);

  const activeStep = DEMO_WALKTHROUGH[activeDemoIndex];
  const hasPrev = activeDemoIndex > 0;
  const hasNext = activeDemoIndex < DEMO_WALKTHROUGH.length - 1;

  const pendingScrollBehavior = useRef<ScrollBehavior | null>(null);

  const scrollDemoToViewportBottom = (behavior: ScrollBehavior) => {
    if (typeof window === 'undefined') return;

    // On mobile we keep the demo card pinned to the bottom of the viewport while stepping.
    // This avoids scrolling all the way to the page footer (which sits below the demo).
    const anchor = demoNavRef.current ?? demoRef.current;
    if (!anchor) return;

    const rect = anchor.getBoundingClientRect();
    const anchorBottom = rect.bottom + window.scrollY;
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const targetTop = Math.min(maxScroll, Math.max(0, anchorBottom - window.innerHeight));
    window.scrollTo({ top: targetTop, behavior });
  };

  const requestBottomScroll = (behavior: ScrollBehavior) => {
    pendingScrollBehavior.current = behavior;
    scrollDemoToViewportBottom(behavior);
  };

  const handleScrollToDemo = () => {
    setDemoFocusActive(true);
    requestBottomScroll('smooth');
  };

  const handlePrevStep = () => {
    setDemoFocusActive(true);
    setActiveDemoIndex((prev) => Math.max(0, prev - 1));
    requestBottomScroll('auto');
  };

  const handleNextStep = () => {
    setDemoFocusActive(true);
    setActiveDemoIndex((prev) => Math.min(DEMO_WALKTHROUGH.length - 1, prev + 1));
    requestBottomScroll('auto');
  };

  const handleOpenContact = () => {
    setContactOpen(true);
  };

  const handleCloseContact = () => {
    setContactOpen(false);
  };

  const computeDesktopFitScale = useCallback(() => {
    if (typeof window === 'undefined') return;
    if (window.matchMedia('(max-width: 1020px)').matches) {
      setDesktopFitScale(1);
      return;
    }

    const leftPanel = descriptionPanelRef.current;
    const leftContent = descriptionContentRef.current;
    const rightPanel = actionPanelRef.current;
    const rightContent = actionContentRef.current;
    if (!leftPanel || !leftContent || !rightPanel || !rightContent) return;

    const leftMinVisualGap = 36;
    const rightMinVisualGap = 48;
    const fitSafetyOffset = 8;
    const leftTargetHeight = Math.max(0, leftPanel.clientHeight - leftMinVisualGap - fitSafetyOffset);
    const rightTargetHeight = Math.max(0, rightPanel.clientHeight - rightMinVisualGap - fitSafetyOffset);
    const leftRatio = leftContent.scrollHeight > 0 ? leftTargetHeight / leftContent.scrollHeight : 1;
    const rightRatio = rightContent.scrollHeight > 0 ? rightTargetHeight / rightContent.scrollHeight : 1;

    const minScale =
      window.innerHeight <= 680
        ? 0.72
        : window.innerHeight <= 760
          ? 0.78
          : window.innerHeight <= 900
            ? 0.84
            : 0.9;
    let nextScale = Math.max(minScale, Math.min(1, leftRatio, rightRatio));
    if (nextScale >= 0.993 && window.innerWidth >= 1536 && window.innerHeight <= 1020) {
      nextScale = 0.988;
    }
    const roundedScale = Number(nextScale.toFixed(3));
    setDesktopFitScale((prev) => (Math.abs(prev - roundedScale) < 0.004 ? prev : roundedScale));
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mediaQuery = window.matchMedia('(max-width: 1020px)');
    const heightQuery = window.matchMedia('(max-height: 749px)');
    const updateScrollLock = () => {
      const shouldLockScroll = !mediaQuery.matches && !heightQuery.matches;
      document.documentElement.classList.toggle('homepage-no-scroll', shouldLockScroll);
      document.body.classList.toggle('homepage-no-scroll', shouldLockScroll);
    };

    updateScrollLock();
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', updateScrollLock);
      heightQuery.addEventListener('change', updateScrollLock);
    } else {
      const legacyMediaQuery = mediaQuery as MediaQueryList & {
        addListener: (listener: (event: MediaQueryListEvent) => void) => void;
        removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
      };
      const legacyHeightQuery = heightQuery as MediaQueryList & {
        addListener: (listener: (event: MediaQueryListEvent) => void) => void;
        removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
      };
      legacyMediaQuery.addListener(updateScrollLock);
      legacyHeightQuery.addListener(updateScrollLock);
    }
    window.addEventListener('resize', updateScrollLock);
    return () => {
      if (typeof mediaQuery.removeEventListener === 'function') {
        mediaQuery.removeEventListener('change', updateScrollLock);
        heightQuery.removeEventListener('change', updateScrollLock);
      } else {
        const legacyMediaQuery = mediaQuery as MediaQueryList & {
          addListener: (listener: (event: MediaQueryListEvent) => void) => void;
          removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
        };
        const legacyHeightQuery = heightQuery as MediaQueryList & {
          addListener: (listener: (event: MediaQueryListEvent) => void) => void;
          removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
        };
        legacyMediaQuery.removeListener(updateScrollLock);
        legacyHeightQuery.removeListener(updateScrollLock);
      }
      window.removeEventListener('resize', updateScrollLock);
      document.documentElement.classList.remove('homepage-no-scroll');
      document.body.classList.remove('homepage-no-scroll');
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!window.matchMedia('(max-width: 1020px)').matches) return;
    if (!demoFocusActive) return;
    const behavior = pendingScrollBehavior.current ?? 'auto';
    pendingScrollBehavior.current = null;
    const raf = requestAnimationFrame(() => {
      scrollDemoToViewportBottom(behavior);
    });
    const timeout = window.setTimeout(() => {
      scrollDemoToViewportBottom(behavior);
    }, 150);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timeout);
    };
  }, [activeDemoIndex, demoFocusActive]);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    let rafId = 0;
    const scheduleFitCheck = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        computeDesktopFitScale();
      });
    };

    scheduleFitCheck();
    window.addEventListener('resize', scheduleFitCheck);

    let resizeObserver: ResizeObserver | null = null;
    if (typeof window.ResizeObserver === 'function') {
      resizeObserver = new window.ResizeObserver(() => {
        scheduleFitCheck();
      });
      if (descriptionPanelRef.current) resizeObserver.observe(descriptionPanelRef.current);
      if (actionPanelRef.current) resizeObserver.observe(actionPanelRef.current);
      if (descriptionContentRef.current) resizeObserver.observe(descriptionContentRef.current);
      if (actionContentRef.current) resizeObserver.observe(actionContentRef.current);
    }

    if (typeof document !== 'undefined' && 'fonts' in document && document.fonts?.ready) {
      void document.fonts.ready.then(() => {
        scheduleFitCheck();
      });
    }

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', scheduleFitCheck);
      if (resizeObserver) resizeObserver.disconnect();
    };
  }, [computeDesktopFitScale]);

  const homepageStyle = useMemo(
    () => ({ '--homepage-fit-scale': desktopFitScale } as CSSProperties),
    [desktopFitScale],
  );

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
    <div className="homepage-container" style={homepageStyle}>
      <header className="homepage-mobile-header">
        <div className="homepage-mobile-header__row">
          <span className="homepage-mobile-tagline">Automatic PDF-&gt;Template</span>
          <div className="homepage-mobile-actions">
            {authAction}
            <div className="homepage-mobile-logo">
              <picture>
                <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
                <img
                  className="homepage-logo-image"
                  src="/DullyPDFLogoImproved.png"
                  alt="DullyPDF"
                  fetchPriority="high"
                  decoding="async"
                />
              </picture>
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
          <button type="button" className="mobile-contact-button" onClick={handleOpenContact}>
            Contact
          </button>
          <a href="/usage-docs" className="mobile-contact-button mobile-legal-button">
            Docs &amp; Privacy &amp; Terms
          </a>
        </div>

        <div className="mobile-copy">
          <p className="mobile-description">
            DullyPDF converts raw PDFs into editable templates with precise form fields. Upload a CSV, Excel, JSON, or
            TXT schema locally, standardize field names with OpenAI, and map them to your database columns for Search
            &amp; Fill.
          </p>
          <p className="mobile-description">
            If you are searching for ways to fill information in PDF files, generate PDF database templates, or clean
            fillable form field names before auto-fill, these workflows are supported in one pipeline with
            {' '}
            <CommonFormsAttribution />
            {' '}
            for field detections.
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
                <h4>Detect fields with <CommonFormsAttribution /></h4>
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
            <picture>
              <source srcSet={activeStep.imageWebp} type="image/webp" />
              <img
                src={activeStep.imagePng}
                alt={activeStep.alt}
                loading="lazy"
                decoding="async"
                onLoad={() => {
                  if (demoFocusActive) {
                    scrollDemoToViewportBottom('auto');
                  }
                }}
              />
            </picture>
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

      <div className="homepage-content-shell">
        <div className="homepage-content homepage-desktop-layout">
          {/* Left Panel - Project Description */}
          <div className="description-panel" ref={descriptionPanelRef}>
            <div className="description-content" ref={descriptionContentRef}>
              <h1 className="homepage-main-title">Automatic PDF to Fillable Form and Database Template Mapping</h1>

              <div className="description-text">
                <p className="lead-description">
                  This software converts raw PDFs into fillable forms with writable areas at input fields.
                  Once your fillable form is ready, you can upload a CSV, Excel, JSON, or TXT schema file locally and map
                  field names to the PDF. CSV/Excel/JSON rows stay in the browser for Search &amp; Fill, with
                  {' '}
                  <CommonFormsAttribution />
                  {' '}
                  for field detections.
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
          <div className="action-panel" ref={actionPanelRef}>
            <div className="action-content" ref={actionContentRef}>
              <div className="cta-section">
                <h3>Ready to Get Started?</h3>
                <p className="cta-description">
                  Click <strong>Try Now</strong> to upload your PDF document and experience AI-driven
                  form field detection, generation and database mapping, pdf to fillable form is <strong>free</strong>! The <strong>Demo</strong> is interactive 
                  and live, <strong>Contact</strong> to send me a message.
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
                  <button type="button" className="contact-button" onClick={handleOpenContact}>
                    Contact
                  </button>
                </div>

                <div className="quick-info">
                  <div className="info-item">
                    <span className="info-label">Supported:</span>
                    <span className="info-value">PDF files up to 50MB</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Processing:</span>
                    <span className="info-value">Typically 30 seconds per page</span>
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
      <SiteFooter />
      <ContactDialog open={contactOpen} onClose={handleCloseContact} defaultEmail={userEmail} />
    </div>
  );
};

export default Homepage;
