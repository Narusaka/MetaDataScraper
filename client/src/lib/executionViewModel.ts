import type { ExecutionRecord, ExecutionTimelineEvent, MetadataRecord } from './types';

export type ExecutionFilter = 'all' | 'running' | 'issues' | 'done';

const runningStatuses = new Set(['created', 'running', 'cancel_requested']);
const issueStatuses = new Set(['failed', 'partial', 'stopped', 'cancelled', 'interrupted']);
const terminalStatuses = new Set(['completed', 'failed', 'partial', 'stopped', 'cancelled', 'interrupted']);

export const executionIsRunning = (execution: ExecutionRecord) => runningStatuses.has(execution.status);

export function deriveExecutions(executions: ExecutionRecord[], filter: ExecutionFilter, query = '') {
  const needle = query.trim().toLowerCase();
  return [...executions]
    .filter((execution) => {
      if (filter === 'running' && !executionIsRunning(execution)) return false;
      if (filter === 'issues' && !issueStatuses.has(execution.status)) return false;
      if (filter === 'done' && !terminalStatuses.has(execution.status)) return false;
      if (!needle) return true;
      const config = execution.config || {};
      const searchable = [
        execution.id,
        execution.input_dir,
        execution.status,
        execution.phase,
        config.source_plan_task_id,
        ...Object.values(execution.items || {}).flatMap((item) => {
          const record = item as MetadataRecord;
          const operation = record.operation && typeof record.operation === 'object'
            ? record.operation as MetadataRecord
            : {};
          const currentOperation = record.current_operation && typeof record.current_operation === 'object'
            ? record.current_operation as MetadataRecord
            : {};
          const latestOperation = record.latest_operation && typeof record.latest_operation === 'object'
            ? record.latest_operation as MetadataRecord
            : {};
          return [
            record.name,
            record.path,
            record.error,
            operation.stage,
            operation.action,
            operation.source,
            operation.destination,
            currentOperation.stage,
            currentOperation.action,
            currentOperation.source,
            currentOperation.destination,
            latestOperation.stage,
            latestOperation.action,
            latestOperation.source,
            latestOperation.destination,
          ];
        }),
      ];
      return searchable.some(value => String(value || '').toLowerCase().includes(needle));
    })
    .sort((left, right) => {
      const activeDelta = Number(executionIsRunning(right)) - Number(executionIsRunning(left));
      if (activeDelta) return activeDelta;
      return String(right.updated_at || right.created_at).localeCompare(String(left.updated_at || left.created_at));
    });
}

export function executionStats(executions: ExecutionRecord[]) {
  return executions.reduce((stats, execution) => {
    stats.total += 1;
    if (executionIsRunning(execution)) stats.running += 1;
    if (issueStatuses.has(execution.status)) stats.issues += 1;
    if (execution.status === 'completed') stats.completed += 1;
    stats.processed += Number(execution.progress?.processed || 0);
    return stats;
  }, { total: 0, running: 0, issues: 0, completed: 0, processed: 0 });
}

export function executionPhaseLabel(phase?: string) {
  const labels: Record<string, string> = {
    queued: 'Queued',
    scanning: 'Scanning',
    preflight: 'Preflight',
    metadata: 'Writing metadata',
    organizing: 'Organizing files',
    verifying: 'Verifying output',
    cancelling: 'Cancelling',
    cancelled: 'Cancelled',
    completed: 'Completed',
    partial: 'Completed with issues',
    failed: 'Failed',
    stopped: 'Stopped',
    interrupted: 'Interrupted by restart',
  };
  return labels[phase || ''] || 'Preparing';
}

export function executionPhasePercent(execution: ExecutionRecord) {
  if (execution.status === 'completed') return 100;
  if (terminalStatuses.has(execution.status)) {
    const total = Number(execution.progress?.total || 0);
    const processed = Number(execution.progress?.processed || 0);
    return total ? Math.round((processed / total) * 100) : 100;
  }
  const phasePercent: Record<string, number> = {
    queued: 4,
    scanning: 12,
    preflight: 28,
    metadata: 52,
    organizing: 74,
    verifying: 90,
    cancelling: 94,
  };
  const phase = phasePercent[execution.phase || ''] || 8;
  const total = Number(execution.progress?.total || 0);
  const processed = Number(execution.progress?.processed || 0);
  const itemProgress = total ? Math.round((processed / total) * 88) : 0;
  return Math.max(phase, Math.min(96, itemProgress));
}

