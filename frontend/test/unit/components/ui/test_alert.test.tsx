import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Alert } from '../../../../src/components/ui/Alert';

describe('Alert', () => {
  it.each([
    ['error', 'alert', 'assertive'],
    ['warning', 'alert', 'assertive'],
    ['info', 'status', 'polite'],
    ['success', 'status', 'polite'],
  ] as const)('maps tone %s to role and aria-live', (tone, role, ariaLive) => {
    render(<Alert tone={tone} message="Message body" />);

    const alertRoot = screen.getByText('Message body').closest('.ui-alert') as HTMLElement;
    expect(alertRoot).toBeTruthy();
    expect(alertRoot.getAttribute('role')).toBe(role);
    expect(alertRoot.getAttribute('aria-live')).toBe(ariaLive);
  });

  it('composes variant, size, tone, and custom classes', () => {
    render(
      <Alert
        tone="warning"
        variant="banner"
        size="sm"
        className="custom-alert"
        message="Custom alert"
      />,
    );

    const alertRoot = screen.getByText('Custom alert').closest('.ui-alert') as HTMLElement;
    expect(alertRoot.classList.contains('ui-alert--warning')).toBe(true);
    expect(alertRoot.classList.contains('ui-alert--banner')).toBe(true);
    expect(alertRoot.classList.contains('ui-alert--sm')).toBe(true);
    expect(alertRoot.classList.contains('custom-alert')).toBe(true);
  });

  it('renders optional title and dismiss action only when provided', () => {
    const { rerender } = render(<Alert message="No extras" />);

    expect(screen.queryByText('Important')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();

    rerender(<Alert title="Important" message="With extras" onDismiss={vi.fn()} dismissLabel="Close" />);
    expect(screen.getByText('Important')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
  });

  it('invokes onDismiss callback when dismiss button is clicked', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();

    render(<Alert message="Dismiss me" onDismiss={onDismiss} dismissLabel="Close alert" />);

    await user.click(screen.getByRole('button', { name: 'Close alert' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
