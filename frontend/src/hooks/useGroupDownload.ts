import { useCallback, useState } from 'react';
import type { BannerNotice } from '../types';
import type { GroupTemplateWorkspaceSnapshot } from './useGroupTemplateCache';
import { ApiService } from '../services/api';
import { debugLog } from '../utils/debug';
import { normaliseFormName, prepareFieldsForMaterialize } from '../utils/fields';
import { buildStoredZipArchive } from '../utils/zip';

type GroupDownloadTemplate = {
  id: string;
  name: string;
};

type UseGroupDownloadDeps = {
  verifiedUser: unknown;
  activeGroupId: string | null;
  activeGroupName: string | null;
  activeGroupTemplates: GroupDownloadTemplate[];
  activeSavedFormId: string | null;
  captureActiveGroupTemplateSnapshot: () => GroupTemplateWorkspaceSnapshot | null;
  ensureGroupTemplateSnapshot: (
    formId: string,
    templateNameHint?: string | null,
  ) => Promise<GroupTemplateWorkspaceSnapshot>;
  setLoadError: (message: string | null) => void;
  setBannerNotice: (notice: BannerNotice | null) => void;
};

function sanitizeArchiveSegment(value: string | null | undefined, fallback: string): string {
  const raw = (value || fallback).trim();
  const cleaned = raw
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/^\.+/, '')
    .trim();
  return cleaned || fallback;
}

function buildPdfArchiveName(value: string | null | undefined): string {
  const base = sanitizeArchiveSegment(normaliseFormName(value), 'form');
  return base.toLowerCase().endsWith('.pdf') ? base : `${base}.pdf`;
}

function ensureUniqueArchiveName(name: string, usedNames: Set<string>): string {
  if (!usedNames.has(name)) {
    usedNames.add(name);
    return name;
  }
  const extensionIndex = name.toLowerCase().lastIndexOf('.pdf');
  const stem = extensionIndex >= 0 ? name.slice(0, extensionIndex) : name;
  let suffix = 2;
  while (true) {
    const candidate = `${stem}-${suffix}.pdf`;
    if (!usedNames.has(candidate)) {
      usedNames.add(candidate);
      return candidate;
    }
    suffix += 1;
  }
}

export function useGroupDownload(deps: UseGroupDownloadDeps) {
  const [downloadGroupInProgress, setDownloadGroupInProgress] = useState(false);

  const handleDownloadGroup = useCallback(async () => {
    if (!deps.activeGroupId || !deps.activeGroupTemplates.length) {
      deps.setBannerNotice({ tone: 'error', message: 'Open a group before downloading it.' });
      return;
    }
    if (!deps.verifiedUser) {
      deps.setLoadError('Sign in to download this group.');
      return;
    }

    setDownloadGroupInProgress(true);
    deps.setLoadError(null);

    try {
      const folderName = sanitizeArchiveSegment(deps.activeGroupName, 'group');
      const usedNames = new Set<string>();
      const archiveEntries: Array<{ name: string; data: Uint8Array }> = [];

      for (const template of deps.activeGroupTemplates) {
        const activeSnapshot = template.id === deps.activeSavedFormId
          ? deps.captureActiveGroupTemplateSnapshot()
          : null;
        const snapshot = activeSnapshot ?? await deps.ensureGroupTemplateSnapshot(template.id, template.name);
        const materializedBlob = await ApiService.materializeFormPdf(
          snapshot.sourceFile,
          prepareFieldsForMaterialize(snapshot.fields),
        );
        const bytes = new Uint8Array(await materializedBlob.arrayBuffer());
        const fileName = ensureUniqueArchiveName(
          buildPdfArchiveName(snapshot.templateName || template.name),
          usedNames,
        );
        archiveEntries.push({ name: `${folderName}/${fileName}`, data: bytes });
      }

      const archiveBlob = buildStoredZipArchive(archiveEntries);
      const archiveName = `${sanitizeArchiveSegment(deps.activeGroupName, 'group')}.zip`;
      const url = URL.createObjectURL(archiveBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = archiveName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to download this group.';
      deps.setLoadError(message);
      debugLog('Failed to download group archive', error);
    } finally {
      setDownloadGroupInProgress(false);
    }
  }, [deps]);

  return {
    downloadGroupInProgress,
    handleDownloadGroup,
  };
}