export function executionCurrentItem(execution: ExecutionRecord) {
  const entries = Object.entries(execution.items || {});
  const active = entries.find(([, raw]) => {
    const item = raw as MetadataRecord;
    return ['processing', 'fetching', 'verifying'].includes(String(item.status || ''));
  }) || entries.at(-1);
  if (!active) return undefined;
  const [id, raw] = active;
  return { ...(raw as MetadataRecord), id } as MetadataRecord & { id: string };
}

export function executionCurrentOperation(execution: ExecutionRecord) {
  const item = executionCurrentItem(execution);
  if (!item?.current_operation || typeof item.current_operation !== 'object') return undefined;
  return item.current_operation as MetadataRecord;
}

export function executionOperationLabel(operation: MetadataRecord) {
  const action = String(operation.action || 'operation').replaceAll('_', ' ');
  const source = String(operation.source || '').trim();
  const destination = String(operation.destination || '').trim();
  if (source && destination) return `${action}: ${source} → ${destination}`;
  if (destination) return `${action}: ${destination}`;
  return action;
}

export function executionItemSummary(item: MetadataRecord) {
  const error = String(item.error || '').trim();
  if (error) {
    const operation = item.operation && typeof item.operation === 'object'
      ? item.operation as MetadataRecord
      : {};
    const destination = String(operation.destination || '').trim();
    return destination ? `${error} · ${destination}` : error;
  }
  const verification = item.verification && typeof item.verification === 'object'
    ? item.verification as MetadataRecord
    : {};
  const failed = Number(verification.failed || 0);
  const warnings = Number(verification.warnings || 0);
  if (failed > 0) return `Verification failed · ${failed} checks`;
  if (warnings > 0) return `Verification needs review · ${warnings} warning${warnings === 1 ? '' : 's'}`;
  return String(item.path || item.result || '').trim();
}

export function executionEventLabel(event: ExecutionTimelineEvent) {
  const payload = event.payload || {};
  if (event.type.startsWith('operation.')) {
    const operation = payload.operation && typeof payload.operation === 'object'
      ? payload.operation as MetadataRecord
      : {};
    const label = executionOperationLabel(operation);
    if (event.type === 'operation.started') return `Started ${label}`;
    if (event.type === 'operation.completed') return `Completed ${label}`;
    if (event.type === 'operation.failed') return `Failed ${label}${operation.error ? ` · ${operation.error}` : ''}`;
    if (event.type === 'operation.skipped') return `Skipped ${label}${operation.reason ? ` · ${operation.reason}` : ''}`;
  }
  if (event.type === 'item.execution_phase') return executionPhaseLabel(String(payload.phase || ''));
  if (event.type === 'task.progress') return `Processed ${payload.processed || 0}/${payload.total || 0}`;
  if (event.type === 'item.failed' || event.type === 'task.failed') return String(payload.error || 'Execution failed');
  if (event.type === 'item.cancelled' || event.type === 'task.cancelled') return `Cancelled${payload.stage ? ` during ${payload.stage}` : ''}`;
  if (event.type === 'task.interrupted') return 'Interrupted when the service restarted';
  if (event.type === 'item.completed') return `${payload.name || 'Item'} completed`;
  if (event.type === 'item.verification_started') return 'Verification started';
  if (event.type === 'item.verification_completed') {
    const verification = payload.verification && typeof payload.verification === 'object'
      ? payload.verification as MetadataRecord
      : payload;
    const failed = Number(verification.failed || 0);
    const warnings = Number(verification.warnings || 0);
    if (failed > 0) return `Verification failed · ${failed} checks`;
    if (warnings > 0) return `Verification needs review · ${warnings} warning${warnings === 1 ? '' : 's'}`;
    return `Verification passed · ${Number(verification.passed || 0)} checks`;
  }
  if (event.type === 'item.lock_acquired') return 'Target directory locked';
  return event.type.replaceAll('.', ' ');
}
