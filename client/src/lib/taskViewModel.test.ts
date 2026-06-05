import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyTaskEvent,
  buildTaskStartPayload,
  deriveTaskBoardState,
  formatPlanSummary,
  getTaskViewKey,
  issueFromRecord,
  taskFromSnapshot,
  taskFromSnapshotItem,
} from './taskViewModel.ts';
import type { TaskSnapshot } from './types.ts';

const baseSnapshot: TaskSnapshot = {
  id: 'task-1',
  status: 'running',
  input_dir: '/media/Source',
  created_at: '2026-06-04T00:00:00.000Z',
  summary: { total: 1, completed: 0, failed: 0 },
  config: { enable_organize: true, search_mode: 'tavily_only' },
  items: {},
};

test('formatPlanSummary prioritizes blockers over action counts', () => {
  assert.equal(formatPlanSummary({ actions: 12, risks: 3, conflicts: 2, blocked: 1 }), '2 conflicts · 1 blocked');
  assert.equal(formatPlanSummary({ actions: 12, risks: 3, conflicts: 0, blocked: 0 }), '12 actions · 3 risks');
  assert.equal(formatPlanSummary({ actions: 12, metadata_writes: 4 }), '12 actions · 4 metadata');
});

test('taskFromSnapshotItem keeps failure reason ahead of plan summary', () => {
  const task = taskFromSnapshotItem(baseSnapshot, '/media/Bad Movie', {
    status: 'failed',
    path: '/media/Bad Movie',
    error: 'No reliable metadata candidate',
    plan_summary: { actions: 8, risks: 0, conflicts: 0 },
    candidate: { title: 'Wrong Candidate', tmdb_id: 99, media_type: 'movie' },
  });

  assert.equal(task.status, 'failed');
  assert.equal(task.resultSummary, 'No reliable metadata candidate');
  assert.equal(task.issue?.error, 'No reliable metadata candidate');
  assert.equal(task.tmdbId, '99');
});

test('taskFromSnapshotItem exposes blocker summary for audit cards', () => {
  const task = taskFromSnapshotItem(baseSnapshot, '/media/Blocked Movie', {
    status: 'audit_completed',
    path: '/media/Blocked Movie',
    plan: {
      rollback_available: true,
      summary: { actions: 3, conflicts: 1, blocked: 1, risks: 0 },
      conflicts: [{ reason: 'destination_exists', destination: '/library/Blocked Movie/movie.mkv' }],
    },
  });

  assert.equal(task.status, 'audit_completed');
  assert.equal(task.resultSummary, '1 conflicts · 1 blocked');
  assert.equal(task.rollbackAvailable, true);
  assert.equal(task.planSummary?.conflicts, 1);
});

test('task view models expose a stable path-based view key', () => {
  const parent = taskFromSnapshot(baseSnapshot);
  const item = taskFromSnapshotItem(baseSnapshot, 'opaque-item-id', {
    status: 'audit_completed',
    path: '/media/Nested Movie',
    candidate: { title: 'Nested Movie', tmdb_id: 77, media_type: 'movie' },
  });

  assert.equal(parent.viewKey, '/media/Source');
  assert.equal(getTaskViewKey(parent), '/media/Source');
  assert.equal(item.viewKey, '/media/Nested Movie');
  assert.equal(getTaskViewKey(item), '/media/Nested Movie');
});

test('buildTaskStartPayload preserves execution options from audited task cards', () => {
  const task = taskFromSnapshotItem(baseSnapshot, '/media/Movie', {
    status: 'audit_completed',
    path: '/media/Movie',
    candidate: { title: 'Movie', tmdb_id: 123, media_type: 'movie' },
  });

  const payload = buildTaskStartPayload(task, {
    strategy: 'copy',
    outputPath: '/library',
    searchMode: 'smart',
    forceFresh: true,
    extraImages: true,
    enableOrganize: true,
    overwriteImages: true,
    renameParentDir: true,
  }, {
    tmdbId: '456',
    mediaType: 'tv',
  });

  assert.deepEqual(payload, {
    input_dir: '/media/Movie',
    tmdb_id: 456,
    media_type: 'tv',
    dry_run: false,
    inplace: false,
    copy_mode: true,
    output_dir: '/library',
    fresh: true,
    extra_images: true,
    enable_organize: true,
    overwrite_images: true,
    rename_parent_dir: true,
    search_mode: 'tavily_only',
  });
});

