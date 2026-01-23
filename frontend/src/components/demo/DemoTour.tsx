import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import './DemoTour.css';

export type DemoStep = {
  id: string;
  title: string;
  body: string;
  targetSelector?: string;
  placement?: 'top' | 'bottom' | 'left' | 'right';
  variant?: 'callout' | 'modal';
  primaryLabel?: string;
  showNext?: boolean;
  showBack?: boolean;
};

type DemoTourProps = {
  open: boolean;
  step: DemoStep | null;
  stepIndex: number;
  stepCount: number;
  onNext: () => void;
  onBack: () => void;
  onClose: () => void;
};

const CALLOUT_PADDING = 16;
const CALLOUT_GAP = 18;
const CALLOUT_ARROW = 10;
const CALLOUT_ARROW_TIP = 5;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function DemoTour({ open, step, stepIndex, stepCount, onNext, onBack, onClose }: DemoTourProps) {
  const calloutRef = useRef<HTMLDivElement | null>(null);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [calloutSize, setCalloutSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!open || !step?.targetSelector) {
      setTargetRect(null);
      return;
    }

    let rafId = 0;
    let rafFrames = 0;
    const maxFrames = 48;

    const updateRect = () => {
      const target = document.querySelector(step.targetSelector);
      setTargetRect(target instanceof Element ? target.getBoundingClientRect() : null);
    };

    const handleScroll = () => updateRect();
    const runRaf = () => {
      updateRect();
      rafFrames += 1;
      if (rafFrames < maxFrames) {
        rafId = window.requestAnimationFrame(runRaf);
      }
    };

    runRaf();
    window.addEventListener('resize', updateRect);
    window.addEventListener('scroll', handleScroll, true);

    const observer = new MutationObserver(() => updateRect());
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    if (document.fonts?.ready) {
      document.fonts.ready.then(updateRect).catch(() => undefined);
    }
    return () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      observer.disconnect();
      window.removeEventListener('resize', updateRect);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [open, step?.targetSelector]);

  useLayoutEffect(() => {
    if (!open || !calloutRef.current) return;
    const updateSize = () => {
      if (!calloutRef.current) return;
      setCalloutSize({
        width: calloutRef.current.offsetWidth,
        height: calloutRef.current.offsetHeight,
      });
    };
    updateSize();
    window.addEventListener('resize', updateSize);
    return () => window.removeEventListener('resize', updateSize);
  }, [open, step?.id]);

  const calloutMeta = useMemo(() => {
    if (!open || !step || step.variant === 'modal') return null;
    const placement = step.placement ?? 'bottom';
    const width = calloutSize.width || Math.min(360, window.innerWidth - CALLOUT_PADDING * 2);
    const height = calloutSize.height || 180;

    if (!targetRect) {
      const top = clamp(
        window.innerHeight / 2 - height / 2,
        CALLOUT_PADDING,
        window.innerHeight - height - CALLOUT_PADDING,
      );
      const left = clamp(
        window.innerWidth / 2 - width / 2,
        CALLOUT_PADDING,
        window.innerWidth - width - CALLOUT_PADDING,
      );
      const arrowLeft = width / 2;
      const arrowTop = height / 2;
      return {
        placement,
        top,
        left,
        width,
        height,
        arrowLeft,
        arrowTop,
        style: {
          top,
          left,
          ['--demo-arrow-left' as string]: `${arrowLeft}px`,
          ['--demo-arrow-top' as string]: `${arrowTop}px`,
        },
      };
    }

    const targetCenterX = targetRect.left + targetRect.width / 2;
    const targetCenterY = targetRect.top + targetRect.height / 2;

    let top = targetRect.bottom + CALLOUT_GAP;
    let left = targetCenterX - width / 2;

    if (placement === 'top') {
      top = targetRect.top - CALLOUT_GAP - height;
      left = targetCenterX - width / 2;
    } else if (placement === 'left') {
      top = targetCenterY - height / 2;
      left = targetRect.left - CALLOUT_GAP - width;
    } else if (placement === 'right') {
      top = targetCenterY - height / 2;
      left = targetRect.right + CALLOUT_GAP;
    }

    top = clamp(top, CALLOUT_PADDING, window.innerHeight - height - CALLOUT_PADDING);
    left = clamp(left, CALLOUT_PADDING, window.innerWidth - width - CALLOUT_PADDING);

    const arrowLeft = clamp(targetCenterX - left, 28, width - 28);
    const arrowTop = clamp(targetCenterY - top, 28, height - 28);

    return {
      placement,
      top,
      left,
      width,
      height,
      arrowLeft,
      arrowTop,
      style: {
        top,
        left,
        ['--demo-arrow-left' as string]: `${arrowLeft}px`,
        ['--demo-arrow-top' as string]: `${arrowTop}px`,
      },
    };
  }, [open, step, targetRect, calloutSize]);

  const connectorStyle = useMemo(() => {
    if (!open || !step || step.variant === 'modal') return null;
    if (!targetRect || !calloutMeta) return null;
    const placement = calloutMeta.placement ?? 'bottom';
    let startX = calloutMeta.left + calloutMeta.arrowLeft;
    let startY = calloutMeta.top - CALLOUT_ARROW_TIP;
    let endX = targetRect.left + targetRect.width / 2;
    let endY = targetRect.bottom;

    if (placement === 'top') {
      startY = calloutMeta.top + calloutMeta.height + CALLOUT_ARROW_TIP;
      endY = targetRect.top;
    } else if (placement === 'left') {
      startX = calloutMeta.left + calloutMeta.width + CALLOUT_ARROW_TIP;
      startY = calloutMeta.top + calloutMeta.arrowTop;
      endX = targetRect.left;
      endY = targetRect.top + targetRect.height / 2;
    } else if (placement === 'right') {
      startX = calloutMeta.left - CALLOUT_ARROW_TIP;
      startY = calloutMeta.top + calloutMeta.arrowTop;
      endX = targetRect.right;
      endY = targetRect.top + targetRect.height / 2;
    } else {
      startY = calloutMeta.top - CALLOUT_ARROW_TIP;
      endY = targetRect.bottom;
    }

    const dx = endX - startX;
    const dy = endY - startY;
    const length = Math.max(0, Math.hypot(dx, dy));
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
    return {
      left: startX,
      top: startY,
      width: length,
      transform: `rotate(${angle}deg)`,
    } as CSSProperties;
  }, [calloutMeta, open, step, targetRect]);

  if (!open || !step) return null;

  const isModal = step.variant === 'modal';
  const primaryLabel = step.primaryLabel ?? (stepIndex === stepCount - 1 ? 'Finish demo' : 'Next');
  const showNext = step.showNext ?? true;
  const showBack = step.showBack ?? true;

  return (
    <div className="demo-tour" aria-live="polite">
      <div className="demo-tour__backdrop" />
      {targetRect ? (
        <div
          className="demo-tour__highlight"
          style={{
            top: targetRect.top - 6,
            left: targetRect.left - 6,
            width: targetRect.width + 12,
            height: targetRect.height + 12,
          }}
        />
      ) : null}
      {connectorStyle ? <div className="demo-tour__connector" style={connectorStyle} /> : null}
      {isModal ? (
        <div className="demo-tour__modal" role="dialog" aria-modal="true" aria-labelledby="demo-tour-title">
          <div className="demo-tour__card" ref={calloutRef}>
            <div className="demo-tour__header">
              <span className="demo-tour__eyebrow">Demo step {stepIndex + 1} of {stepCount}</span>
              <button className="demo-tour__close" type="button" onClick={onClose}>
                Exit demo
              </button>
            </div>
            <h3 id="demo-tour-title" className="demo-tour__title">{step.title}</h3>
            <p className="demo-tour__body">{step.body}</p>
            <div className="demo-tour__actions">
              {showBack ? (
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={onBack}
                  disabled={stepIndex === 0}
                >
                  Back
                </button>
              ) : null}
              {showNext ? (
                <button
                  type="button"
                  className="ui-button ui-button--primary ui-button--compact"
                  onClick={onNext}
                >
                  {primaryLabel}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : (
        <div
          ref={calloutRef}
          className="demo-tour__callout"
          data-placement={step.placement ?? 'bottom'}
          style={(calloutMeta?.style ?? {}) as CSSProperties}
        >
          <div className="demo-tour__header">
            <span className="demo-tour__eyebrow">Demo step {stepIndex + 1} of {stepCount}</span>
            <button className="demo-tour__close" type="button" onClick={onClose}>
              Exit demo
            </button>
          </div>
          <h3 className="demo-tour__title">{step.title}</h3>
          <p className="demo-tour__body">{step.body}</p>
          <div className="demo-tour__actions">
            {showBack ? (
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={onBack}
                disabled={stepIndex === 0}
              >
                Back
              </button>
            ) : null}
            {showNext ? (
              <button
                type="button"
                className="ui-button ui-button--primary ui-button--compact"
                onClick={onNext}
              >
                {primaryLabel}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
