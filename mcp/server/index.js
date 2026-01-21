#!/usr/bin/env node

import axios from 'axios';
import dotenv from 'dotenv';
import FormData from 'form-data';
import fs from 'fs';
import path from 'path';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import {
  REPO_ROOT,
  asAbsolutePath,
  assertPathWithinRepo,
  assertWorkingDirectoryWithinRepo,
} from './repo-paths.js';

dotenv.config({ path: path.join(REPO_ROOT, 'mcp', '.env.local') });
assertWorkingDirectoryWithinRepo('dullypdf-mcp');

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const HTTP_METHODS = new Set([
  'GET',
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
  'HEAD',
  'OPTIONS',
]);
const LOCALHOST_SUFFIX = '.localhost';

const normalizeUrl = (value) => {
  if (!value) return '';
  return value.includes('://') ? value : `http://${value}`;
};

const isLocalHost = (hostname) => {
  if (!hostname) return false;
  if (hostname === 'localhost' || hostname === '::1' || hostname === '0.0.0.0') {
    return true;
  }
  if (hostname.startsWith('127.')) {
    return true;
  }
  return hostname.endsWith(LOCALHOST_SUFFIX);
};

const isLocalUrl = (value) => {
  try {
    const url = new URL(normalizeUrl(value));
    return isLocalHost(url.hostname);
  } catch (error) {
    return false;
  }
};

