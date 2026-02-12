import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const dbMocks = vi.hoisted(() => ({
  testAndCreate: vi.fn(),
}));

vi.mock('../../fixtures/legacy/db', () => ({
  DB: {
    testAndCreate: dbMocks.testAndCreate,
  },
}));

import ConnectDB from '../../fixtures/legacy/ConnectDB';

const getHostInput = () => screen.getByPlaceholderText('db.example.com') as HTMLInputElement;
const getPortInput = () => screen.getByPlaceholderText(/5432|1433/) as HTMLInputElement;
const getDatabaseInput = () => screen.getByPlaceholderText('healthdb') as HTMLInputElement;
const getSchemaInput = () => screen.getByPlaceholderText(/public|dbo/) as HTMLInputElement;
const getViewInput = () => screen.getByPlaceholderText('vw_form_fields') as HTMLInputElement;
const getUserInput = () => screen.getByPlaceholderText('read_only_user') as HTMLInputElement;
const getPasswordInput = () => screen.getByPlaceholderText('••••••••') as HTMLInputElement;

const fillBaseForm = () => {
  fireEvent.change(getHostInput(), { target: { value: ' db.example.com ' } });
  fireEvent.change(getPortInput(), { target: { value: '5432' } });
  fireEvent.change(getDatabaseInput(), { target: { value: ' healthdb ' } });
  fireEvent.change(getSchemaInput(), { target: { value: ' public ' } });
  fireEvent.change(getViewInput(), { target: { value: ' vw_form_fields ' } });
  fireEvent.change(getUserInput(), { target: { value: ' cdata_ro ' } });
  fireEvent.change(getPasswordInput(), { target: { value: 'strongpassword' } });
};

describe('ConnectDB', () => {
  beforeEach(() => {
    dbMocks.testAndCreate.mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it('renders nothing when closed and renders modal contents when open', () => {
    vi.stubEnv('DEV', '1');
    const onClose = vi.fn();

    const { rerender } = render(<ConnectDB open={false} onClose={onClose} onConnected={vi.fn()} />);
    expect(screen.queryByRole('dialog')).toBeNull();

    rerender(<ConnectDB open onClose={onClose} onConnected={vi.fn()} />);
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByText('Connect Database')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('prefills local defaults in dev mode and keeps fields blank in non-dev mode', () => {
    const noop = () => {};

    vi.stubEnv('DEV', '1');
    const { unmount } = render(<ConnectDB open onClose={noop} onConnected={noop} />);
    expect(screen.getByText(/local Docker defaults are pre-filled/i)).toBeTruthy();
    expect(getHostInput().value).toBe('localhost');
    expect(getPortInput().value).toBe('5432');
    expect(getDatabaseInput().value).toBe('healthdb');
    expect(getSchemaInput().value).toBe('public');
    expect(getViewInput().value).toBe('vw_form_fields');
    expect(getUserInput().value).toBe('cdata_ro');
    unmount();

    vi.stubEnv('DEV', '');
    render(<ConnectDB open onClose={noop} onConnected={noop} />);
    expect(screen.queryByText(/local Docker defaults are pre-filled/i)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Use Local Defaults' })).toBeNull();
    expect(getHostInput().value).toBe('');
    expect(getPortInput().value).toBe('');
    expect(getDatabaseInput().value).toBe('');
    expect(getSchemaInput().value).toBe('');
    expect(getViewInput().value).toBe('');
    expect(getUserInput().value).toBe('');
  });

  it('builds postgres payload, returns connected metadata, and closes modal on success', async () => {
    vi.stubEnv('DEV', '');
    dbMocks.testAndCreate.mockResolvedValue({
      connId: 'conn-postgres',
      columns: ['mrn', 'first_name'],
      identifierKey: 'mrn',
    });

    const onConnected = vi.fn();
    const onClose = vi.fn();

    render(<ConnectDB open onClose={onClose} onConnected={onConnected} />);
    fillBaseForm();
    fireEvent.click(screen.getByLabelText(/Require SSL/i));
    fireEvent.click(screen.getByRole('button', { name: 'Test & Connect' }));

    await waitFor(() => {
      expect(dbMocks.testAndCreate).toHaveBeenCalledTimes(1);
    });

    expect(dbMocks.testAndCreate).toHaveBeenCalledWith({
      type: 'postgres',
      host: 'db.example.com',
      port: 5432,
      database: 'healthdb',
      schema: 'public',
      view: 'vw_form_fields',
      user: 'cdata_ro',
      password: 'strongpassword',
      ssl: true,
      encrypt: undefined,
      trustServerCertificate: undefined,
    });

    expect(onConnected).toHaveBeenCalledWith({
      connId: 'conn-postgres',
      columns: ['mrn', 'first_name'],
      identifierKey: 'mrn',
      label: 'SQL: healthdb.public.vw_form_fields',
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('builds sqlserver payload with sqlserver-only options', async () => {
    vi.stubEnv('DEV', '');
    dbMocks.testAndCreate.mockResolvedValue({
      connId: 'conn-sqlserver',
      columns: ['member_id'],
      identifierKey: 'member_id',
    });

    const onConnected = vi.fn();

    render(<ConnectDB open onClose={vi.fn()} onConnected={onConnected} />);

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'sqlserver' } });
    fireEvent.change(getHostInput(), { target: { value: ' sql.local ' } });
    fireEvent.change(getPortInput(), { target: { value: '1433' } });
    fireEvent.change(getDatabaseInput(), { target: { value: ' members ' } });
    fireEvent.change(getSchemaInput(), { target: { value: '   ' } });
    fireEvent.change(getViewInput(), { target: { value: ' members_view ' } });
    fireEvent.change(getUserInput(), { target: { value: ' readonly ' } });
    fireEvent.change(getPasswordInput(), { target: { value: 'pw' } });

    fireEvent.click(screen.getByLabelText(/Encrypt/i));
    fireEvent.click(screen.getByLabelText(/Trust Server Certificate/i));
    fireEvent.click(screen.getByRole('button', { name: 'Test & Connect' }));

    await waitFor(() => {
      expect(dbMocks.testAndCreate).toHaveBeenCalledTimes(1);
    });

    expect(dbMocks.testAndCreate).toHaveBeenCalledWith({
      type: 'sqlserver',
      host: 'sql.local',
      port: 1433,
      database: 'members',
      schema: undefined,
      view: 'members_view',
      user: 'readonly',
      password: 'pw',
      ssl: undefined,
      encrypt: false,
      trustServerCertificate: true,
    });

    expect(onConnected).toHaveBeenCalledWith({
      connId: 'conn-sqlserver',
      columns: ['member_id'],
      identifierKey: 'member_id',
      label: 'SQL: members.dbo.members_view',
    });
  });

  it('surfaces backend errors when connection test fails', async () => {
    vi.stubEnv('DEV', '');
    dbMocks.testAndCreate.mockRejectedValue(new Error('Invalid credentials'));

    const onConnected = vi.fn();
    const onClose = vi.fn();

    render(<ConnectDB open onClose={onClose} onConnected={onConnected} />);
    fillBaseForm();
    fireEvent.click(screen.getByRole('button', { name: 'Test & Connect' }));

    expect(await screen.findByText('Invalid credentials')).toBeTruthy();
    expect(onConnected).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
