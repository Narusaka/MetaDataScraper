import type { DashboardSummary, TaskSnapshot } from './types';

export const dashboardAttentionCount = (summary?: DashboardSummary) => (
  (summary?.queues.match_reviews || 0)
  + (summary?.queues.plan_reviews.blocked || 0)
  + (summary?.queues.plan_reviews.drifted || 0)
  + (summary?.queues.executions.issues || 0)
);

export const dashboardSuccessRate = (summary?: DashboardSummary) => {
  const total = summary?.stats.total_media || 0;
  return total ? Math.round(((summary?.stats.total_success || 0) / total) * 100) : 100;
};

export const dashboardPrimaryAction = (summary?: DashboardSummary) => {
  if (!summary) return { tab: 'library_scan', label: 'Scan library' };
  if (summary.queues.executions.running > 0) return { tab: 'execution', label: 'Watch execution' };
  if (summary.queues.executions.issues > 0) return { tab: 'history', label: 'Review recovery' };
  if (summary.queues.match_reviews > 0) return { tab: 'match_review', label: 'Review matches' };
  if (summary.queues.plan_reviews.blocked + summary.queues.plan_reviews.drifted > 0) {
    return { tab: 'plan_review', label: 'Resolve plans' };
  }
  if (summary.queues.plan_reviews.ready > 0) return { tab: 'plan_review', label: 'Review plans' };
  return { tab: 'library_scan', label: 'Scan library' };
};

export const recentTaskStatus = (task: TaskSnapshot) => {
  if (task.rolled_back || task.rollback?.status === 'completed') return 'Rolled back';
  if (task.status === 'partial') return 'Partial';
  if (task.status === 'stopped') return 'Stopped';
  if (task.status === 'interrupted') return 'Interrupted';
  return task.status.replaceAll('_', ' ');
};
