import type { TaskHistoryCleanupPreview, TaskSnapshot } from './types';

export type HistoryFilter = 'all' | 'success' | 'issues' | 'rollback';
export type HistoryTone = 'success' | 'warning' | 'danger' | 'neutral';

const numberValue = (value: unknown) => typeof value === 'number' ? value : 0;

export function historyTone(task: TaskSnapshot): HistoryTone {
  if (task.rolled_back || task.rollback?.status === 'completed') return 'neutral';
  if (task.rollback?.status === 'failed') return 'danger';
  if (task.rollback?.status === 'partial' || task.rollback?.status === 'running') return 'warning';
  if (task.status === 'failed') return 'danger';
  if (task.status === 'interrupted') return 'danger';
  if (task.status === 'partial' || task.status === 'stopped') return 'warning';
  if (task.status === 'completed') return 'success';
  return 'neutral';
}

export function historyStatusLabel(task: TaskSnapshot): string {
  if (task.rolled_back || task.rollback?.status === 'completed') return 'Rolled back';
  if (task.rollback?.status === 'failed') return 'Rollback failed';
  if (task.rollback?.status === 'partial') return 'Rollback needs review';
  if (task.rollback?.status === 'running') return 'Rolling back';
  if (task.status === 'partial') return 'Partial';
  if (task.status === 'failed') return 'Failed';
  if (task.status === 'stopped') return 'Stopped';
  if (task.status === 'interrupted') return 'Interrupted';
  if (task.status === 'cancel_requested') return 'Cancelling';
  if (task.status === 'cancelled') return 'Cancelled';
  if (task.status === 'completed') return 'Completed';
  return task.status || 'Unknown';
}

export function historyStrategyLabel(task: TaskSnapshot): string {
  const strategy = task.config?.strategy;
  if (strategy === 'copy' || task.config?.copy_mode === true) return 'Copy';
  if (strategy === 'organize' || strategy === 'inplace' || task.config?.inplace === true) return 'Organize';
  if (strategy === 'audit' || task.config?.dry_run === true) return 'Metadata';
  return typeof strategy === 'string' && strategy ? strategy : 'Metadata';
}

export function historyScopeLabel(task: TaskSnapshot): string {
  const scope = task.config?.operation_scope;
  if (scope === 'nfo_only') return 'NFO only';
  if (scope === 'artwork_only') return 'Artwork only';
  if (scope === 'organize_only') return 'Files only';
  return 'Full';
}

export function deriveHistory(tasks: TaskSnapshot[], filter: HistoryFilter, query = '') {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return [...tasks]
    .filter((task) => {
      if (filter === 'success' && task.status !== 'completed') return false;
      if (filter === 'issues' && !['failed', 'partial', 'stopped', 'interrupted'].includes(task.status)) return false;
      if (filter === 'rollback' && !task.rollback_available) return false;
      if (!normalizedQuery) return true;
      return [
        task.input_dir,
        task.id,
        task.status,
        task.config?.strategy,
        task.config?.search_mode,
        task.config?.operation_scope,
      ].some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery));
    })
    .sort((a, b) => Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at));
}

export function historyStats(tasks: TaskSnapshot[]) {
  return tasks.reduce((stats, task) => {
    stats.tasks += 1;
    stats.completed += numberValue(task.summary?.completed);
    stats.failed += numberValue(task.summary?.failed);
    stats.changes += numberValue(task.manifest_summary?.operation_count);
    if (task.rollback_available) stats.rollbackReady += 1;
    return stats;
  }, { tasks: 0, completed: 0, failed: 0, changes: 0, rollbackReady: 0 });
}

export function historyCleanupConfirmationMessage(preview: TaskHistoryCleanupPreview) {
  const reasonLabels: Record<string, string> = {
    match_review: 'match review',
    plan_review: 'plan approval',
    rollback_available: 'rollback',
    rollback_incomplete: 'rollback review',
    recovery_available: 'recovery',
  };
  const reasonCounts = new Map<string, number>();
  for (const task of preview.retained || []) {
    for (const reason of task.reasons || []) {
      reasonCounts.set(reason, (reasonCounts.get(reason) || 0) + 1);
    }
  }
  const retainedDetails = [...reasonCounts.entries()]
    .map(([reason, count]) => `${count} ${reasonLabels[reason] || reason}`)
    .join(', ');
  const retainedLine = preview.retained_count
    ? `\n${preview.retained_count} actionable task${preview.retained_count === 1 ? '' : 's'} will be retained${retainedDetails ? ` (${retainedDetails})` : ''}.`
    : '';
  return (
    `Clear ${preview.eligible_count} non-actionable history record${preview.eligible_count === 1 ? '' : 's'}?`
    + retainedLine
    + '\n\nMedia files, operation manifests, and rollback backups will not be deleted.'
  );
}
