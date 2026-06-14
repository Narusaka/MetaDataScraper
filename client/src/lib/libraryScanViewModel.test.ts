import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildLibraryAuditPayload,
  filterLibraryScanItems,
} from './libraryScanViewModel.ts';
import type { LibraryScanItem } from './types.ts';

function item(overrides: Partial<LibraryScanItem>): LibraryScanItem {
  return {
    id: 'item',
    name: 'Example',
    path: '/media/Example',
    kind: 'directory',
    status: 'ready',
    media_type: 'movie',
    parse_reasons: [],
    video_count: 1,
    subtitle_count: 0,
    nfo_count: 0,
    episode_count: 0,
    artwork: {},
    issues: [],
    truncated: false,
    ...overrides,
  };
}

test('review filter includes review and quarantined items', () => {
  const items = [
    item({ id: 'ready', status: 'ready' }),
    item({ id: 'review', status: 'review' }),
    item({ id: 'quarantined', status: 'quarantined' }),
  ];

  assert.deepEqual(filterLibraryScanItems(items, 'review').map(entry => entry.id), [
    'review',
    'quarantined',
  ]);
});

test('NFO filter includes items with local TMDB identifiers', () => {
  const items = [
    item({ id: 'without-id' }),
    item({ id: 'with-id', tmdb_id: 123 }),
  ];

  assert.deepEqual(filterLibraryScanItems(items, 'nfo').map(entry => entry.id), ['with-id']);
});

test('audit payload disables file operations and preserves local identity', () => {
  const payload = buildLibraryAuditPayload(
    item({ path: '/media/Show', media_type: 'tv', tmdb_id: 456 }),
    true,
  );

  assert.deepEqual(payload, {
    input_dir: '/media/Show',
    dry_run: true,
    inplace: false,
    copy_mode: false,
    output_dir: null,
    use_local_nfo: true,
    extra_images: false,
    workers: 1,
    media_type: 'tv',
    tmdb_id: 456,
    search_mode: 'smart',
    enable_fallback: true,
    multi_mode: false,
    fresh: false,
    enable_organize: false,
    overwrite_images: false,
    rename_parent_dir: false,
    conflict_strategy: 'error',
    operation_scope: 'full',
    intended_strategy: 'audit',
  });
});
