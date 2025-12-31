import React, { useState } from 'react';
import './ConnectDB.css';
import { DB } from '../../services/db';
import type { DbConnectionConfig, DbType } from '../../services/db';

interface Props {
  open: boolean;
  onClose: () => void;
  onConnected: (result: { connId: string; columns: string[]; identifierKey?: string; label?: string }) => void;
}

const ConnectDB: React.FC<Props> = ({ open, onClose, onConnected }) => {
  const LOCAL_DEFAULTS = {
    type: 'postgres' as DbType,
    host: 'localhost',
    port: '5432',
    database: 'healthdb',
    schema: 'public',
    view: 'vw_form_fields',
    user: 'cdata_ro',
    password: 'strongpassword',
    ssl: false,
  };

  const [type, setType] = useState<DbType>(LOCAL_DEFAULTS.type);
  const [host, setHost] = useState(LOCAL_DEFAULTS.host);
  const [port, setPort] = useState(LOCAL_DEFAULTS.port);
  const [database, setDatabase] = useState(LOCAL_DEFAULTS.database);
  const [schema, setSchema] = useState(LOCAL_DEFAULTS.schema);
  const [view, setView] = useState(LOCAL_DEFAULTS.view);
  const [user, setUser] = useState(LOCAL_DEFAULTS.user);
  const [password, setPassword] = useState(LOCAL_DEFAULTS.password);
  const [ssl, setSsl] = useState(LOCAL_DEFAULTS.ssl);
  const [encrypt, setEncrypt] = useState(true);
  const [trustServerCert, setTrustServerCert] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleTest = async () => {
    setError(null);
    setTesting(true);
    try {
      const cfg: DbConnectionConfig = {
        type,
        host: host.trim(),
        port: port ? Number(port) : undefined,
        database: database.trim(),
        schema: schema.trim() || undefined,
        view: view.trim(),
        user: user.trim(),
        password,
        ssl: type === 'postgres' ? ssl : undefined,
        encrypt: type === 'sqlserver' ? encrypt : undefined,
        trustServerCertificate: type === 'sqlserver' ? trustServerCert : undefined,
      };
      const out = await DB.testAndCreate(cfg);
      const schemaLabel = (schema.trim() || (type === 'postgres' ? 'public' : 'dbo')).trim();
      const viewLabel = view.trim();
      const dbLabel = database.trim();
      const label = `SQL: ${dbLabel}.${schemaLabel}.${viewLabel}`;
      onConnected({ connId: out.connId, columns: out.columns, identifierKey: out.identifierKey, label });
      onClose();
    } catch (e: any) {
      setError(e?.message || 'Connection failed');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="connectdb-modal" role="dialog" aria-modal="true">
      <div className="connectdb-backdrop" onClick={onClose} />
      <div className="connectdb-panel">
        <div className="connectdb-header">
          <h3>Connect Database</h3>
          <button className="connectdb-close" onClick={onClose}>×</button>
        </div>
        <div className="connectdb-body">
          <div className="connectdb-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 12, color: '#6b7280' }}>Tip: local Docker defaults are pre-filled.</div>
            <button
              type="button"
              className="connectdb-button-secondary"
              onClick={() => {
                setType(LOCAL_DEFAULTS.type);
                setHost(LOCAL_DEFAULTS.host);
                setPort(LOCAL_DEFAULTS.port);
                setDatabase(LOCAL_DEFAULTS.database);
                setSchema(LOCAL_DEFAULTS.schema);
                setView(LOCAL_DEFAULTS.view);
                setUser(LOCAL_DEFAULTS.user);
                setPassword(LOCAL_DEFAULTS.password);
                setSsl(LOCAL_DEFAULTS.ssl);
              }}
              style={{ padding: '0.25rem 0.5rem' }}
            >
              Use Local Defaults
            </button>
          </div>
          <div className="connectdb-row">
            <label>Type</label>
            <select value={type} onChange={e => setType(e.target.value as DbType)}>
              <option value="postgres">Postgres</option>
              <option value="sqlserver">SQL Server</option>
            </select>
          </div>
          <div className="connectdb-grid">
            <div className="connectdb-row">
              <label>Host</label>
              <input value={host} onChange={e => setHost(e.target.value)} placeholder="db.example.com" />
            </div>
            <div className="connectdb-row">
              <label>Port</label>
              <input value={port} onChange={e => setPort(e.target.value)} placeholder={type === 'postgres' ? '5432' : '1433'} />
            </div>
            <div className="connectdb-row">
              <label>Database</label>
              <input value={database} onChange={e => setDatabase(e.target.value)} placeholder="healthdb" />
            </div>
            <div className="connectdb-row">
              <label>Schema</label>
              <input value={schema} onChange={e => setSchema(e.target.value)} placeholder={type === 'postgres' ? 'public' : 'dbo'} />
            </div>
            <div className="connectdb-row">
              <label>View/Table</label>
              <input value={view} onChange={e => setView(e.target.value)} placeholder="vw_form_fields" />
            </div>
            <div className="connectdb-row">
              <label>User</label>
              <input value={user} onChange={e => setUser(e.target.value)} placeholder="read_only_user" />
            </div>
            <div className="connectdb-row">
              <label>Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
            </div>
          </div>
          {type === 'postgres' && (
            <div className="connectdb-row-inline">
              <label><input type="checkbox" checked={ssl} onChange={e => setSsl(e.target.checked)} /> Require SSL</label>
            </div>
          )}
          {type === 'sqlserver' && (
            <div className="connectdb-row-inline">
              <label><input type="checkbox" checked={encrypt} onChange={e => setEncrypt(e.target.checked)} /> Encrypt</label>
              <label><input type="checkbox" checked={trustServerCert} onChange={e => setTrustServerCert(e.target.checked)} /> Trust Server Certificate</label>
            </div>
          )}
          {error && <div className="connectdb-error">{error}</div>}
        </div>
        <div className="connectdb-footer">
          <button className="connectdb-button" onClick={handleTest} disabled={testing}>
            {testing ? 'Connecting…' : 'Test & Connect'}
          </button>
          <button className="connectdb-button-secondary" onClick={onClose} disabled={testing}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

export default ConnectDB;
