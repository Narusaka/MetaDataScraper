import type { MatchExplanation, MatchReviewRecord, MetadataRecord, TaskStartPayload } from './types';

const recordValue = (value: unknown): MetadataRecord => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as MetadataRecord : {}
);

const stringValue = (value: unknown) => typeof value === 'string' ? value : undefined;
const numberValue = (value: unknown) => typeof value === 'number' ? value : undefined;

export interface MatchCandidateView {
  id: number;
  title: string;
  mediaType?: 'movie' | 'tv';
  year?: number;
  score?: number;
  titleSimilarity?: number;
  tokenOverlap?: number;
  decision?: string;
  matchedTitle?: string;
  matchedField?: string;
  yearStatus?: string;
  mediaTypeStatus?: string;
  scriptStatus?: string;
  hardBlockers: string[];
  warnings: string[];
}

export interface MatchReviewView {
  taskId: string;
  itemId: string;
  sourcePath: string;
  parsedTitle: string;
  error?: string;
  errorCode?: string;
  match: MatchExplanation;
  candidates: MatchCandidateView[];
  suggestedTmdbId?: number;
  suggestedMediaType: 'movie' | 'tv';
  taskConfig: MetadataRecord;
  updatedAt?: string;
}

export function toMatchReviewView(review: MatchReviewRecord): MatchReviewView {
  const item = recordValue(review.item);
  const candidate = recordValue(item.candidate);
  const match = recordValue(item.match) as MatchExplanation;
  const rawCandidates = Array.isArray(match.candidates) ? match.candidates : [];
  const candidates = rawCandidates.map(recordValue).map((value) => {
    const evidence = recordValue(value.evidence);
    const dimensions = recordValue(evidence.dimensions);
    const yearEvidence = recordValue(dimensions.year);
    const typeEvidence = recordValue(dimensions.media_type);
    const scriptEvidence = recordValue(dimensions.script);
    return {
      id: numberValue(value.id) || 0,
      title: stringValue(value.title) || stringValue(value.matched_title) || `TMDB ${numberValue(value.id) || '?'}`,
      mediaType: value.media_type === 'tv' ? 'tv' as const : value.media_type === 'movie' ? 'movie' as const : undefined,
      year: numberValue(value.year),
      score: numberValue(value.score),
      titleSimilarity: numberValue(value.title_similarity) ?? numberValue(evidence.title_similarity),
      tokenOverlap: numberValue(value.token_overlap) ?? numberValue(evidence.token_overlap),
      decision: stringValue(value.decision),
      matchedTitle: stringValue(value.matched_title),
      matchedField: stringValue(value.matched_field),
      yearStatus: stringValue(yearEvidence.status),
      mediaTypeStatus: stringValue(typeEvidence.status),
      scriptStatus: stringValue(scriptEvidence.status),
      hardBlockers: Array.isArray(evidence.hard_blockers) ? evidence.hard_blockers.map(String) : [],
      warnings: Array.isArray(evidence.warnings) ? evidence.warnings.map(String) : [],
    };
  }).filter(value => value.id > 0);
  const candidateId = numberValue(candidate.tmdb_id) || numberValue(candidate.id);
  if (candidateId && !candidates.some(value => value.id === candidateId)) {
    candidates.unshift({
      id: candidateId,
      title: stringValue(candidate.title) || stringValue(candidate.name) || `TMDB ${candidateId}`,
      mediaType: candidate.media_type === 'tv' ? 'tv' : candidate.media_type === 'movie' ? 'movie' : undefined,
      year: undefined,
      score: typeof match.score === 'number' ? match.score : undefined,
      titleSimilarity: match.title_similarity,
      tokenOverlap: match.token_overlap,
      decision: stringValue(match.reason),
      matchedTitle: match.matched_title,
      matchedField: match.matched_field,
      yearStatus: undefined,
      mediaTypeStatus: undefined,
      scriptStatus: undefined,
      hardBlockers: [],
      warnings: [],
    });
  }
  const mediaType = candidate.media_type === 'tv' || item.media_type === 'tv' ? 'tv' : 'movie';
  return {
    taskId: review.task_id,
    itemId: review.item_id,
    sourcePath: stringValue(item.path) || review.item_id,
    parsedTitle: stringValue(item.query) || stringValue(item.name) || review.item_id.split('/').pop() || 'Unknown media',
    error: stringValue(item.error),
    errorCode: stringValue(item.error_code),
    match,
    candidates,
    suggestedTmdbId: candidateId || numberValue(match.selected_id) || numberValue(match.external_id),
    suggestedMediaType: mediaType,
    taskConfig: review.task_config || {},
    updatedAt: stringValue(item.updated_at) || stringValue(item.created_at),
  };
}

export function deriveMatchReviews(reviews: MatchReviewRecord[], query = '') {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return reviews
    .map(toMatchReviewView)
    .filter(review => !normalizedQuery || [
      review.sourcePath,
      review.parsedTitle,
      review.error,
      review.errorCode,
      review.match.reason,
      review.match.provider,
    ].some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery)))
    .sort((a, b) => Date.parse(b.updatedAt || '') - Date.parse(a.updatedAt || ''));
}

export function buildMatchReviewPayload(
  review: MatchReviewView,
  tmdbId: number,
  mediaType: 'movie' | 'tv',
  execute: boolean,
): Partial<TaskStartPayload> {
  const config = review.taskConfig;
  const searchMode = config.search_mode === 'tmdb_only' || config.search_mode === 'tavily_only'
    ? config.search_mode
    : 'smart';
  return {
    input_dir: review.sourcePath,
    workers: typeof config.workers === 'number' ? config.workers : 1,
    dry_run: true,
    inplace: execute,
    copy_mode: false,
    output_dir: null,
    use_local_nfo: config.use_local_nfo === true,
    extra_images: config.extra_images === true,
    media_type: mediaType,
    tmdb_id: tmdbId,
    search_mode: searchMode,
    enable_fallback: config.enable_fallback !== false,
    multi_mode: false,
    fresh: config.fresh === true,
    enable_organize: execute,
    intended_strategy: execute ? 'organize' : 'audit',
    overwrite_images: config.overwrite_images === true,
    rename_parent_dir: config.rename_parent_dir === true,
    operation_scope: (
      config.operation_scope === 'nfo_only'
      || config.operation_scope === 'artwork_only'
      || config.operation_scope === 'organize_only'
    ) ? config.operation_scope : 'full',
  };
}
