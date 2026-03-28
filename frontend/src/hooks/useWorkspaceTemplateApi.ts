import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { BannerNotice } from '../types';
import {
  ApiService,
  type MaterializePdfExportMode,
  type TemplateApiAuditEvent,
  type TemplateApiEndpointSummary,
  type TemplateApiOwnerLimitSummary,
  type TemplateApiSchema,
} from '../services/api';

type UseWorkspaceTemplateApiDeps = {
  verifiedUser: unknown;
  managerOpen: boolean;
  setManagerOpen: Dispatch<SetStateAction<boolean>>;
  setBannerNotice: (notice: BannerNotice | null) => void;
  activeTemplateId: string | null;
  activeTemplateName: string | null;
  activeGroupId: string | null;
};

export type ApiFillManagerDialogProps = {
  open: boolean;
  onClose: () => void;
  templateName: string | null;
  hasActiveTemplate: boolean;
  endpoint: TemplateApiEndpointSummary | null;
  schema: TemplateApiSchema | null;
  limits: TemplateApiOwnerLimitSummary | null;
  recentEvents: TemplateApiAuditEvent[];
  loading: boolean;
  publishing: boolean;
  rotating: boolean;
  revoking: boolean;
  error: string | null;
  latestSecret: string | null;
  onPublish: (exportMode: MaterializePdfExportMode) => Promise<void>;
  onRotate: () => Promise<void>;
  onRevoke: () => Promise<void>;
  onRefresh: () => Promise<void>;
};

