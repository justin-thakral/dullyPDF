import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HeaderBar } from '../../../../src/components/layout/HeaderBar';

type HeaderBarProps = ComponentProps<typeof HeaderBar>;

function createProps(overrides: Partial<HeaderBarProps> = {}): HeaderBarProps {
  return {
    pageCount: 8,
    currentPage: 2,
    scale: 1.5,
    userEmail: 'owner@example.com',
    onOpenProfile: vi.fn(),
    onSignIn: vi.fn(),
    onSignOut: vi.fn(),
    onScaleChange: vi.fn(),
    onNavigateHome: vi.fn(),
    dataSourceKind: 'none',
    dataSourceLabel: null,
    onChooseDataSource: vi.fn(),
    onClearDataSource: vi.fn(),
    mappingInProgress: false,
    mapSchemaInProgress: false,
    hasMappedSchema: false,
    onMapSchema: vi.fn(),
    canMapSchema: true,
    renameInProgress: false,
    hasRenamedFields: false,
    onRename: vi.fn(),
    onRenameAndMap: vi.fn(),
    canRename: true,
    canRenameAndMap: true,
    onOpenSearchFill: vi.fn(),
    canSearchFill: true,
    onDownload: vi.fn(),
    onSaveToProfile: vi.fn(),
    downloadInProgress: false,
    saveInProgress: false,
    canDownload: true,
    canSave: true,
    demoLocked: false,
    onDemoLockedAction: vi.fn(),
    ...overrides,
  };
}

