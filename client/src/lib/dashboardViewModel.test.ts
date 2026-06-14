import assert from 'node:assert/strict';
import test from 'node:test';

import {
  dashboardAttentionCount,
  dashboardPrimaryAction,
  dashboardSuccessRate,
  recentTaskStatus,
} from './dashboardViewModel.ts';
import type { DashboardSummary } from './types.ts';

const summary = (overrides: Partial<DashboardSummary> = {}): DashboardSummary => ({
  generated_at: '2026-06-13T00:00:00Z',
  worker: { running: false, workers: 1 },
  queues: {
    match_reviews: 0,
    plan_reviews: { total: 0, ready: 0, blocked: 0, drifted: 0 },
    executions: { total: 0, running: 0, issues: 0 },
    history: { finished: 0, failed: 0, rollback_ready: 0 },
  },
  services: {
    tmdb: { configured: true },
    tavily: { configured: true },
    model: { configured: false },
  },
  stats: { total_tasks: 0, total_media: 0, total_success: 0, total_failed: 0, total_duration: 0 },
  recent: [],
  ...overrides,
});

test('dashboard selects the most urgent workflow action', () => {
  assert.equal(dashboardPrimaryAction(summary()).tab, 'library_scan');
  assert.equal(dashboardPrimaryAction(summary({
    queues: {
      ...summary().queues,
      match_reviews: 3,
    },
  })).tab, 'match_review');
  assert.equal(dashboardPrimaryAction(summary({
    queues: {
      ...summary().queues,
      executions: { total: 1, running: 1, issues: 0 },
    },
  })).tab, 'execution');
  assert.deepEqual(dashboardPrimaryAction(summary({
    queues: {
      ...summary().queues,
      executions: { total: 1, running: 0, issues: 1 },
    },
  })), { tab: 'history', label: 'Review recovery' });
});

test('dashboard derives attention and success rate from stable counts', () => {
  const value = summary({
    queues: {
      match_reviews: 2,
      plan_reviews: { total: 4, ready: 1, blocked: 2, drifted: 1 },
      executions: { total: 2, running: 0, issues: 3 },
      history: { finished: 10, failed: 2, rollback_ready: 1 },
    },
    stats: { total_tasks: 4, total_media: 10, total_success: 8, total_failed: 2, total_duration: 30 },
  });
  assert.equal(dashboardAttentionCount(value), 8);
  assert.equal(dashboardSuccessRate(value), 80);
  assert.equal(recentTaskStatus({
    id: 'task',
    status: 'completed',
    input_dir: '/media',
    created_at: '',
    rolled_back: true,
  }), 'Rolled back');
});
