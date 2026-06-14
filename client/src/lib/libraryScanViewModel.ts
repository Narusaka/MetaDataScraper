import type { LibraryScanItem, TaskStartPayload } from './types';

export type LibraryScanFilter = 'all' | 'ready' | 'review' | 'nfo';

export function filterLibraryScanItems(
  items: LibraryScanItem[],
  filter: LibraryScanFilter,
): LibraryScanItem[] {
  if (filter === 'all') return items;
  if (filter === 'nfo') return items.filter(item => item.tmdb_id != null);
  if (filter === 'review') {
    return items.filter(item => item.status === 'review' || item.status === 'quarantined');
  }
  return items.filter(item => item.status === 'ready');
}

export function buildLibraryAuditPayload(
  item: LibraryScanItem,
  useLocalNfo: boolean,
): TaskStartPayload {
  return {
    input_dir: item.path,
    dry_run: true,
    inplace: false,
    copy_mode: false,
    output_dir: null,
    use_local_nfo: useLocalNfo,
    extra_images: false,
    workers: 1,
    media_type: item.media_type,
    tmdb_id: item.tmdb_id ?? null,
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
  };
}
