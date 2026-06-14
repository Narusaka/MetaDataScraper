import assert from 'node:assert/strict';
import test from 'node:test';

import { deriveHistory, historyCleanupConfirmationMessage, historyScopeLabel, historyStats, historyStatusLabel, historyStrategyLabel, historyTone } from './historyViewModel.ts';
import type { TaskSnapshot } from './types.ts';

const task = (overrides: Partial<TaskSnapshot>): TaskSnapshot => ({
  id: 'task',
  status: 'completed',
  input_dir: '/media/Movie',
  created_at: '2026-06-06T00:00:00Z',
  summary: { total: 1, completed: 1, failed: 0 },
  ...overrides,
});

test('history derivation sorts newest first and supports focused filters', () => {
  const tasks = [
    task({ id: 'old', created_at: '2026-06-01T00:00:00Z' }),
    task({ id: 'failed', status: 'failed', input_dir: '/media/Failed', created_at: '2026-06-03T00:00:00Z' }),
    task({
      id: 'rollback',
      input_dir: '/media/Rollback',
      created_at: '2026-06-02T00:00:00Z',
      rollback_available: true,
    }),
  ];

  assert.deepEqual(deriveHistory(tasks, 'all').map(item => item.id), ['failed', 'rollback', 'old']);
  assert.deepEqual(deriveHistory(tasks, 'issues').map(item => item.id), ['failed']);
  assert.deepEqual(deriveHistory(tasks, 'rollback').map(item => item.id), ['rollback']);
  assert.deepEqual(deriveHistory(tasks, 'all', 'movie').map(item => item.id), ['old']);
});

test('history stats use manifest evidence and item summaries', () => {
  const stats = historyStats([
    task({
      id: 'one',
      summary: { total: 3, completed: 2, failed: 1 },
      rollback_available: true,
      manifest_summary: { exists: true, operation_count: 8, reversible_count: 6, action_counts: {} },
    }),
    task({
      id: 'two',
      summary: { total: 1, completed: 1, failed: 0 },
      manifest_summary: { exists: false, operation_count: 0, reversible_count: 0, action_counts: {} },
    }),
  ]);

  assert.deepEqual(stats, { tasks: 2, completed: 3, failed: 1, changes: 8, rollbackReady: 1 });
});

test('rolled back tasks have a neutral final state', () => {
  const rolledBack = task({ rolled_back: true, rollback: { status: 'completed' } });

  assert.equal(historyTone(rolledBack), 'neutral');
  assert.equal(historyStatusLabel(rolledBack), 'Rolled back');
  assert.equal(historyTone(task({ status: 'failed' })), 'danger');
});

test('history exposes incomplete rollback as a separate retryable state', () => {
  const partial = task({
    status: 'completed',
    rollback: { status: 'partial' },
    rollback_available: true,
  });
  const failed = task({
    status: 'completed',
    rollback: { status: 'failed' },
    rollback_available: true,
  });

  assert.equal(historyStatusLabel(partial), 'Rollback needs review');
  assert.equal(historyTone(partial), 'warning');
  assert.equal(historyStatusLabel(failed), 'Rollback failed');
  assert.equal(historyTone(failed), 'danger');
  assert.deepEqual(deriveHistory([partial, failed], 'rollback').map(item => item.id), ['task', 'task']);
});

test('history strategy hides internal inplace and boolean transport values', () => {
  assert.equal(historyStrategyLabel(task({ config: { strategy: 'inplace' } })), 'Organize');
  assert.equal(historyStrategyLabel(task({ config: { inplace: true } })), 'Organize');
  assert.equal(historyStrategyLabel(task({ config: { copy_mode: true } })), 'Copy');
  assert.equal(historyStrategyLabel(task({ config: { dry_run: true } })), 'Metadata');
  assert.equal(historyStrategyLabel(task({ config: { strategy: 'copy', dry_run: true } })), 'Copy');
});

test('history exposes operation scope and cancellation as auditable state', () => {
  const cancelled = task({
    status: 'cancelled',
    config: { operation_scope: 'artwork_only' },
    cancel: { stage: 'artwork.download' },
  });

  assert.equal(historyScopeLabel(cancelled), 'Artwork only');
  assert.equal(historyStatusLabel(cancelled), 'Cancelled');
  assert.equal(historyTone(cancelled), 'neutral');
  assert.deepEqual(deriveHistory([cancelled], 'all', 'artwork').map(item => item.id), ['task']);
});

test('interrupted tasks are prominent issue history with an explicit label', () => {
  const interrupted = task({
    status: 'interrupted',
    interruption: {
      reason: 'process_restart',
      previous_status: 'running',
      recoverable: true,
    },
  });

  assert.equal(historyStatusLabel(interrupted), 'Interrupted');
  assert.equal(historyTone(interrupted), 'danger');
  assert.deepEqual(deriveHistory([interrupted], 'issues').map(item => item.id), ['task']);
});

test('history cleanup confirmation explains deletions and protected evidence', () => {
  const message = historyCleanupConfirmationMessage({
    eligible_count: 3,
    task_ids: ['one', 'two', 'three'],
    retained_count: 2,
    retained: [
      { task_id: 'plan', reasons: ['plan_review'] },
      { task_id: 'recovery', reasons: ['rollback_available', 'recovery_available'] },
    ],
  });

  assert.match(message, /Clear 3 non-actionable history records/);
  assert.match(message, /2 actionable tasks will be retained/);
  assert.match(message, /1 plan approval/);
  assert.match(message, /1 rollback/);
  assert.match(message, /1 recovery/);
  assert.match(message, /rollback backups will not be deleted/);
});
