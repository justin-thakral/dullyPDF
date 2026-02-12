import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DemoTour, type DemoStep } from '../../../../src/components/demo/DemoTour';

function makeStep(overrides: Partial<DemoStep> = {}): DemoStep {
  return {
    id: 'step-1',
    title: 'Step title',
    body: 'Step body',
    ...overrides,
  };
}

function rect({
  left,
  top,
  width,
  height,
}: {
  left: number;
  top: number;
  width: number;
  height: number;
}): DOMRect {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

describe('DemoTour', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      writable: true,
      value: 1200,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      writable: true,
      value: 900,
    });
  });

  it('renders nothing when closed or when step is null', () => {
    const { rerender } = render(
      <DemoTour
        open={false}
        step={makeStep()}
        stepIndex={0}
        stepCount={3}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText('Step title')).toBeNull();

    rerender(
      <DemoTour
        open
        step={null}
        stepIndex={0}
        stepCount={3}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText('Step title')).toBeNull();
  });

  it('renders callout and modal variants', () => {
    const { rerender, container } = render(
      <DemoTour
        open
        step={makeStep({ variant: 'callout' })}
        stepIndex={0}
        stepCount={2}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector('.demo-tour__callout')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();

    rerender(
      <DemoTour
        open
        step={makeStep({ id: 'modal-step', variant: 'modal' })}
        stepIndex={0}
        stepCount={2}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(container.querySelector('.demo-tour__callout')).toBeNull();
  });

  it('resolves target selector for highlight/connector and falls back when target is missing', async () => {
    const target = document.createElement('div');
    target.id = 'demo-target';
    target.getBoundingClientRect = () => rect({ left: 200, top: 120, width: 140, height: 60 });
    document.body.appendChild(target);

    const { rerender, container } = render(
      <DemoTour
        open
        step={makeStep({ targetSelector: '#demo-target', placement: 'right' })}
        stepIndex={1}
        stepCount={3}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector('.demo-tour__highlight')).toBeTruthy();
      expect(container.querySelector('.demo-tour__connector')).toBeTruthy();
    });

    rerender(
      <DemoTour
        open
        step={makeStep({ id: 'missing', targetSelector: '#missing-target', placement: 'left' })}
        stepIndex={1}
        stepCount={3}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector('.demo-tour__highlight')).toBeNull();
    });

    const callout = container.querySelector('.demo-tour__callout') as HTMLDivElement;
    expect(callout).toBeTruthy();
    expect(callout.dataset.placement).toBe('left');
    expect(callout.style.top).not.toBe('');
    expect(callout.style.left).not.toBe('');
  });

  it('falls back to a non-overlapping placement when preferred placement overlaps target', async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      writable: true,
      value: 600,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      writable: true,
      value: 360,
    });

    const target = document.createElement('div');
    target.id = 'overlap-target';
    target.getBoundingClientRect = () => rect({ left: 220, top: 290, width: 100, height: 40 });
    document.body.appendChild(target);

    const { container } = render(
      <DemoTour
        open
        step={makeStep({
          id: 'placement-step',
          targetSelector: '#overlap-target',
          placement: 'bottom',
        })}
        stepIndex={0}
        stepCount={3}
        onNext={vi.fn()}
        onBack={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      const callout = container.querySelector('.demo-tour__callout') as HTMLDivElement;
      expect(callout.dataset.placement).toBe('top');
    });
  });

  it('wires action callbacks and respects button visibility rules', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    const onBack = vi.fn();
    const onClose = vi.fn();
    const { rerender } = render(
      <DemoTour
        open
        step={makeStep({ showBack: true, showNext: true })}
        stepIndex={0}
        stepCount={2}
        onNext={onNext}
        onBack={onBack}
        onClose={onClose}
      />,
    );

    const backButton = screen.getByRole('button', { name: 'Back' }) as HTMLButtonElement;
    expect(backButton.disabled).toBe(true);
    await user.click(backButton);
    expect(onBack).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(onNext).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Exit demo' }));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(
      <DemoTour
        open
        step={makeStep({ id: 'hidden-actions', showBack: false, showNext: false })}
        stepIndex={1}
        stepCount={2}
        onNext={onNext}
        onBack={onBack}
        onClose={onClose}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Finish demo' })).toBeNull();

    rerender(
      <DemoTour
        open
        step={makeStep({ id: 'finish-label' })}
        stepIndex={1}
        stepCount={2}
        onNext={onNext}
        onBack={onBack}
        onClose={onClose}
      />,
    );
    expect(screen.getByRole('button', { name: 'Finish demo' })).toBeTruthy();
  });
});