class DullyPdfMcpServer {
  constructor() {
    this.server = new Server(
      {
        name: 'dullypdf-mcp',
        version: '0.1.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.apiBaseUrl = process.env.DULLY_MCP_API_BASE_URL || 'http://localhost:8000';
    const explicitEnv = process.env.DULLY_MCP_ENV;
    const inferredEnv = explicitEnv || (isLocalUrl(this.apiBaseUrl) ? 'dev' : 'prod');
    this.envName = inferredEnv.toLowerCase();
    this.frontendUrl = process.env.DULLY_MCP_FRONTEND_URL || 'http://localhost:5173';
    this.openApiUrl =
      process.env.DULLY_MCP_OPENAPI_URL || `${this.apiBaseUrl.replace(/\/$/, '')}/openapi.json`;
    this.allowlistMode =
      process.env.DULLY_MCP_ALLOWLIST_MODE || (this.envName === 'prod' ? 'file' : 'auto');
    this.allowlistFile =
      process.env.DULLY_MCP_ALLOWLIST_FILE || path.join(REPO_ROOT, 'mcp', 'allowlist.prod.json');
    this.allowWrite = process.env.DULLY_MCP_ALLOW_WRITE === '1';
    this.firebaseApiKey = process.env.DULLY_MCP_FIREBASE_API_KEY || '';
    this.defaultEmail = process.env.DULLY_MCP_FIREBASE_EMAIL || '';
    this.defaultPassword = process.env.DULLY_MCP_FIREBASE_PASSWORD || '';

    this.authState = {
      email: null,
      idToken: null,
      refreshToken: null,
      expiresAt: null,
    };
    this.allowlist = [];

    this.setupToolHandlers();
  }

  async start() {
    await this.loadAllowlist();
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
  }

  setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      return {
        tools: [
          {
            name: 'auth.login',
            description:
              'Sign in via Firebase email/password and cache the ID token in memory. Defaults to mcp/.env.local values.',
            inputSchema: {
              type: 'object',
              properties: {
                email: { type: 'string' },
                password: { type: 'string' },
              },
              required: [],
            },
          },
          {
            name: 'auth.refresh',
            description: 'Refresh the Firebase ID token using the cached refresh token.',
            inputSchema: { type: 'object', properties: {} },
          },
          {
            name: 'auth.status',
            description: 'Check whether a Firebase session is cached in memory.',
            inputSchema: { type: 'object', properties: {} },
          },
          {
            name: 'auth.logout',
            description: 'Clear cached Firebase tokens from memory.',
            inputSchema: { type: 'object', properties: {} },
          },
          {
            name: 'config.status',
            description: 'Show the active MCP configuration (non-secret values only).',
            inputSchema: { type: 'object', properties: {} },
          },
          {
            name: 'allowlist.refresh',
            description: 'Reload the allowlist (from OpenAPI or file).',
            inputSchema: { type: 'object', properties: {} },
          },
          {
            name: 'allowlist.list',
            description: 'List the currently loaded allowlist entries.',
            inputSchema: { type: 'object', properties: {} },
          },
          {
            name: 'api.request',
            description: 'Call a backend endpoint with JSON payloads and cached auth.',
            inputSchema: {
              type: 'object',
              properties: {
                method: {
                  type: 'string',
                  description: 'HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS).',
                },
                path: {
                  type: 'string',
                  description: 'Path beginning with /, e.g. /api/health.',
                },
                query: {
                  type: 'object',
                  additionalProperties: { type: 'string' },
                },
                headers: {
                  type: 'object',
                  additionalProperties: { type: 'string' },
                },
                body: {
                  type: ['object', 'string', 'number', 'array', 'boolean', 'null'],
                },
                timeoutMs: { type: 'number' },
                useAuth: {
                  type: 'boolean',
                  description: 'Attach cached Firebase token when true (default).',
                },
              },
              required: ['method', 'path'],
            },
          },
          {
            name: 'api.uploadFile',
            description: 'Upload a file as multipart/form-data with cached auth.',
            inputSchema: {
              type: 'object',
              properties: {
                path: {
                  type: 'string',
                  description: 'File path (absolute or repo-relative).',
                },
                endpoint: {
                  type: 'string',
                  description: 'Endpoint path beginning with /, e.g. /detect-fields.',
                },
                fieldName: {
                  type: 'string',
                  description: 'Multipart field name (default: file).',
                },
                method: {
                  type: 'string',
                  description: 'HTTP method (default: POST).',
                },
                formFields: {
                  type: 'object',
                  additionalProperties: { type: 'string' },
                },
                query: {
                  type: 'object',
                  additionalProperties: { type: 'string' },
                },
                headers: {
                  type: 'object',
                  additionalProperties: { type: 'string' },
                },
                timeoutMs: { type: 'number' },
                useAuth: {
                  type: 'boolean',
                  description: 'Attach cached Firebase token when true (default).',
                },
              },
              required: ['path', 'endpoint'],
            },
          },
        ],
      };
    });

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;
      try {
        switch (name) {
          case 'auth.login':
            return this.toTextResponse(await this.login(args));
          case 'auth.refresh':
            return this.toTextResponse(await this.refresh());
          case 'auth.status':
            return this.toTextResponse(this.status());
          case 'auth.logout':
            return this.toTextResponse(this.logout());
          case 'config.status':
            return this.toTextResponse(this.configStatus());
          case 'allowlist.refresh':
            await this.loadAllowlist();
            return this.toTextResponse({ loaded: this.allowlist.length });
          case 'allowlist.list':
            return this.toTextResponse({
              entries: this.allowlist.map((entry) => ({
                method: entry.method,
                path: entry.rawPath,
              })),
            });
          case 'api.request':
            return this.toTextResponse(await this.apiRequest(args));
          case 'api.uploadFile':
            return this.toTextResponse(await this.uploadFile(args));
          default:
            throw new Error(`Unknown tool: ${name}`);
        }
      } catch (error) {
        return this.toTextResponse({ error: error.message });
      }
    });
  }

  async loadAllowlist() {
    if (this.allowlistMode === 'auto') {
      const response = await axios.get(this.openApiUrl, { timeout: 15000 });
      this.allowlist = buildAllowlistFromOpenApi(response.data);
      return;
    }
    if (this.allowlistMode === 'file') {
      const filePath = asAbsolutePath(this.allowlistFile) || this.allowlistFile;
      const raw = fs.readFileSync(filePath, 'utf8');
      this.allowlist = buildAllowlistFromFile(raw);
      return;
    }
    throw new Error(`Unsupported allowlist mode: ${this.allowlistMode}`);
  }

  ensureAllowed(method, requestPath) {
    const normalizedMethod = method.toUpperCase();
    if (!HTTP_METHODS.has(normalizedMethod)) {
      throw new Error(`Unsupported HTTP method: ${method}`);
    }
    if (this.envName === 'prod' && !SAFE_METHODS.has(normalizedMethod) && !this.allowWrite) {
      throw new Error('Write operations are disabled in prod. Set DULLY_MCP_ALLOW_WRITE=1 to enable.');
    }
    // Linear scan over allowlist entries keeps matching predictable; O(N) in endpoint count.
    const allowed = this.allowlist.some(
      (entry) => entry.method === normalizedMethod && entry.pattern.test(requestPath)
    );
    if (!allowed) {
      throw new Error(`Endpoint not in allowlist: ${normalizedMethod} ${requestPath}`);
    }
  }

  getAuthHeaders(useAuth = true) {
    if (!useAuth || !this.authState.idToken) return {};
    return { Authorization: `Bearer ${this.authState.idToken}` };
  }

  async login({ email, password } = {}) {
    if (!this.firebaseApiKey) {
      throw new Error('Missing DULLY_MCP_FIREBASE_API_KEY in mcp/.env.local');
    }
    const finalEmail = email || this.defaultEmail;
    const finalPassword = password || this.defaultPassword;
    if (!finalEmail || !finalPassword) {
      throw new Error('Missing Firebase email/password. Set DULLY_MCP_FIREBASE_EMAIL and DULLY_MCP_FIREBASE_PASSWORD.');
    }

    const url = `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${this.firebaseApiKey}`;
    const response = await axios.post(url, {
      email: finalEmail,
      password: finalPassword,
      returnSecureToken: true,
    });

    const { idToken, refreshToken, expiresIn } = response.data || {};
    if (!idToken) {
      throw new Error('Firebase login did not return an idToken.');
    }
    const expiresAt = Date.now() + Number(expiresIn || 0) * 1000;
    this.authState = {
      email: finalEmail,
      idToken,
      refreshToken,
      expiresAt,
    };

    return { email: finalEmail, expiresAt };
  }

  async refresh() {
    if (!this.firebaseApiKey) {
      throw new Error('Missing DULLY_MCP_FIREBASE_API_KEY in mcp/.env.local');
    }
    if (!this.authState.refreshToken) {
      throw new Error('No refresh token available. Call auth.login first.');
    }
    const url = `https://securetoken.googleapis.com/v1/token?key=${this.firebaseApiKey}`;
    const params = new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: this.authState.refreshToken,
    });
    const response = await axios.post(url, params.toString(), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    const { id_token: idToken, refresh_token: refreshToken, expires_in: expiresIn } = response.data || {};
    if (!idToken) {
      throw new Error('Refresh did not return an id_token.');
    }
    const expiresAt = Date.now() + Number(expiresIn || 0) * 1000;
    this.authState = {
      email: this.authState.email,
      idToken,
      refreshToken: refreshToken || this.authState.refreshToken,
      expiresAt,
    };
    return { email: this.authState.email, expiresAt };
  }

  status() {
    if (!this.authState.idToken) {
      return { authenticated: false };
    }
    return {
      authenticated: true,
      email: this.authState.email,
      expiresAt: this.authState.expiresAt,
    };
  }

  logout() {
    this.authState = {
      email: null,
      idToken: null,
      refreshToken: null,
      expiresAt: null,
    };
    return { loggedOut: true };
  }

  configStatus() {
    return {
      env: this.envName,
      apiBaseUrl: this.apiBaseUrl,
      openApiUrl: this.openApiUrl,
      frontendUrl: this.frontendUrl,
      allowlistMode: this.allowlistMode,
      allowlistFile: this.allowlistFile,
      allowWrite: this.allowWrite,
      allowlistCount: this.allowlist.length,
    };
  }

  async apiRequest({ method, path: requestPath, query, headers, body, timeoutMs, useAuth } = {}) {
    if (!method || !requestPath) {
      throw new Error('api.request requires method and path.');
    }
    this.ensureAllowed(method, requestPath);

    const url = this.buildUrl(requestPath, query);
    const mergedHeaders = {
      'Content-Type': 'application/json',
      ...this.getAuthHeaders(useAuth !== false),
      ...(headers || {}),
    };

    const response = await axios({
      method,
      url,
      headers: mergedHeaders,
      data: body,
      timeout: timeoutMs || 60000,
      validateStatus: () => true,
    });

    return this.formatResponse(response);
  }

  async uploadFile({
    path: filePath,
    endpoint,
    fieldName,
    method,
    formFields,
    query,
    headers,
    timeoutMs,
    useAuth,
  } = {}) {
    if (!filePath || !endpoint) {
      throw new Error('api.uploadFile requires path and endpoint.');
    }
    const resolved = asAbsolutePath(filePath);
    if (!resolved || !fs.existsSync(resolved)) {
      throw new Error(`File not found: ${filePath}`);
    }
    assertPathWithinRepo(resolved, 'upload path');
    const httpMethod = method || 'POST';
    this.ensureAllowed(httpMethod, endpoint);

    const form = new FormData();
    form.append(fieldName || 'file', fs.createReadStream(resolved), path.basename(resolved));
    if (formFields) {
      Object.entries(formFields).forEach(([key, value]) => {
        if (value === undefined || value === null) return;
        form.append(key, String(value));
      });
    }

    const url = this.buildUrl(endpoint, query);
    const mergedHeaders = {
      ...form.getHeaders(),
      ...this.getAuthHeaders(useAuth !== false),
      ...(headers || {}),
    };

    const response = await axios({
      method: httpMethod,
      url,
      headers: mergedHeaders,
      data: form,
      timeout: timeoutMs || 120000,
      maxBodyLength: Infinity,
      validateStatus: () => true,
    });

    return this.formatResponse(response);
  }

  buildUrl(requestPath, query) {
    const base = this.apiBaseUrl.replace(/\/$/, '');
    const normalizedPath = requestPath.startsWith('/') ? requestPath : `/${requestPath}`;
    const url = new URL(`${base}${normalizedPath}`);
    if (query) {
      Object.entries(query).forEach(([key, value]) => {
        if (value === undefined || value === null) return;
        url.searchParams.set(key, String(value));
      });
    }
    return url.toString();
  }

  formatResponse(response) {
    const contentType = String(response.headers?.['content-type'] || '');
    const data = contentType.includes('application/json') ? response.data : String(response.data);
    return {
      status: response.status,
      statusText: response.statusText,
      data,
    };
  }

  toTextResponse(payload) {
    if (typeof payload === 'string') {
      return { content: [{ type: 'text', text: payload }] };
    }
    return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] };
  }
}

function buildAllowlistFromOpenApi(spec) {
  const entries = [];
  const paths = spec?.paths || {};
  Object.entries(paths).forEach(([rawPath, methods]) => {
    Object.entries(methods || {}).forEach(([method]) => {
      const upper = method.toUpperCase();
      if (!HTTP_METHODS.has(upper)) return;
      entries.push({
        method: upper,
        rawPath,
        pattern: pathPattern(rawPath),
      });
    });
  });
  return entries;
}

function buildAllowlistFromFile(raw) {
  const parsed = JSON.parse(raw);
  const entries = Array.isArray(parsed.entries) ? parsed.entries : [];
  return entries.map((entry) => ({
    method: String(entry.method || '').toUpperCase(),
    rawPath: String(entry.path || ''),
    pattern: pathPattern(String(entry.path || '')),
  }));
}

function pathPattern(rawPath) {
  const escaped = rawPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const withWildcards = escaped.replace(/\\{[^/]+?\\}/g, '[^/]+');
  return new RegExp(`^${withWildcards}$`);
}

const server = new DullyPdfMcpServer();
server.start().catch((error) => {
  // eslint-disable-next-line no-console
  console.error(`[dullypdf-mcp] Failed to start: ${error.message}`);
  process.exit(1);
});
