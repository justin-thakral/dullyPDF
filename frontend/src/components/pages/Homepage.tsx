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
  authPending?: boolean;
  onSignIn?: () => void;
  onOpenProfile?: () => void;
  onInitialRenderReady?: () => void;
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
      'Use the inspector to add, rename, and adjust text, checkbox, and radio field types without touching the PDF source.',
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
    title: 'Search & Fill or Fill By Link completes the form',
    description:
      'Pull a local record or choose a stored Fill By Link respondent record and populate every mapped field in seconds.',
    imageWebp: '/demo/mobile-filled.webp',
    imagePng: '/demo/mobile-filled.png',
    alt: 'Completed PDF form with patient data filled into the detected fields.',
  },
  {
    id: 'link-generated',
    title: 'Generate a shareable link for respondents',
    description:
      'After saving the template, publish a DullyPDF link you can send to users so they can submit the form without opening the PDF editor.',
    imageWebp: '/demo/link-generated.webp',
    imagePng: '/demo/link-generated.png',
    alt: 'Generated Fill By Link panel showing a shareable respondent link for the saved template.',
  },
  {
    id: 'mock-form',
    title: 'Respondents fill a mock form, not the PDF',
    description:
      'The public link opens a mobile-friendly HTML form where users submit answers. DullyPDF stores the response so you can generate the PDF later.',
    imageWebp: '/demo/mock-form.webp',
    imagePng: '/demo/mock-form.png',
    alt: 'Mock respondent form showing public question fields that collect answers outside the PDF editor.',
  },
  {
    id: 'create-group',
    title: 'Create groups for full document workflows',
    description:
      'Open a group to search and fill an entire packet, then rename and remap every template in that group at once for larger document workflows.',
    imageWebp: '/demo/create-group.webp',
    imagePng: '/demo/create-group.png',
    alt: 'Create Group workflow showing grouped templates for packet-wide Search and Fill and batch Rename + Map.',
  },
];

/**
 * Landing page describing the end-to-end workflow.
 */
const Homepage: React.FC<HomepageProps> = ({
  onStartWorkflow,
  onStartDemo,
  userEmail,
  authPending,
  onSignIn,
  onOpenProfile,
  onInitialRenderReady,
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
  const initialRenderReadyRef = useRef(false);
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

  useEffect(() => {
    if (!onInitialRenderReady || initialRenderReadyRef.current) return;

    let cancelled = false;
    const waitForNextFrame = () => new Promise<void>((resolve) => {
      if (typeof window === 'undefined') {
        resolve();
        return;
      }
      window.requestAnimationFrame(() => resolve());
    });

    const reportInitialRenderReady = async () => {
      if (typeof document !== 'undefined' && 'fonts' in document && document.fonts?.ready) {
        try {
          await document.fonts.ready;
        } catch {
          // Ignore font readiness errors and continue to the next frame barrier.
        }
      }

      // The desktop landing page applies a measured fit scale after mount and again
      // after fonts resolve. Waiting a couple of frames lets those post-mount writes
      // land before the splash screen is removed.
      await waitForNextFrame();
      await waitForNextFrame();

      if (cancelled || initialRenderReadyRef.current) return;
      initialRenderReadyRef.current = true;
      onInitialRenderReady();
    };

    void reportInitialRenderReady();

    return () => {
      cancelled = true;
    };
  }, [onInitialRenderReady]);

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
  ) : authPending ? (
    <span className="homepage-auth-button homepage-auth-button--pending" aria-busy="true">
      Sign in
    </span>
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
            DullyPDF converts raw PDFs into editable templates with precise form fields. Then you can either search
            local CSV, Excel, JSON, or TXT data or publish a native Fill By Link from a saved template so respondents
            can answer from a phone.
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
                <h4>Publish Fill By Link or map local data</h4>
                <p>Save the template, then either connect local rows or publish a DullyPDF-hosted HTML form link.</p>
              </div>
            </div>
            <div className="feature-item">
              <span className="feature-number">5</span>
              <div className="feature-content">
                <h4>Select a respondent and generate the PDF</h4>
                <p>Choose a saved respondent record inside DullyPDF and create the final PDF only when it is needed.</p>
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
            Use the arrows to move through each state and see how DullyPDF prepares a database-ready template that can
            be filled from local data or a native Fill By Link respondent record.
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
              <h1 className="homepage-main-title">Automatic PDF Templates, Fill By Link, and Database Mapping</h1>

              <div className="description-text">
                <p className="lead-description">
                  This software converts raw PDFs into fillable forms using 
                  {' '}
                  <CommonFormsAttribution />
                  {' '}
                  for field detections with writable areas at input fields.
                  It supports text fields, checkbox groups, radio groups, dates, and signatures in the editor.
                  Once your form is ready, you can upload a CSV, Excel, JSON, or TXT schema file and map
                  field names to the PDF, or publish a native DullyPDF Fill By Link from a saved template so up to 10,000 respondents can
                  submit data through a mobile-friendly HTML form to be filled in on your PDF. Database rows stay in browser for Search
                  &amp; Fill.
                </p>

                <div className="features-section">
                  <h3>Complete Workflow Process</h3>
                  <div className="feature-list">
              
                    <div className="feature-item">
                      <span className="feature-number">1</span>
                      <div className="feature-content">
                        <h4>PDF to Form with AI-Powered Field Detection</h4>
                        <p>
                          The detection pipeline analyzes your PDF and automatically identifies
                          potential form fields with confidence scoring and field names pulled from nearby labels.
                        </p>
                      </div>
                    </div>

                    <div className="feature-item">
                      <span className="feature-number">2</span>
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
                      <span className="feature-number">3</span>
                      <div className="feature-content">
                        <h4>Publish Native Fill By Link or Connect Local Data</h4>
                        <p>
                          Save the template, then either publish a DullyPDF-hosted HTML form link or upload a
                          CSV/Excel/JSON/TXT schema file locally for Search &amp; Fill preparation.
                        </p>
                      </div>
                    </div>

                    <div className="feature-item">
                      <span className="feature-number">4</span>
                      <div className="feature-content">
                        <h4>Search, Select, and Generate the Final PDF</h4>
                        <p>
                          Choose a local row or a stored respondent submission in the workspace. DullyPDF fills the
                          template and creates the PDF only when you download it.
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
                <h3>Build, Share, and Fill Faster</h3>
                <p className="cta-description">
                  Click <strong>Try Now</strong> to upload your PDF document and use AI-driven form field detection,
                  the form builder, native Fill By Link, and database mapping. 
                  The <strong>Demo</strong> is interactive and live. Use <strong>Contact</strong> to send me a
                  message.
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
                  <a href="/free-features" className="info-item info-item--link" aria-label="View free features">
                    <span className="info-main">
                      <span className="info-label">Free Feats:</span>
                      <span className="info-value">Unlimited PDF to form and form builder</span>
                    </span>
                    <span className="info-cta">View</span>
                  </a>
                  <a href="/premium-features" className="info-item info-item--link" aria-label="View premium features">
                    <span className="info-main">
                      <span className="info-label">Premium Feats:</span>
                      <span className="info-value">High usage for all DullyPDF features.</span>
                    </span>
                    <span className="info-cta">View</span>
                  </a>
                </div>
              </div>

              <div className="tech-note">
                <h4>Powered by Advanced Technology</h4>
                <p>
                  Built using PDF.js rendering for precision geometry,
                  React for responsive interfaces, and AI workflows for intelligent field detection and naming.
                  Respondent answers stay structured so owners can reopen the workspace, search a respondent list, and
                  generate the final PDF only when it is needed.
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
