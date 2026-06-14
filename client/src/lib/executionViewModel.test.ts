import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deriveExecutions,
  executionCurrentItem,
  executionCurrentOperation,
  executionEventLabel,
  executionItemSummary,
  executionOperationLabel,
  executionPhaseLabel,
  executionPhasePercent,
  executionStats,
} from './executionViewModel.ts';
import type { ExecutionRecord } from './types.ts';

const execution = (overrides: Partial<ExecutionRecord> = {}): ExecutionRecord => ({
  id: 'exec-1',
  status: 'running',
  input_dir: '/media/Show',
  created_at: '2026-06-13T01:00:00Z',
  phase: 'metadata',
  progress: { total: 2, processed: 1 },
  config: { source_plan_task_id: 'plan-1' },
  items: {},
  ...overrides,
});

test('execution queue prioritizes active work and supports filters and search', () => {
  const values = [
    execution({ id: 'done', status: 'completed', updated_at: '2026-06-13T03:00:00Z' }),
    execution({ id: 'failed', status: 'failed', input_dir: '/media/Broken' }),
    execution({ id: 'active', status: 'running', updated_at: '2026-06-13T02:00:00Z' }),
  ];
  assert.deepEqual(deriveExecutions(values, 'all').map(item => item.id), ['active', 'done', 'failed']);
  assert.deepEqual(deriveExecutions(values, 'issues').map(item => item.id), ['failed']);
  assert.deepEqual(deriveExecutions(values, 'all', 'broken').map(item => item.id), ['failed']);
});

test('execution stats, phase and progress are deterministic', () => {
  const values = [
    execution(),
    execution({ id: 'done', status: 'completed', phase: 'completed', progress: { total: 1, processed: 1 } }),
    execution({ id: 'partial', status: 'partial', phase: 'partial' }),
  ];
  assert.deepEqual(executionStats(values), { total: 3, running: 1, issues: 1, completed: 1, processed: 3 });
  assert.equal(executionPhaseLabel('verifying'), 'Verifying output');
  assert.equal(executionPhasePercent(values[1]), 100);
  assert.equal(executionPhasePercent(values[0]), 52);
});

test('service restart interruptions are terminal issues rather than active work', () => {
  const interrupted = execution({
    status: 'interrupted',
    phase: 'interrupted',
    progress: { total: 1, processed: 0 },
  });

  assert.deepEqual(executionStats([interrupted]), {
    total: 1,
    running: 0,
    issues: 1,
    completed: 0,
    processed: 0,
  });
  assert.deepEqual(deriveExecutions([interrupted], 'issues').map(item => item.id), ['exec-1']);
  assert.equal(executionPhaseLabel('interrupted'), 'Interrupted by restart');
  assert.equal(executionPhasePercent(interrupted), 0);
  assert.equal(executionEventLabel({
    type: 'task.interrupted',
    timestamp: '2026-06-14T00:00:00Z',
    payload: { reason: 'process_restart' },
  }), 'Interrupted when the service restarted');
});

test('execution detail selects the active item and explains timeline events', () => {
  const value = execution({
    items: {
      old: { status: 'completed', name: 'Old' },
      current: { status: 'verifying', name: 'Current' },
    },
  });
  assert.equal(executionCurrentItem(value)?.name, 'Current');
  assert.equal(executionEventLabel({
    type: 'item.execution_phase',
    timestamp: '2026-06-13T01:00:00Z',
    payload: { phase: 'organizing' },
  }), 'Organizing files');
  assert.equal(executionEventLabel({
    type: 'item.verification_completed',
    timestamp: '2026-06-13T01:00:00Z',
    payload: { verification: { status: 'partial', warnings: 2, failed: 0 } },
  }), 'Verification needs review · 2 warnings');
  assert.equal(executionItemSummary({
    status: 'partial',
    verification: { warnings: 1, failed: 0 },
  }), 'Verification needs review · 1 warning');
  assert.equal(executionItemSummary({
    status: 'failed',
    error: 'move_file failed at organize.file_operation',
    operation: { destination: '/library/Show/Season 01/episode.mkv' },
  }), 'move_file failed at organize.file_operation · /library/Show/Season 01/episode.mkv');
});

test('execution detail exposes current file operation and lifecycle labels', () => {
  const operation = {
    action: 'move_file',
    stage: 'organize.file_operation',
    source: '/incoming/episode.mkv',
    destination: '/library/Show/Season 01/episode.mkv',
  };
  const value = execution({
    items: {
      current: {
        status: 'processing',
        name: 'Show',
        current_operation: operation,
      },
    },
  });

  assert.deepEqual(executionCurrentOperation(value), operation);
  assert.equal(
    executionOperationLabel(operation),
    'move file: /incoming/episode.mkv → /library/Show/Season 01/episode.mkv',
  );
  assert.equal(executionEventLabel({
    type: 'operation.started',
    timestamp: '2026-06-13T01:00:00Z',
    payload: { operation },
  }), 'Started move file: /incoming/episode.mkv → /library/Show/Season 01/episode.mkv');
  assert.equal(executionEventLabel({
    type: 'operation.failed',
    timestamp: '2026-06-13T01:00:01Z',
    payload: { operation: { ...operation, error: 'permission denied' } },
  }), 'Failed move file: /incoming/episode.mkv → /library/Show/Season 01/episode.mkv · permission denied');
  assert.deepEqual(deriveExecutions([value], 'all', 'season 01').map(item => item.id), ['exec-1']);
});
