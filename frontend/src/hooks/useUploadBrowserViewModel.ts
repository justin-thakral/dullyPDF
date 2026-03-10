import { useMemo, type ReactNode } from 'react';
import type { DataSourceKind } from '../types';
import type { UploadViewProps } from '../components/features/UploadView';
import type { SavedFormSummary, TemplateGroupSummary } from '../services/api';

type UploadPipelineState = Pick<
  UploadViewProps,
  | 'showPipelineModal'
  | 'pendingDetectFile'
  | 'pendingDetectPageCount'
  | 'pendingDetectPageCountLoading'
  | 'pendingDetectCreditEstimate'
  | 'pendingDetectWithinPageLimit'
  | 'pendingDetectCreditsRemaining'
  | 'uploadWantsRename'
  | 'uploadWantsMap'
  | 'pipelineError'
  | 'onSetUploadWantsRename'
  | 'onSetUploadWantsMap'
  | 'onSetPipelineError'
  | 'onPipelineCancel'
  | 'onPipelineConfirm'
> & {
  onDetectUpload: (file: File) => void;
};

type UploadSavedFormsState = {
  savedForms: SavedFormSummary[];
  savedFormsLoading: boolean;
  deletingFormId: string | null;
};

type UploadGroupsState = {
  groups: TemplateGroupSummary[];
  groupsLoading: boolean;
  groupsCreating: boolean;
  updatingGroupId: string | null;
  selectedGroupFilterId: string;
  selectedGroupFilterLabel: string | null;
  deletingGroupId: string | null;
  setSelectedGroupFilterId: (groupId: string) => void;
};

type UploadHandlers = Pick<
  UploadViewProps,
  | 'onFillableUpload'
  | 'onOpenGroupUpload'
  | 'onSelectSavedForm'
  | 'onDeleteSavedForm'
  | 'onOpenGroup'
  | 'onCreateGroup'
  | 'onUpdateGroup'
  | 'onDeleteGroup'
>;

type UseUploadBrowserViewModelDeps = {
  loadError: string | null;
  onSetLoadError: (error: string | null) => void;
  verifiedUser: boolean;
  schemaUploadInProgress: boolean;
  dataSourceLabel: string | null;
  onChooseDataSource: (kind: Exclude<DataSourceKind, 'none'>) => void;
  pipeline: UploadPipelineState;
  savedForms: UploadSavedFormsState;
  groups: UploadGroupsState;
  handlers: UploadHandlers;
  groupUploadDialog?: ReactNode;
};

export function useUploadBrowserViewModel(deps: UseUploadBrowserViewModelDeps): UploadViewProps {
  const {
    loadError,
    onSetLoadError,
    verifiedUser,
    schemaUploadInProgress,
    dataSourceLabel,
    onChooseDataSource,
    pipeline,
    savedForms,
    groups,
    handlers,
    groupUploadDialog,
  } = deps;

  return useMemo(() => ({
    loadError,
    showPipelineModal: pipeline.showPipelineModal,
    pendingDetectFile: pipeline.pendingDetectFile,
    pendingDetectPageCount: pipeline.pendingDetectPageCount,
    pendingDetectPageCountLoading: pipeline.pendingDetectPageCountLoading,
    pendingDetectCreditEstimate: pipeline.pendingDetectCreditEstimate,
    pendingDetectWithinPageLimit: pipeline.pendingDetectWithinPageLimit,
    pendingDetectCreditsRemaining: pipeline.pendingDetectCreditsRemaining,
    uploadWantsRename: pipeline.uploadWantsRename,
    uploadWantsMap: pipeline.uploadWantsMap,
    schemaUploadInProgress,
    dataSourceLabel,
    pipelineError: pipeline.pipelineError,
    verifiedUser,
    savedForms: savedForms.savedForms,
    groups: groups.groups,
    groupsLoading: groups.groupsLoading,
    groupsCreating: groups.groupsCreating,
    updatingGroupId: groups.updatingGroupId,
    selectedGroupFilterId: groups.selectedGroupFilterId,
    selectedGroupFilterLabel: groups.selectedGroupFilterLabel,
    savedFormsLoading: savedForms.savedFormsLoading,
    deletingFormId: savedForms.deletingFormId,
    deletingGroupId: groups.deletingGroupId,
    onSetUploadWantsRename: pipeline.onSetUploadWantsRename,
    onSetUploadWantsMap: pipeline.onSetUploadWantsMap,
    onSetPipelineError: pipeline.onSetPipelineError,
    onSetLoadError,
    onChooseDataSource,
    onPipelineCancel: pipeline.onPipelineCancel,
    onPipelineConfirm: pipeline.onPipelineConfirm,
    onDetectUpload: pipeline.onDetectUpload,
    onFillableUpload: handlers.onFillableUpload,
    onOpenGroupUpload: handlers.onOpenGroupUpload,
    onSelectSavedForm: handlers.onSelectSavedForm,
    onDeleteSavedForm: handlers.onDeleteSavedForm,
    onSelectGroupFilter: groups.setSelectedGroupFilterId,
    onOpenGroup: handlers.onOpenGroup,
    onCreateGroup: handlers.onCreateGroup,
    onUpdateGroup: handlers.onUpdateGroup,
    onDeleteGroup: handlers.onDeleteGroup,
    groupUploadDialog,
  }), [
    dataSourceLabel,
    groupUploadDialog,
    groups.deletingGroupId,
    groups.groups,
    groups.groupsCreating,
    groups.groupsLoading,
    groups.selectedGroupFilterId,
    groups.selectedGroupFilterLabel,
    groups.setSelectedGroupFilterId,
    groups.updatingGroupId,
    handlers.onCreateGroup,
    handlers.onDeleteGroup,
    handlers.onDeleteSavedForm,
    handlers.onFillableUpload,
    handlers.onOpenGroup,
    handlers.onOpenGroupUpload,
    handlers.onSelectSavedForm,
    handlers.onUpdateGroup,
    loadError,
    onChooseDataSource,
    onSetLoadError,
    pipeline.onDetectUpload,
    pipeline.onPipelineCancel,
    pipeline.onPipelineConfirm,
    pipeline.onSetPipelineError,
    pipeline.onSetUploadWantsMap,
    pipeline.onSetUploadWantsRename,
    pipeline.pendingDetectCreditEstimate,
    pipeline.pendingDetectCreditsRemaining,
    pipeline.pendingDetectFile,
    pipeline.pendingDetectPageCount,
    pipeline.pendingDetectPageCountLoading,
    pipeline.pendingDetectWithinPageLimit,
    pipeline.pipelineError,
    pipeline.showPipelineModal,
    pipeline.uploadWantsMap,
    pipeline.uploadWantsRename,
    savedForms.deletingFormId,
    savedForms.savedForms,
    savedForms.savedFormsLoading,
    schemaUploadInProgress,
    verifiedUser,
  ]);
}
