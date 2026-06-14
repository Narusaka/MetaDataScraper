import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPlanReviewReplanPayload,
  derivePlanReviews,
  planDiagnostics,
  planReviewStats,
  planReviewTitle,
} from './planReviewViewModel.ts';
import type { PlanReviewRecord } from './types.ts';

const record = (overrides: Partial<PlanReviewRecord>): PlanReviewRecord => ({
  task_id: 'task',
  task_updated_at: '2026-06-12T00:00:00Z',
  task_config: { strategy: 'audit', search_mode: 'smart' },
  item_id: '/media/Example',
  review_status: 'ready',
  item: {
    name: 'Example',
    path: '/media/Example',
    media_type: 'movie',
    plan_digest: 'a'.repeat(64),
    plan: { title: 'Example', summary: { actions: 2 } },
  },
  ...overrides,
});

test('plan review derivation filters, searches and sorts', () => {
  const plans = [
    record({ task_id: 'old', task_updated_at: '2026-06-10T00:00:00Z' }),
    record({
      task_id: 'blocked',
      task_updated_at: '2026-06-13T00:00:00Z',
      review_status: 'blocked',
      item: { name: 'Target Show', path: '/media/Target Show' },
    }),
  ];

  assert.deepEqual(derivePlanReviews(plans, 'all').map(entry => entry.task_id), ['blocked', 'old']);
  assert.deepEqual(derivePlanReviews(plans, 'blocked').map(entry => entry.task_id), ['blocked']);
  assert.deepEqual(derivePlanReviews(plans, 'all', 'target').map(entry => entry.task_id), ['blocked']);
});

test('plan review exposes actionable metadata diagnostics and supports diagnostic search', () => {
  const diagnosticPlan = record({
    task_id: 'diagnostic',
    review_status: 'blocked',
    item: {
      name: 'Affected Show',
      path: '/media/Affected Show',
      plan: {
        title: 'Affected Show',
        diagnostics: [{
          code: 'episode_nfo_generation_failed',
          level: 'error',
          message: 'Could not generate episode NFO.',
          stage: 'generate_nfo',
          season: 1,
          episode: 3,
        }],
        risks: [{
          code: 'episode_nfo_generation_failed',
          level: 'error',
          message: 'Could not generate episode NFO.',
          stage: 'generate_nfo',
          season: 1,
          episode: 3,
        }],
      },
    },
  });

  const diagnostics = planDiagnostics(diagnosticPlan.item.plan as Record<string, unknown>);
  assert.equal(diagnostics.length, 1);
  assert.equal(diagnostics[0].context, 'S01E03');
  assert.match(diagnostics[0].guidance, /locked plan/);
  assert.deepEqual(
    derivePlanReviews([diagnosticPlan], 'all', 'episode_nfo_generation_failed').map(entry => entry.task_id),
    ['diagnostic'],
  );
  assert.deepEqual(
    derivePlanReviews([diagnosticPlan], 'all', 'S01E03').map(entry => entry.task_id),
    ['diagnostic'],
  );
});

test('plan review stats and titles use compact plan evidence', () => {
  const plans = [
    record({ review_status: 'ready' }),
    record({ task_id: 'blocked', review_status: 'blocked' }),
    record({ task_id: 'drifted', review_status: 'drifted' }),
  ];

  assert.deepEqual(planReviewStats(plans), { total: 3, ready: 1, blocked: 1, drifted: 1 });
  assert.equal(planReviewTitle(plans[0]), 'Example');
});

test('settings drift remains searchable and counted as drifted', () => {
  const record = {
    task_id: 'audit-settings',
    task_created_at: '2026-06-14T00:00:00Z',
    task_config: {
      settings_revision: 2,
      settings_fingerprint: 'a'.repeat(64),
    },
    item_id: '/media/Movie',
    review_status: 'drifted' as const,
    settings_drift: {
      expected_revision: 2,
      current_revision: 3,
      expected_fingerprint: 'a'.repeat(64),
      current_fingerprint: 'b'.repeat(64),
    },
    item: {
      name: 'Movie',
      plan: { title: 'Movie', summary: { actions: 1 } },
    },
  };

  assert.deepEqual(planReviewStats([record]), {
    total: 1,
    ready: 0,
    blocked: 0,
    drifted: 1,
  });
  assert.equal(derivePlanReviews([record], 'drifted', 'settings changed').length, 1);
  assert.equal(derivePlanReviews([record], 'ready', '').length, 0);
});

test('replan payload preserves audited strategy and match identity', () => {
  const payload = buildPlanReviewReplanPayload(record({
    task_config: {
      strategy: 'copy',
      output_dir: '/library',
      workers: 3,
      operation_scope: 'artwork_only',
      conflict_strategy: 'suffix',
      use_local_nfo: true,
    },
    item: {
      path: '/incoming/Show',
      media_type: 'tv',
      candidate: { tmdb_id: 123, media_type: 'tv' },
    },
  }));

  assert.equal(payload.input_dir, '/incoming/Show');
  assert.equal(payload.tmdb_id, 123);
  assert.equal(payload.media_type, 'tv');
  assert.equal(payload.copy_mode, true);
  assert.equal(payload.output_dir, '/library');
  assert.equal(payload.operation_scope, 'artwork_only');
  assert.equal(payload.conflict_strategy, 'suffix');
  assert.equal(payload.dry_run, true);
});
