import assert from 'node:assert/strict';
import test from 'node:test';

import { buildMatchReviewPayload, deriveMatchReviews, toMatchReviewView } from './matchReviewViewModel.ts';
import type { MatchReviewRecord } from './types.ts';

const review: MatchReviewRecord = {
  task_id: 'task-1',
  item_id: '/media/Front Innocent',
  task_config: {
    workers: 4,
    search_mode: 'smart',
    extra_images: true,
    overwrite_images: false,
  },
  item: {
    name: 'Front Innocent',
    path: '/media/Front Innocent',
    error: 'Match requires confirmation before execution',
    error_code: 'MATCH_REVIEW_REQUIRED',
    candidate: { tmdb_id: 42, title: 'Candidate', media_type: 'movie' },
    match: {
      provider: 'tmdb',
      confidence: 'low',
      score: 0.31,
      reason: 'localized title',
      review_required: true,
      candidates: [
        {
          id: 42,
          title: 'Candidate',
          media_type: 'movie',
          year: 2026,
          score: 0.71,
          title_similarity: 0.82,
          token_overlap: 0.75,
          decision: 'selected',
          evidence: {
            hard_blockers: [],
            warnings: [],
            dimensions: {
              year: { status: 'exact' },
              media_type: { status: 'exact' },
              script: { status: 'compatible' },
            },
          },
        },
        { id: 43, title: 'Alternative', media_type: 'movie', year: 2024, score: 0.22, decision: 'low_similarity' },
      ],
    },
    updated_at: '2026-06-06T01:00:00Z',
  },
};

test('match review view exposes candidate evidence and suggested override', () => {
  const view = toMatchReviewView(review);

  assert.equal(view.sourcePath, '/media/Front Innocent');
  assert.equal(view.suggestedTmdbId, 42);
  assert.equal(view.suggestedMediaType, 'movie');
  assert.equal(view.candidates.length, 2);
  assert.equal(view.candidates[1].decision, 'low_similarity');
  assert.equal(view.candidates[0].titleSimilarity, 0.82);
  assert.equal(view.candidates[0].tokenOverlap, 0.75);
  assert.equal(view.candidates[0].yearStatus, 'exact');
  assert.equal(view.candidates[0].mediaTypeStatus, 'exact');
});

test('match review queue supports source and reason search', () => {
  assert.equal(deriveMatchReviews([review], 'front').length, 1);
  assert.equal(deriveMatchReviews([review], 'localized').length, 1);
  assert.equal(deriveMatchReviews([review], 'missing').length, 0);
});

test('match review payload describes audit or organize planning intent', () => {
  const view = toMatchReviewView(review);
  const audit = buildMatchReviewPayload(view, 43, 'movie', false);
  const execute = buildMatchReviewPayload(view, 43, 'movie', true);

  assert.equal(audit.tmdb_id, 43);
  assert.equal(audit.dry_run, true);
  assert.equal(audit.inplace, false);
  assert.equal(audit.enable_organize, false);
  assert.equal(execute.dry_run, true);
  assert.equal(execute.inplace, true);
  assert.equal(execute.enable_organize, true);
  assert.equal(execute.intended_strategy, 'organize');
  assert.equal(execute.extra_images, true);
});
