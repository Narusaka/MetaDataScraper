import { apiJson, wsUrl } from './api';
import type {
  ClearTaskHistoryResponse,
  DashboardSummary,
  ExecutionsResponse,
  LibraryScanResponse,
  ManifestResponse,
  MatchReviewResponse,
  MatchReviewResolutionResponse,
  PlanReviewResponse,
  PlanArtifactResponse,
  PlanExecutionResponse,
  RollbackResponse,
  RecoveryPreviewResponse,
  RecoveryResponse,
  TaskEvent,
  TaskHistoryResponse,
  TaskHistoryCleanupPreview,
  TaskSnapshotsResponse,
  TaskStartPayload,
} from './types';

export async function scanLibrary(payload: {
  path: string;
  mode: 'auto' | 'single' | 'batch';
  use_local_nfo: boolean;
}) {
  return apiJson<LibraryScanResponse>(
    '/api/library/scan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    'Library scan failed',
  );
}

export async function planTask(payload: Partial<TaskStartPayload>) {
  return apiJson<{ status: 'planning'; task_id: string; strategy: string; message: string }>(
    '/api/tasks/plan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    'Plan generation failed',
  );
}

export async function stopTasks() {
  return apiJson<unknown>('/api/tasks/stop', { method: 'POST' }, 'Stop failed');
}

export async function cancelTask(taskId: string) {
  return apiJson<unknown>(`/api/tasks/${taskId}/cancel`, { method: 'POST' }, 'Cancel failed');
}

export async function rollbackTask(taskId: string) {
  return apiJson<RollbackResponse>(`/api/tasks/${taskId}/rollback`, { method: 'POST' }, 'Rollback failed');
}

export async function previewRollbackTask(taskId: string) {
  return apiJson<RollbackResponse>(`/api/tasks/${taskId}/rollback/preview`, undefined, 'Rollback preview failed');
}

export async function previewRecoveryTask(taskId: string) {
  return apiJson<RecoveryPreviewResponse>(`/api/tasks/${taskId}/recovery/preview`, undefined, 'Recovery preview failed');
}

export async function recoverTask(taskId: string) {
  return apiJson<RecoveryResponse>(`/api/tasks/${taskId}/recover`, { method: 'POST' }, 'Recovery failed');
}

export async function fetchTaskSnapshots() {
  return apiJson<TaskSnapshotsResponse>('/api/tasks?compact=true', undefined, 'Task snapshots unavailable');
}

export async function fetchTaskHistory() {
  return apiJson<TaskHistoryResponse>('/api/tasks/history', undefined, 'Task history unavailable');
}

export async function fetchMatchReviews() {
  return apiJson<MatchReviewResponse>('/api/matches/review', undefined, 'Match review queue unavailable');
}

export async function fetchPlanReviews() {
  return apiJson<PlanReviewResponse>('/api/plans/review', undefined, 'Plan review queue unavailable');
}

export async function fetchExecutions(limit = 50) {
  return apiJson<ExecutionsResponse>(
    `/api/executions?limit=${encodeURIComponent(limit)}`,
    undefined,
    'Execution queue unavailable',
  );
}

export async function fetchDashboardSummary() {
  return apiJson<DashboardSummary>(
    '/api/dashboard/summary',
    undefined,
    'Dashboard summary unavailable',
  );
}

export async function resolveMatchReview(
  taskId: string,
  itemId: string,
  resolution: {
    action: 'audit' | 'execute' | 'ignored' | 'rejected';
    tmdb_id?: number;
    media_type?: 'movie' | 'tv';
  },
) {
  return apiJson<MatchReviewResolutionResponse>(
    `/api/matches/review/${encodeURIComponent(taskId)}/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, ...resolution }),
    },
    'Unable to resolve match review',
  );
}

export async function clearCompletedTaskHistory() {
  return apiJson<ClearTaskHistoryResponse>(
    '/api/tasks/history/completed',
    { method: 'DELETE' },
    'Clear history failed',
  );
}

export async function previewCompletedTaskHistoryClear() {
  return apiJson<TaskHistoryCleanupPreview>(
    '/api/tasks/history/cleanup-preview',
    undefined,
    'History cleanup preview failed',
  );
}

export async function fetchPlanArtifact(taskId: string, itemId: string) {
  return apiJson<PlanArtifactResponse>(
    `/api/tasks/${taskId}/plan?item_id=${encodeURIComponent(itemId)}`,
    undefined,
    'Plan artifact unavailable',
  );
}

export async function executeConfirmedPlan(taskId: string, itemId: string, planDigest: string) {
  return apiJson<PlanExecutionResponse>(
    `/api/tasks/${taskId}/execute`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, plan_digest: planDigest }),
    },
    'Confirmed execution failed',
  );
}

export async function fetchTaskManifest(taskId: string) {
  return apiJson<ManifestResponse>(
    `/api/tasks/${taskId}/manifest`,
    undefined,
    'Manifest unavailable',
  );
}

export function openTaskEventSocket(onEvent: (event: TaskEvent) => void, onInvalidEvent?: (error: unknown) => void) {
  const ws = new WebSocket(wsUrl('/ws/events'));
  ws.onmessage = (event) => {
    try {
      onEvent(JSON.parse(event.data) as TaskEvent);
    } catch (error) {
      onInvalidEvent?.(error);
    }
  };
  return ws;
}