describe('HeaderBar', () => {
  it('shows page/zoom metadata and authenticated account controls', async () => {
    const user = userEvent.setup();
    const props = createProps();

    render(<HeaderBar {...props} />);

    expect(screen.getByText('2 / 8')).toBeTruthy();
    expect(screen.getByText('150%')).toBeTruthy();
    expect((screen.getByRole('slider', { name: 'Zoom' }) as HTMLInputElement).value).toBe('1.5');

    await user.click(screen.getByRole('button', { name: 'Return to homepage' }));
    await user.click(screen.getByRole('button', { name: /owner@example\.com/i }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(props.onNavigateHome).toHaveBeenCalledTimes(1);
    expect(props.onOpenProfile).toHaveBeenCalledTimes(1);
    expect(props.onSignOut).toHaveBeenCalledTimes(1);
  });

  it('shows sign-in control when no user is signed in', async () => {
    const user = userEvent.setup();
    const onSignIn = vi.fn();

    render(
      <HeaderBar
        {...createProps({
          userEmail: undefined,
          onOpenProfile: undefined,
          onSignOut: undefined,
          onSignIn,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(onSignIn).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('opens and closes the data source menu, including outside click dismissal', async () => {
    const user = userEvent.setup();
    const onChooseDataSource = vi.fn();
    const onClearDataSource = vi.fn();

    render(
      <HeaderBar
        {...createProps({
          dataSourceKind: 'excel',
          dataSourceLabel: 'rows.xlsx',
          onChooseDataSource,
          onClearDataSource,
        })}
      />,
    );

    const dataButton = screen.getByRole('button', { name: /Connected XLS/i });
    await user.click(dataButton);
    expect(screen.getByRole('menu', { name: 'Choose data source' })).toBeTruthy();

    await user.click(screen.getByRole('menuitem', { name: /CSV file/i }));
    expect(onChooseDataSource).toHaveBeenCalledTimes(1);
    expect(onChooseDataSource).toHaveBeenCalledWith('csv');
    expect(screen.queryByRole('menu', { name: 'Choose data source' })).toBeNull();

    await user.click(dataButton);
    expect(screen.getByRole('menu', { name: 'Choose data source' })).toBeTruthy();
    await user.click(document.body);
    expect(screen.queryByRole('menu', { name: 'Choose data source' })).toBeNull();

    await user.click(dataButton);
    await user.click(screen.getByRole('menuitem', { name: 'Clear data source' }));
    expect(onClearDataSource).toHaveBeenCalledTimes(1);
  });

  it('applies enabled/disabled rules for mapping, rename, and search controls', () => {
    const props = createProps();
    const { rerender } = render(<HeaderBar {...props} />);

    const mapButton = screen.getByRole('button', { name: 'Map Schema' }) as HTMLButtonElement;
    const renameButton = screen.getByRole('button', { name: 'Rename' }) as HTMLButtonElement;
    const renameMapButton = screen.getByRole('button', { name: 'Rename + Map' }) as HTMLButtonElement;
    const searchButton = screen.getByRole('button', { name: 'Search, Fill & Clear' }) as HTMLButtonElement;

    expect(mapButton.disabled).toBe(false);
    expect(renameButton.disabled).toBe(false);
    expect(renameMapButton.disabled).toBe(false);
    expect(searchButton.disabled).toBe(false);

    rerender(
      <HeaderBar
        {...props}
        mappingInProgress
        canSearchFill={false}
      />,
    );

    expect((screen.getByRole('button', { name: 'Map Schema' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Rename' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Rename + Map' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Search, Fill & Clear' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Requires CSV/Excel/JSON rows')).toBeTruthy();
  });

  it('keeps demo-locked actions blocked except download', async () => {
    const user = userEvent.setup();
    const onDemoLockedAction = vi.fn();
    const onRename = vi.fn();
    const onMapSchema = vi.fn();
    const onRenameAndMap = vi.fn();
    const onDownload = vi.fn();
    const onSaveToProfile = vi.fn();

    render(
      <HeaderBar
        {...createProps({
          demoLocked: true,
          onDemoLockedAction,
          canMapSchema: false,
          canRename: false,
          canRenameAndMap: false,
          canDownload: false,
          canSave: false,
          onRename,
          onMapSchema,
          onRenameAndMap,
          onDownload,
          onSaveToProfile,
        })}
      />,
    );

    const dataButton = screen.getByRole('button', { name: /^Schema/i });
    const renameButton = screen.getByRole('button', { name: 'Rename' }) as HTMLButtonElement;
    const mapButton = screen.getByRole('button', { name: 'Map Schema' }) as HTMLButtonElement;
    const renameMapButton = screen.getByRole('button', { name: 'Rename + Map' }) as HTMLButtonElement;
    const downloadButton = screen.getByRole('button', { name: 'Download' }) as HTMLButtonElement;
    const saveButton = screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement;

    expect(renameButton.disabled).toBe(false);
    expect(mapButton.disabled).toBe(false);
    expect(renameMapButton.disabled).toBe(false);
    expect(downloadButton.disabled).toBe(false);
    expect(saveButton.disabled).toBe(false);

    await user.click(dataButton);
    await user.click(renameButton);
    await user.click(mapButton);
    await user.click(renameMapButton);
    await user.click(downloadButton);
    await user.click(saveButton);

    expect(onDemoLockedAction).toHaveBeenCalledTimes(5);
    expect(screen.queryByRole('menu', { name: 'Choose data source' })).toBeNull();
    expect(onRename).not.toHaveBeenCalled();
    expect(onMapSchema).not.toHaveBeenCalled();
    expect(onRenameAndMap).not.toHaveBeenCalled();
    expect(onDownload).toHaveBeenCalledTimes(1);
    expect(onSaveToProfile).not.toHaveBeenCalled();
  });

  it('wires download/save callbacks and updates loading button states', async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();
    const onSaveToProfile = vi.fn();
    const props = createProps({ onDownload, onSaveToProfile });
    const { rerender } = render(<HeaderBar {...props} />);

    await user.click(screen.getByRole('button', { name: 'Download' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onDownload).toHaveBeenCalledTimes(1);
    expect(onSaveToProfile).toHaveBeenCalledTimes(1);

    rerender(<HeaderBar {...props} downloadInProgress saveInProgress />);

    const downloadingButton = screen.getByRole('button', { name: 'Downloading...' }) as HTMLButtonElement;
    const savingButton = screen.getByRole('button', { name: 'Saving...' }) as HTMLButtonElement;

    expect(downloadingButton.disabled).toBe(true);
    expect(savingButton.disabled).toBe(true);
  });
});