test('buildTaskStartPayload falls back to board search mode and null output in organize mode', () => {
  const task = taskFromSnapshotItem({
    ...baseSnapshot,
    config: {},
  }, '/media/Show', {
    status: 'audit_completed',
    path: '/media/Show',
    candidate: { title: 'Show', media_type: 'tv' },
  });

  const payload = buildTaskStartPayload(task, {
    strategy: 'organize',
    outputPath: '/ignored',
    searchMode: 'tmdb_only',
    extraImages: false,
    enableOrganize: true,
    overwriteImages: false,
    renameParentDir: false,
  });

  assert.equal(payload.tmdb_id, null);
  assert.equal(payload.media_type, 'tv');
  assert.equal(payload.inplace, true);
  assert.equal(payload.copy_mode, false);
  assert.equal(payload.output_dir, null);
  assert.equal(payload.search_mode, 'tmdb_only');
  assert.equal(payload.extra_images, false);
});

test('taskFromSnapshot includes task-level errors as issue details', () => {
  const task = taskFromSnapshot({
    ...baseSnapshot,
    status: 'failed',
    error: 'Input path not found',
  });

  assert.equal(task.status, 'failed');
  assert.equal(task.resultSummary, 'Input path not found');
  assert.equal(task.issue?.path, '/media/Source');
});

test('issueFromRecord ignores successful records without actionable text', () => {
  assert.equal(issueFromRecord({ status: 'completed', result: undefined }), undefined);
  assert.deepEqual(issueFromRecord({ status: 'stopped', path: '/media/A' }), {
    status: 'stopped',
    error: undefined,
    result: undefined,
    path: '/media/A',
    name: undefined,
  });
});

test('applyTaskEvent creates a planned item and keeps full plan preview fields', () => {
  const next = applyTaskEvent({}, {
    task_id: 'task-1',
    item_id: '/media/Movie',
    type: 'item.plan_ready',
    timestamp: '2026-06-04T00:01:00.000Z',
    payload: {
      plan_path: '/logs/plans/task-1/hash.json',
      plan: {
        rollback_available: true,
        summary: { actions: 4, conflicts: 0, risks: 1, metadata_writes: 2 },
        actions: [{ type: 'create_file', destination: '/media/Movie/movie.nfo' }],
      },
    },
  });

  const task = next['/media/Movie'];
  assert.equal(task.status, 'idle');
  assert.equal(task.resultSummary, '4 actions · 1 risks');
  assert.equal(task.planPath, '/logs/plans/task-1/hash.json');
  assert.equal(task.rollbackAvailable, undefined);
});

test('applyTaskEvent stores candidate match and then failure issue details', () => {
  const withCandidate = applyTaskEvent({}, {
    task_id: 'task-1',
    item_id: '/media/Maybe',
    type: 'candidate.selected',
    timestamp: '2026-06-04T00:01:00.000Z',
    payload: {
      title: 'Maybe',
      tmdb_id: 123,
      media_type: 'movie',
      match: { provider: 'tmdb', confidence: 'medium', score: 0.72 },
    },
  });

  const failed = applyTaskEvent(withCandidate, {
    task_id: 'task-1',
    item_id: '/media/Maybe',
    type: 'item.failed',
    timestamp: '2026-06-04T00:02:00.000Z',
    payload: {
      path: '/media/Maybe',
      error: 'Plan conflict',
      plan_summary: { actions: 2, conflicts: 1, blocked: 1 },
      lock: { target_path: '/media/Maybe', owner: 'other-task' },
    },
  });

  const task = failed['/media/Maybe'];
  assert.equal(task.status, 'failed');
  assert.equal(task.match?.confidence, 'medium');
  assert.equal(task.resultSummary, 'Plan conflict');
  assert.equal(task.issue?.error, 'Plan conflict');
  assert.equal(task.lock?.owner, 'other-task');
  assert.equal(task.planSummary?.conflicts, 1);
});

test('applyTaskEvent applies task-level partial and rollback updates to related items only', () => {
  const tasks = {
    '/media/A': {
      threadId: '/media/A',
      taskId: 'task-1',
      createdAt: 0,
      name: 'A',
      status: 'processing',
      step: 'Scanning',
      lastLog: '',
      logs: [],
      isExpanded: false,
    },
    '/media/B': {
      threadId: '/media/B',
      taskId: 'task-2',
      createdAt: 0,
      name: 'B',
      status: 'processing',
      step: 'Scanning',
      lastLog: '',
      logs: [],
      isExpanded: false,
    },
  } as const;

  const partial = applyTaskEvent(tasks, {
    task_id: 'task-1',
    type: 'task.partial',
    timestamp: '2026-06-04T00:03:00.000Z',
    payload: { summary: { total: 2, completed: 1, failed: 1 } },
  });

  assert.equal(partial['/media/A'].status, 'partial');
  assert.equal(partial['/media/A'].resultSummary, '1/2 done · 1 failed');
  assert.equal(partial['/media/B'].status, 'processing');

  const rollback = applyTaskEvent(partial, {
    task_id: 'task-1',
    type: 'task.rollback_completed',
    timestamp: '2026-06-04T00:04:00.000Z',
    payload: { status: 'completed', operations: [] },
  });

  assert.equal(rollback['/media/A'].status, 'stopped');
  assert.equal(rollback['/media/A'].resultSummary, '已回滚');
  assert.equal(rollback['/media/A'].rollback?.status, 'completed');
  assert.equal(rollback['/media/B'].status, 'processing');
});

