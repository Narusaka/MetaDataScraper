import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyTaskEvent,
  buildTaskStartPayload,
  clearTaskHistoryItems,
  deriveTaskBoardState,
  formatPlanSummary,
  getTaskViewKey,
  hasTaskIssue,
  issueFromRecord,
  planReviewHeadline,
  planReviewItems,
  rollbackRiskCount,
  rollbackPreviewConfirmationMessage,
  rollbackResultPresentation,
  summarizePlanPreview,
  summarizeManifestOperations,
  taskFromSnapshot,
  taskFromSnapshotItem,
} from './taskViewModel.ts';
import type { TaskViewModel } from './taskViewModel.ts';
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

test('plan review exposes duplicate episode evidence and repair guidance', () => {
  const plan = {
    summary: { actions: 8, blocked: 1, risks: 2 },
    review: {
      required: true,
      status: 'manual_review',
      reasons: [{
        level: 'error',
        code: 'duplicate_episode_files',
        message: '2 video files claim S01E01.',
        episode: 'S01E01',
        sources: ['/media/Show/one.mkv', '/media/Show/two.mkv'],
      }],
    },
  };

  const items = planReviewItems(plan);
  assert.equal(items.length, 1);
  assert.equal(items[0].code, 'duplicate_episode_files');
  assert.equal(items[0].sources.length, 2);
  assert.match(items[0].guidance, /unique/);
  assert.equal(planReviewHeadline(plan), 'S01E01 is claimed by 2 video files');
});

test('plan review merges legacy duplicate-episode risk and action reasons', () => {
  const items = planReviewItems({
    summary: { actions: 8, blocked: 1, risks: 2 },
    review: {
      required: true,
      reasons: [
        {
          code: 'duplicate_episode_files',
          message: '2 video files claim S01E01.',
          episode: 'S01E01',
          sources: ['/media/Show/one.mkv', '/media/Show/two.mkv'],
        },
        {
          code: 'duplicate_episode_files',
          message: 'This action requires manual review before execution.',
          episode: 'S01E01',
          source: '/media/Show/two.mkv',
        },
      ],
    },
  });

  assert.equal(items.length, 1);
  assert.deepEqual(items[0].sources, ['/media/Show/one.mkv', '/media/Show/two.mkv']);
});