export function useWorkspaceTemplateApi(deps: UseWorkspaceTemplateApiDeps) {
  const [endpoint, setEndpoint] = useState<TemplateApiEndpointSummary | null>(null);
  const [schema, setSchema] = useState<TemplateApiSchema | null>(null);
  const [limits, setLimits] = useState<TemplateApiOwnerLimitSummary | null>(null);
  const [recentEvents, setRecentEvents] = useState<TemplateApiAuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latestSecret, setLatestSecret] = useState<string | null>(null);
  const requestVersionRef = useRef(0);

  const canOpenTemplateApi = useMemo(
    () => Boolean(deps.verifiedUser && deps.activeTemplateId && !deps.activeGroupId),
    [deps.activeGroupId, deps.activeTemplateId, deps.verifiedUser],
  );

  const resetState = useCallback(() => {
    requestVersionRef.current += 1;
    setEndpoint(null);
    setSchema(null);
    setLimits(null);
    setRecentEvents([]);
    setLoading(false);
    setPublishing(false);
    setRotating(false);
    setRevoking(false);
    setError(null);
    setLatestSecret(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!deps.verifiedUser || !deps.activeTemplateId || deps.activeGroupId) {
      resetState();
      return;
    }
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    setLoading(true);
    setError(null);
    setLatestSecret(null);
    try {
      const endpointPayload = await ApiService.listTemplateApiEndpoints(deps.activeTemplateId);
      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      setLimits(endpointPayload.limits ?? null);
      const activeEndpoint = endpointPayload.endpoints.find((entry) => entry.status === 'active')
        ?? endpointPayload.endpoints[0]
        ?? null;
      if (!activeEndpoint) {
        setEndpoint(null);
        setSchema(null);
        setRecentEvents([]);
        return;
      }
      const payload = await ApiService.getTemplateApiEndpointSchema(activeEndpoint.id);
      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      setEndpoint(payload.endpoint);
      setSchema(payload.schema);
      setLimits(payload.limits);
      setRecentEvents(Array.isArray(payload.recentEvents) ? payload.recentEvents : []);
    } catch (nextError) {
      if (requestVersionRef.current !== requestVersion) {
        return;
      }
      const message = nextError instanceof Error ? nextError.message : 'Failed to load API Fill details.';
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
    } finally {
      if (requestVersionRef.current === requestVersion) {
        setLoading(false);
      }
    }
  }, [deps.activeGroupId, deps.activeTemplateId, deps.setBannerNotice, deps.verifiedUser, resetState]);

  useEffect(() => {
    if (!deps.managerOpen) {
      return;
    }
    if (!canOpenTemplateApi) {
      deps.setManagerOpen(false);
      resetState();
      return;
    }
    void refresh();
  }, [canOpenTemplateApi, deps.managerOpen, deps.setManagerOpen, refresh, resetState]);

  useEffect(() => {
    if (deps.verifiedUser) {
      return;
    }
    deps.setManagerOpen(false);
    resetState();
  }, [deps.setManagerOpen, deps.verifiedUser, resetState]);

  const publish = useCallback(async (exportMode: MaterializePdfExportMode) => {
    if (!deps.activeTemplateId) {
      deps.setBannerNotice({ tone: 'error', message: 'Save a template before publishing API Fill.' });
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      const payload = await ApiService.publishTemplateApiEndpoint({
        templateId: deps.activeTemplateId,
        exportMode,
      });
      setEndpoint(payload.endpoint);
      setSchema(payload.schema);
      setLimits(payload.limits);
      setRecentEvents(Array.isArray(payload.recentEvents) ? payload.recentEvents : []);
      setLatestSecret(payload.secret);
      deps.setBannerNotice({
        tone: 'success',
        message: payload.created ? 'API Fill key generated.' : 'API Fill snapshot republished.',
        autoDismissMs: 6000,
      });
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : 'Failed to publish API Fill.';
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
    } finally {
      setPublishing(false);
    }
  }, [deps.activeTemplateId, deps.setBannerNotice]);

  const rotate = useCallback(async () => {
    if (!endpoint?.id) {
      return;
    }
    setRotating(true);
    setError(null);
    try {
      const payload = await ApiService.rotateTemplateApiEndpoint(endpoint.id);
      setEndpoint(payload.endpoint);
      setLimits(payload.limits);
      setRecentEvents(Array.isArray(payload.recentEvents) ? payload.recentEvents : []);
      setLatestSecret(payload.secret);
      deps.setBannerNotice({
        tone: 'success',
        message: 'API Fill key rotated.',
        autoDismissMs: 6000,
      });
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : 'Failed to rotate API Fill key.';
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
    } finally {
      setRotating(false);
    }
  }, [deps.setBannerNotice, endpoint?.id]);

  const revoke = useCallback(async () => {
    if (!endpoint?.id) {
      return;
    }
    setRevoking(true);
    setError(null);
    try {
      const payload = await ApiService.revokeTemplateApiEndpoint(endpoint.id);
      setEndpoint(payload.endpoint);
      setLimits(payload.limits);
      setRecentEvents(Array.isArray(payload.recentEvents) ? payload.recentEvents : []);
      setLatestSecret(null);
      deps.setBannerNotice({
        tone: 'warning',
        message: 'API Fill endpoint revoked.',
        autoDismissMs: 6000,
      });
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : 'Failed to revoke API Fill endpoint.';
      setError(message);
      deps.setBannerNotice({ tone: 'error', message });
    } finally {
      setRevoking(false);
    }
  }, [deps.setBannerNotice, endpoint?.id]);

  return {
    canOpenTemplateApi,
    handleOpenTemplateApiManager: () => deps.setManagerOpen(true),
    clearTemplateApiManager: resetState,
    dialogProps: {
      open: deps.managerOpen,
      onClose: () => {
        setLatestSecret(null);
        deps.setManagerOpen(false);
      },
      templateName: deps.activeTemplateName,
      hasActiveTemplate: Boolean(deps.activeTemplateId),
      endpoint,
      schema,
      limits,
      recentEvents,
      loading,
      publishing,
      rotating,
      revoking,
      error,
      latestSecret,
      onPublish: publish,
      onRotate: rotate,
      onRevoke: revoke,
      onRefresh: refresh,
    } satisfies ApiFillManagerDialogProps,
  };
}