test('taskFromSnapshotItem keeps rollback state visible after refresh', () => {
  const task = taskFromSnapshotItem({
    ...baseSnapshot,
    status: 'stopped',
    rollback: { status: 'completed', operations: [] },
  }, '/media/Rolled Back', {
    status: 'stopped',
    path: '/media/Rolled Back',
    result: '任务成功',
    candidate: { title: 'Rolled Back', tmdb_id: 321, media_type: 'movie' },
  });

  assert.equal(task.status, 'stopped');
  assert.equal(task.resultSummary, '已回滚');
  assert.equal(task.rollback?.status, 'completed');
});

const viewTask = (overrides: Partial<ReturnType<typeof taskFromSnapshot>> & { threadId: string; name: string }) => ({
  createdAt: 0,
  status: 'idle' as const,
  step: 'Preparing',
  lastLog: '',
  logs: [],
  isExpanded: false,
  ...overrides,
});

test('deriveTaskBoardState deduplicates by path and keeps richer task data', () => {
  const state = deriveTaskBoardState({
    weak: viewTask({
      threadId: 'weak',
      name: 'Movie',
      fullPath: '/media/Movie',
      logs: ['weak'],
    }),
    rich: viewTask({
      threadId: 'rich',
      name: 'Movie',
      fullPath: '/media/Movie',
      tmdbId: '123',
      posterPath: 'poster.jpg',
      resultSummary: 'done',
      status: 'completed',
      logs: ['rich'],
    }),
  }, { field: 'time', direction: 'desc' }, 'all');

  assert.equal(state.allVisibleTasks.length, 1);
  assert.equal(state.allVisibleTasks[0].viewKey, '/media/Movie');
  assert.equal(state.allVisibleTasks[0].threadId, 'rich');
  assert.deepEqual(state.allVisibleTasks[0].logs, ['rich', 'weak']);
  assert.equal(state.stats.doneOnlyCount, 1);
});

test('deriveTaskBoardState hides empty idle placeholders and computes focus counts', () => {
  const state = deriveTaskBoardState({
    placeholder: viewTask({ threadId: 'placeholder', name: 'Initializing' }),
    running: viewTask({ threadId: 'running', name: 'Running', fullPath: '/media/Running', status: 'processing' }),
    ready: viewTask({
      threadId: 'ready',
      name: 'Ready',
      fullPath: '/media/Ready',
      status: 'audit_completed',
      planSummary: { actions: 2, conflicts: 0, blocked: 0 },
    }),
    blocked: viewTask({
      threadId: 'blocked',
      name: 'Blocked',
      fullPath: '/media/Blocked',
      status: 'audit_completed',
      planSummary: { actions: 2, conflicts: 1, blocked: 1 },
    }),
    done: viewTask({ threadId: 'done', name: 'Done', fullPath: '/media/Done', status: 'completed' }),
  }, { field: 'status', direction: 'asc' }, 'focus');

  assert.equal(state.allVisibleTasks.length, 4);
  assert.equal(state.stats.runningCount, 1);
  assert.equal(state.stats.readyCount, 1);
  assert.equal(state.stats.issueCount, 1);
  assert.equal(state.stats.doneOnlyCount, 1);
  assert.deepEqual(state.filteredTasks.map((task) => task.threadId).sort(), ['blocked', 'ready', 'running']);
});

test('deriveTaskBoardState supports focused filter views and sort order', () => {
  const tasks = {
    zeta: viewTask({ threadId: 'zeta', name: 'Zeta', fullPath: '/media/Zeta', status: 'completed', createdAt: 1 }),
    alpha: viewTask({ threadId: 'alpha', name: 'Alpha', fullPath: '/media/Alpha', status: 'failed', createdAt: 2 }),
    beta: viewTask({ threadId: 'beta', name: 'Beta', fullPath: '/media/Beta', status: 'audit_completed', createdAt: 3 }),
  };

  const allByName = deriveTaskBoardState(tasks, { field: 'name', direction: 'asc' }, 'all');
  assert.deepEqual(allByName.filteredTasks.map((task) => task.name), ['Alpha', 'Beta', 'Zeta']);

  const issues = deriveTaskBoardState(tasks, { field: 'time', direction: 'desc' }, 'issues');
  assert.deepEqual(issues.filteredTasks.map((task) => task.threadId), ['alpha']);

  const done = deriveTaskBoardState(tasks, { field: 'time', direction: 'desc' }, 'done');
  assert.deepEqual(done.filteredTasks.map((task) => task.threadId), ['zeta']);
});