test('plan review falls back to compact blocked actions', () => {
  const items = planReviewItems({
    summary: { actions: 2, blocked: 1 },
    actions: [{
      type: 'manual_review',
      kind: 'duplicate_episode',
      status: 'blocked',
      reason: 'duplicate_episode_files',
      episode: 'S02E03',
      source: '/media/Show/duplicate.mkv',
    }],
  });

  assert.equal(items[0].code, 'duplicate_episode_files');
  assert.deepEqual(items[0].sources, ['/media/Show/duplicate.mkv']);
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

test('taskFromSnapshotItem exposes planned output path and rollback risk count', () => {
  const task = taskFromSnapshotItem({
    ...baseSnapshot,
    rollback: {
      status: 'partial',
      operations: [
        { status: 'removed_created_file', destination: '/library/Movie/poster.jpg' },
        { status: 'current_modified', destination: '/library/Movie/movie.nfo' },
      ],
    },
  }, '/media/Movie', {
    status: 'completed',
    path: '/media/Movie',
    plan: {
      target_root: '/library/Movie',
      rollback_available: true,
      summary: { actions: 3, conflicts: 0, blocked: 0 },
    },
  });

  assert.equal(task.outputPath, '/library/Movie');
  assert.equal(task.rollbackRiskCount, 1);
  assert.equal(rollbackRiskCount(task.rollback), 1);
});

test('summarizeManifestOperations counts auditable rollback evidence', () => {
  const summary = summarizeManifestOperations({
    operations: [
      { action: 'create_file', destination: '/library/Movie/movie.nfo' },
      { action: 'create_file', destination: '/library/Movie/poster.jpg' },
      { action: 'move_file', source: '/downloads/movie.mkv', destination: '/library/Movie/movie.mkv' },
      { action: 'overwrite_file', destination: '/library/Movie/fanart.jpg' },
      { action: 'custom_action', destination: '/library/Movie/custom' },
    ],
  });

  assert.equal(summary.total, 5);
  assert.equal(summary.reversible, 4);
  assert.equal(summary.review, 0);
  assert.equal(summary.preview[0].destination, '/library/Movie/movie.nfo');
  assert.deepEqual(summary.counts, {
    create_file: 2,
    move_file: 1,
    overwrite_file: 1,
    custom_action: 1,
  });
});

test('summarizeManifestOperations surfaces review operations and omitted count', () => {
  const summary = summarizeManifestOperations({
    operations: [
      { action: 'create_file', status: 'done', destination: '/library/0.nfo' },
      { action: 'overwrite_file', status: 'current_modified', destination: '/library/1.nfo' },
      { action: 'move_file', status: 'done', destination: '/library/2.mkv' },
      { action: 'move_file', status: 'done', destination: '/library/3.mkv' },
      { action: 'move_file', status: 'done', destination: '/library/4.mkv' },
      { action: 'move_file', status: 'done', destination: '/library/5.mkv' },
      { action: 'move_file', status: 'done', destination: '/library/6.mkv' },
      { action: 'move_file', status: 'done', destination: '/library/7.mkv' },
      { action: 'move_file', status: 'missing_destination', destination: '/library/8.mkv' },
    ],
  });

  assert.equal(summary.review, 2);
  assert.equal(summary.preview.length, 8);
  assert.equal(summary.omitted, 1);
  assert.equal(summary.preview[1].status, 'current_modified');
});

test('rollbackPreviewConfirmationMessage summarizes operation and review counts', () => {
  const message = rollbackPreviewConfirmationMessage({
    operations: [
      { status: 'would_removed_created_file' },
      { status: 'current_modified' },
      { status: 'missing_backup' },
    ],
  });

  assert.match(message, /3 operations/);
  assert.match(message, /2 operations need review/);
});

test('summarizePlanPreview exposes compact hidden plan work', () => {
  const summary = summarizePlanPreview({
    compact: true,
    full_plan_available: true,
    preview_omitted: true,
    summary: { actions: 12, risks: 4, conflicts: 2 },
    actions: [{ type: 'create_file' }, { type: 'move_file' }],
    risks: [{ code: 'missing_episodes' }],
    conflicts: [],
  });

  assert.equal(summary.compact, true);
  assert.equal(summary.fullPlanAvailable, true);
  assert.equal(summary.hiddenActions, 10);
  assert.equal(summary.hiddenRisks, 3);
  assert.equal(summary.hiddenConflicts, 2);
  assert.equal(summary.hasHiddenPreview, true);
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
    conflictStrategy: 'suffix',
  }, {
    tmdbId: '456',
    mediaType: 'tv',
  });

  assert.deepEqual(payload, {
    input_dir: '/media/Movie',
    tmdb_id: 456,
    media_type: 'tv',
    dry_run: true,
    inplace: false,
    copy_mode: true,
    output_dir: '/library',
    fresh: true,
    extra_images: true,
    enable_organize: true,
    overwrite_images: true,
    rename_parent_dir: true,
    conflict_strategy: 'suffix',
    operation_scope: 'full',
    search_mode: 'tavily_only',
    intended_strategy: 'copy',
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
  assert.equal(payload.intended_strategy, 'organize');
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

test('task-level summary reports quarantined items separately from success', () => {
  const task = taskFromSnapshot({
    ...baseSnapshot,
    status: 'partial',
    summary: { total: 2, completed: 1, failed: 0, quarantined: 1 },
  });

  assert.equal(task.resultSummary, '1/2 done · 0 failed · 1 quarantined');
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
      plan_digest: 'a'.repeat(64),
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
  assert.equal(task.planDigest, 'a'.repeat(64));
  assert.equal(task.rollbackAvailable, true);
  assert.equal(task.outputPath, undefined);
});

test('confirmed execution and plan drift remain visible on the audited item', () => {
  const ready = viewTask({
    taskId: 'audit-task',
    threadId: '/media/Movie',
    fullPath: '/media/Movie',
    status: 'audit_completed',
  });
  const confirmed = applyTaskEvent({ '/media/Movie': ready }, {
    task_id: 'audit-task',
    item_id: '/media/Movie',
    type: 'item.execution_started',
    timestamp: '2026-06-04T00:02:00.000Z',
    payload: { execution_task_id: 'execution-task', plan_digest: 'a'.repeat(64) },
  });
  const drifted = applyTaskEvent(confirmed, {
    task_id: 'audit-task',
    item_id: '/media/Movie',
    type: 'item.plan_drifted',
    timestamp: '2026-06-04T00:03:00.000Z',
    payload: { drift: [{ path: '/media/Movie/movie.mkv' }] },
  });

  assert.equal(confirmed['/media/Movie'].planConfirmation?.status, 'executing');
  assert.equal(confirmed['/media/Movie'].hasExecuted, true);
  assert.equal(drifted['/media/Movie'].planConfirmation?.status, 'drifted');
  assert.equal(drifted['/media/Movie'].hasExecuted, false);
});

test('applyTaskEvent stores target output path from plan and rollback review summary', () => {
  const planned = applyTaskEvent({}, {
    task_id: 'task-1',
    item_id: '/media/Movie',
    type: 'item.plan_ready',
    timestamp: '2026-06-04T00:01:00.000Z',
    payload: {
      plan: {
        target_root: '/library/Movie',
        rollback_available: true,
        summary: { actions: 4, conflicts: 0, risks: 0, metadata_writes: 2 },
      },
    },
  });

  const withCandidate = applyTaskEvent(planned, {
    task_id: 'task-1',
    item_id: '/media/Movie',
    type: 'candidate.selected',
    timestamp: '2026-06-04T00:01:30.000Z',
    payload: {
      title: 'Movie',
      tmdb_id: 123,
      media_type: 'movie',
    },
  });

  const rolledBack = applyTaskEvent(withCandidate, {
    task_id: 'task-1',
    type: 'task.rollback_partial',
    timestamp: '2026-06-04T00:02:00.000Z',
    payload: {
      status: 'partial',
      operations: [
        { status: 'removed_created_file', destination: '/library/Movie/poster.jpg' },
        { status: 'current_modified', destination: '/library/Movie/movie.nfo' },
      ],
    },
  });

  const task = rolledBack['/media/Movie'];
  assert.equal(task.outputPath, '/library/Movie');
  assert.equal(task.rollbackRiskCount, 1);
  assert.equal(task.resultSummary, '回滚需复核 · 1 项');
  assert.equal(task.rollbackAvailable, true);
  assert.equal(task.status, 'fetching');
});

test('rollback presentation distinguishes progress, retryable failures, and completion', () => {
  assert.deepEqual(rollbackResultPresentation({ status: 'running' }), {
    status: 'running',
    completed: false,
    retryable: false,
    riskCount: 0,
    step: 'Rolling back',
    summary: 'Rollback in progress',
  });
  assert.equal(rollbackResultPresentation({ status: 'failed' }).retryable, true);
  assert.equal(rollbackResultPresentation({ status: 'failed' }).summary, '回滚失败');
  assert.equal(rollbackResultPresentation({ status: 'completed' }).completed, true);
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

test('applyTaskEvent records structured nfo output evidence', () => {
  const initial = applyTaskEvent({}, {
    task_id: 'task-nfo',
    item_id: '/media/Show',
    type: 'item.started',
    timestamp: '2026-06-11T00:00:00Z',
    payload: { name: 'Show', path: '/media/Show' },
  });
  const updated = applyTaskEvent(initial, {
    task_id: 'task-nfo',
    item_id: '/media/Show',
    type: 'nfo.written',
    timestamp: '2026-06-11T00:00:01Z',
    payload: { path: '/media/Show/tvshow.nfo', kind: 'main_nfo', atomic: true },
  });
  const task = Object.values(updated)[0];

  assert.equal(task.nfoOutputs?.length, 1);
  assert.equal(task.nfoOutputs?.[0].path, '/media/Show/tvshow.nfo');
  assert.equal(task.resultSummary, '1 NFO written');
});

test('verification lifecycle exposes evidence and partial completion', () => {
  const started = applyTaskEvent({}, {
    task_id: 'task-verify',
    item_id: '/media/Movie',
    type: 'item.verification_started',
    timestamp: '2026-06-11T00:00:00Z',
    payload: { name: 'Movie', path: '/media/Movie' },
  });
  assert.equal(started['/media/Movie'].status, 'verifying');
  assert.equal(started['/media/Movie'].step, 'Verifying outputs');

  const verification = {
    status: 'partial',
    checked: 3,
    passed: 2,
    failed: 0,
    warnings: 1,
    warning_codes: ['artwork_incomplete'],
  };
  const verified = applyTaskEvent(started, {
    task_id: 'task-verify',
    item_id: '/media/Movie',
    type: 'item.verification_completed',
    timestamp: '2026-06-11T00:00:01Z',
    payload: { verification },
  });
  const partial = applyTaskEvent(verified, {
    task_id: 'task-verify',
    item_id: '/media/Movie',
    type: 'item.partial',
    timestamp: '2026-06-11T00:00:02Z',
    payload: { result: 'Execution completed with verification warnings', verification },
  });

  assert.equal(partial['/media/Movie'].status, 'partial');
  assert.equal(partial['/media/Movie'].verification?.status, 'partial');
  assert.equal(partial['/media/Movie'].hasExecuted, true);
  assert.equal(partial['/media/Movie'].resultSummary, 'Execution completed with verification warnings');
});

test('recovery lifecycle is attached to the original failed task', () => {
  const tasks = {
    '/media/Movie': {
      threadId: '/media/Movie',
      taskId: 'task-recovery',
      createdAt: 0,
      name: 'Movie',
      status: 'failed',
      step: 'Error',
      lastLog: 'move failed',
      logs: [],
      isExpanded: false,
    },
  } satisfies Record<string, TaskViewModel>;
  const started = applyTaskEvent(tasks, {
    task_id: 'task-recovery',
    type: 'task.recovery_started',
    timestamp: '2026-06-11T00:00:00Z',
    payload: { strategy: 'rollback_then_retry' },
  });
  const completed = applyTaskEvent(started, {
    task_id: 'task-recovery',
    type: 'task.recovery_completed',
    timestamp: '2026-06-11T00:00:01Z',
    payload: { strategy: 'rollback_then_retry', retry_task_id: 'task-new' },
  });

  assert.equal(started['/media/Movie'].recovery?.status, 'running');
  assert.equal(completed['/media/Movie'].recovery?.status, 'restarted');
  assert.equal(completed['/media/Movie'].resultSummary, 'Recovered as task-new');
});

test('quarantined filename remains an actionable issue without becoming failed', () => {
  const updated = applyTaskEvent({}, {
    task_id: 'task-quarantine',
    item_id: '/media/1080p.x265.mkv',
    type: 'item.quarantined',
    timestamp: '2026-06-11T00:00:00Z',
    payload: {
      name: '1080p.x265.mkv',
      path: '/media/1080p.x265.mkv',
      kind: 'quarantined',
      reason: 'Filename could not be parsed with sufficient confidence.',
      parse: { confidence: 'none', reasons: ['no_stable_title'] },
    },
  });
  const task = updated['/media/1080p.x265.mkv'];

  assert.equal(task.status, 'quarantined');
  assert.equal(task.step, 'Needs naming');
  assert.equal(task.issue?.reason, 'Filename could not be parsed with sufficient confidence.');
  assert.equal((task.issue?.parse as Record<string, unknown>).confidence, 'none');
  assert.equal(hasTaskIssue(task), true);
});

test('cancellation lifecycle moves running items through cancelling to cancelled', () => {
  const running = applyTaskEvent({}, {
    task_id: 'task-cancel',
    item_id: '/media/Movie',
    type: 'item.started',
    timestamp: '2026-06-11T00:00:00Z',
    payload: { name: 'Movie', path: '/media/Movie' },
  });
  const requested = applyTaskEvent(running, {
    task_id: 'task-cancel',
    type: 'task.cancel_requested',
    timestamp: '2026-06-11T00:00:01Z',
    payload: { stage: 'requested' },
  });
  assert.equal(requested['/media/Movie'].status, 'cancel_requested');
  assert.equal(requested['/media/Movie'].step, 'Cancelling');

  const cancelled = applyTaskEvent(requested, {
    task_id: 'task-cancel',
    item_id: '/media/Movie',
    type: 'item.cancelled',
    timestamp: '2026-06-11T00:00:02Z',
    payload: { stage: 'artwork.stream' },
  });
  assert.equal(cancelled['/media/Movie'].status, 'cancelled');
  assert.equal(cancelled['/media/Movie'].resultSummary, 'Cancelled during artwork.stream');
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

  assert.equal(rollback['/media/A'].status, 'partial');
  assert.equal(rollback['/media/A'].resultSummary, '已回滚');
  assert.equal(rollback['/media/A'].rollback?.status, 'completed');
  assert.equal(rollback['/media/A'].rollbackAvailable, false);
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
  assert.deepEqual(state.allVisibleTasks[0].logs, ['rich']);
  assert.equal(state.stats.doneOnlyCount, 1);
});

test('deriveTaskBoardState prefers the newest plan for the same path', () => {
  const state = deriveTaskBoardState({
    oldReady: viewTask({
      threadId: 'old-ready',
      taskId: 'old-task',
      name: 'Show',
      fullPath: '/media/Show',
      createdAt: 100,
      status: 'audit_completed',
      resultSummary: '7 actions',
      plan: { summary: { actions: 7, blocked: 0 } },
      posterPath: 'poster.jpg',
    }),
    newBlocked: viewTask({
      threadId: 'new-blocked',
      taskId: 'new-task',
      name: 'Show',
      fullPath: '/media/Show',
      createdAt: 200,
      status: 'audit_completed',
      resultSummary: '1 blockers · 10 actions',
      plan: {
        summary: { actions: 10, blocked: 1 },
        review: {
          required: true,
          reasons: [{ code: 'duplicate_episode_files', episode: 'S01E01' }],
        },
      },
    }),
  }, { field: 'time', direction: 'desc' }, 'all');

  const task = state.allVisibleTasks[0];
  assert.equal(task.taskId, 'new-task');
  assert.equal(task.plan?.summary?.blocked, 1);
  assert.equal(task.resultSummary, '1 blockers · 10 actions');
  assert.equal(task.posterPath, 'poster.jpg');
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

test('clearTaskHistoryItems removes only finished historical task cards', () => {
  const tasks = {
    done: { threadId: 'done', createdAt: 0, name: 'Done', status: 'completed', step: '', lastLog: '', logs: [], isExpanded: false },
    failed: { threadId: 'failed', createdAt: 0, name: 'Failed', status: 'failed', step: '', lastLog: '', logs: [], isExpanded: false },
    stopped: { threadId: 'stopped', createdAt: 0, name: 'Stopped', status: 'stopped', step: '', lastLog: '', logs: [], isExpanded: false },
    audit: { threadId: 'audit', createdAt: 0, name: 'Audit', status: 'audit_completed', step: '', lastLog: '', logs: [], isExpanded: false },
    running: { threadId: 'running', createdAt: 0, name: 'Running', status: 'processing', step: '', lastLog: '', logs: [], isExpanded: false },
  } as const;

  assert.deepEqual(Object.keys(clearTaskHistoryItems(tasks)).sort(), ['audit', 'running']);
});

test('clearTaskHistoryItems follows the backend removal decision when supplied', () => {
  const tasks = {
    removable: {
      threadId: 'removable:item',
      taskId: 'removable',
      createdAt: 0,
      name: 'Done',
      status: 'completed',
      step: '',
      lastLog: '',
      logs: [],
      isExpanded: false,
    },
    protected: {
      threadId: 'protected:item',
      taskId: 'protected',
      createdAt: 0,
      name: 'Rollback ready',
      status: 'completed',
      step: '',
      lastLog: '',
      logs: [],
      isExpanded: false,
      rollbackAvailable: true,
    },
  } as const;

  assert.deepEqual(
    Object.keys(clearTaskHistoryItems(tasks, ['removable'])),
    ['protected'],
  );
});
