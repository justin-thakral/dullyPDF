import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
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

    expect(screen.getByText('Page 2/8')).toBeTruthy();
    expect((screen.getByRole('spinbutton', { name: 'Zoom percentage' }) as HTMLInputElement).value).toBe('150');

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
    expect(screen.getByText('Requires CSV/Excel/JSON/respondent rows')).toBeTruthy();
  });

  it('keeps Fill By Web Form Link clickable when the workspace needs to surface a banner guard', async () => {
    const user = userEvent.setup();
    const onOpenFillLink = vi.fn();

    render(
      <HeaderBar
        {...createProps({
          onOpenFillLink,
          canFillLink: true,
        })}
      />,
    );

    const fillLinkButton = screen.getByRole('button', { name: 'Fill By Web Form Link' }) as HTMLButtonElement;
    expect(fillLinkButton.disabled).toBe(false);

    await user.click(fillLinkButton);

    expect(onOpenFillLink).toHaveBeenCalledTimes(1);
  });

  it('renders API Fill beside download for saved templates', async () => {
    const user = userEvent.setup();
    const onOpenTemplateApi = vi.fn();

    render(
      <HeaderBar
        {...createProps({
          onOpenTemplateApi,
          canOpenTemplateApi: true,
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'API Fill' }));

    expect(onOpenTemplateApi).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Download' })).toBeTruthy();
  });

  it('switches into group mode with a selector and batch rename + map action', async () => {
    const user = userEvent.setup();
    const onSelectGroupTemplate = vi.fn();
    const onRenameAndMapGroup = vi.fn();

    render(
      <HeaderBar
        {...createProps({
          groupName: 'Admissions',
          groupTemplates: [
            { id: 'tpl-a', name: 'Alpha Packet' },
            { id: 'tpl-b', name: 'Bravo Intake' },
          ],
          activeGroupTemplateId: 'tpl-a',
          onSelectGroupTemplate,
          onRenameAndMapGroup,
          canRenameAndMapGroup: true,
          renameAndMapGroupButtonLabel: 'Rename + Map 1/2',
        })}
      />,
    );

    expect(screen.getByRole('button', { name: 'Open template in Admissions' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Rename + Map 1/2' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Rename' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Map Schema' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Rename + Map' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Open template in Admissions' }));
    await user.click(screen.getByRole('option', { name: 'Bravo Intake' }));
    await user.click(screen.getByRole('button', { name: 'Rename + Map 1/2' }));

    expect(onSelectGroupTemplate).toHaveBeenCalledWith('tpl-b');
    expect(onRenameAndMapGroup).toHaveBeenCalledTimes(1);
  });

  it('shows cached group template readiness labels and disables selector while switching', () => {
    render(
      <HeaderBar
        {...createProps({
          groupName: 'Admissions',
          groupTemplates: [
            { id: 'tpl-a', name: 'Alpha Packet' },
            { id: 'tpl-b', name: 'Bravo Intake' },
          ],
          groupTemplateStatuses: {
            'tpl-a': 'ready',
            'tpl-b': 'loading',
          },
          activeGroupTemplateId: 'tpl-a',
          groupTemplateSwitchInProgress: true,
        })}
      />,
    );

    expect(screen.queryByRole('listbox', { name: 'Templates in Admissions' })).toBeNull();
    expect(screen.getByText('Alpha Packet')).toBeTruthy();
  });

  it('shows a stable preparing label for the active loading template while switching', () => {
    render(
      <HeaderBar
        {...createProps({
          groupName: 'Admissions',
          groupTemplates: [
            { id: 'tpl-a', name: 'Alpha Packet' },
            { id: 'tpl-b', name: 'Bravo Intake' },
          ],
          groupTemplateStatuses: {
            'tpl-a': 'ready',
            'tpl-b': 'loading',
          },
          activeGroupTemplateId: 'tpl-b',
          groupTemplateSwitchInProgress: true,
        })}
      />,
    );

    expect(screen.queryByRole('listbox', { name: 'Templates in Admissions' })).toBeNull();
    expect(screen.getByText('Bravo Intake (Preparing...)')).toBeTruthy();
  });

  it('keeps the active loading group template label selectable while the switch is in progress', async () => {
    const user = userEvent.setup();

    render(
      <HeaderBar
        {...createProps({
          groupName: 'Admissions',
          groupTemplates: [
            { id: 'tpl-a', name: 'Alpha Packet' },
            { id: 'tpl-b', name: 'Bravo Intake' },
          ],
          groupTemplateStatuses: {
            'tpl-a': 'ready',
            'tpl-b': 'loading',
          },
          activeGroupTemplateId: 'tpl-b',
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Open template in Admissions' }));

    const selector = screen.getByRole('listbox', { name: 'Templates in Admissions' });
    const activeOption = within(selector).getByRole('option', { name: 'Bravo Intake (Preparing...)' }) as HTMLButtonElement;
    expect(activeOption.disabled).toBe(false);
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

    expect((dataButton as HTMLButtonElement).disabled).toBe(true);
    expect(renameButton.disabled).toBe(true);
    expect(mapButton.disabled).toBe(true);
    expect(renameMapButton.disabled).toBe(true);
    expect(downloadButton.disabled).toBe(false);
    expect(saveButton.disabled).toBe(true);

    await user.click(downloadButton);
    await user.click(screen.getByRole('menuitem', { name: /Download editable PDF/i }));

    expect(onDemoLockedAction).not.toHaveBeenCalled();
    expect(screen.queryByRole('menu', { name: 'Choose data source' })).toBeNull();
    expect(onRename).not.toHaveBeenCalled();
    expect(onMapSchema).not.toHaveBeenCalled();
    expect(onRenameAndMap).not.toHaveBeenCalled();
    expect(onDownload).toHaveBeenCalledTimes(1);
    expect(onDownload).toHaveBeenCalledWith('editable');
    expect(onSaveToProfile).not.toHaveBeenCalled();
  });

  it('shows docs links instead of the Fill By Web Form Link action in demo-locked mode', () => {
    render(
      <HeaderBar
        {...createProps({
          demoLocked: true,
          onOpenFillLink: vi.fn(),
          canFillLink: true,
          demoFillLinkDocsHref: '/usage-docs/fill-by-link',
          demoCreateGroupDocsHref: '/usage-docs/create-group',
        })}
      />,
    );

    expect(screen.queryByRole('button', { name: 'Fill By Web Form Link' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Fill By Link docs' }).getAttribute('href')).toBe(
      '/usage-docs/fill-by-link',
    );
    expect(screen.getByRole('link', { name: 'Create Group docs' }).getAttribute('href')).toBe(
      '/usage-docs/create-group',
    );
  });

  it('opens the download menu and wires format-specific download callbacks', async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();
    const onDownloadGroup = vi.fn();
    const onSaveToProfile = vi.fn();
    const props = createProps({
      groupName: 'Admissions',
      groupTemplates: [
        { id: 'tpl-a', name: 'Alpha Packet' },
        { id: 'tpl-b', name: 'Bravo Intake' },
      ],
      activeGroupTemplateId: 'tpl-a',
      onDownload,
      onDownloadGroup,
      onSaveToProfile,
      canDownloadGroup: true,
    });
    const { rerender } = render(<HeaderBar {...props} />);

    await user.click(screen.getByRole('button', { name: 'Download' }));
    expect(screen.getByRole('menu', { name: 'Choose download format' })).toBeTruthy();
    await user.click(screen.getByRole('menuitem', { name: /Download flat PDF/i }));
    await user.click(screen.getByRole('button', { name: 'Download' }));
    await user.click(screen.getByRole('menuitem', { name: /Download editable PDF/i }));
    await user.click(screen.getByRole('button', { name: 'Download Group' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onDownload).toHaveBeenCalledTimes(2);
    expect(onDownload).toHaveBeenNthCalledWith(1, 'flat');
    expect(onDownload).toHaveBeenNthCalledWith(2, 'editable');
    expect(onDownloadGroup).toHaveBeenCalledTimes(1);
    expect(onSaveToProfile).toHaveBeenCalledTimes(1);

    rerender(<HeaderBar {...props} downloadInProgress downloadGroupInProgress saveInProgress />);

    const downloadingButton = screen.getByRole('button', { name: 'Downloading...' }) as HTMLButtonElement;
    const groupDownloadingButton = screen.getByRole('button', { name: 'Downloading Group...' }) as HTMLButtonElement;
    const savingButton = screen.getByRole('button', { name: 'Saving...' }) as HTMLButtonElement;

    expect(downloadingButton.disabled).toBe(true);
    expect(groupDownloadingButton.disabled).toBe(true);
    expect(savingButton.disabled).toBe(true);
  });
});
