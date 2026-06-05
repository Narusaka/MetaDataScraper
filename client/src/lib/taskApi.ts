import { apiJson, wsUrl } from './api';
import type {
  PlanArtifactResponse,
  RollbackResponse,
  TaskEvent,
  TaskSnapshotsResponse,
  TaskStartPayload,
} from './types';

export async function startTask(payload: Partial<TaskStartPayload>) {
  return apiJson<unknown>(
    '/api/tasks/start',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    'Start failed',
  );
}

export async function stopTasks() {
  return apiJson<unknown>('/api/tasks/stop', { method: 'POST' }, 'Stop failed');
}

export async function rollbackTask(taskId: string) {
  return apiJson<RollbackResponse>(`/api/tasks/${taskId}/rollback`, { method: 'POST' }, 'Rollback failed');
}

export async function fetchTaskSnapshots() {
  return apiJson<TaskSnapshotsResponse>('/api/tasks', undefined, 'Task snapshots unavailable');
}

export async function fetchPlanArtifact(taskId: string, itemId: string) {
  return apiJson<PlanArtifactResponse>(
    `/api/tasks/${taskId}/plan?item_id=${encodeURIComponent(itemId)}`,
    undefined,
    'Plan artifact unavailable',
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
