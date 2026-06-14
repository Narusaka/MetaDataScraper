import type { ExecutionPlan, MetadataRecord, PlanReviewRecord, TaskStartPayload } from './types';

export type PlanReviewFilter = 'all' | 'ready' | 'blocked' | 'drifted';

export interface PlanDiagnosticView {
  code: string;
  level: 'info' | 'warning' | 'error';
  message: string;
  context: string;
  guidance: string;
}

const recordValue = (value: unknown): MetadataRecord => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as MetadataRecord : {}
);

const stringValue = (value: unknown) => typeof value === 'string' ? value : '';
const numberValue = (value: unknown) => typeof value === 'number' ? value : undefined;

const diagnosticCodes = new Set([
  'provider_season_fetch_failed',
  'episode_nfo_generation_failed',
  'season_nfo_generation_failed',
]);

const diagnosticGuidance = (code: string) => {
  switch (code) {
    case 'provider_season_fetch_failed':
      return 'Check TMDB connectivity and the selected show ID, then replan so the missing season metadata can be fetched.';
    case 'episode_nfo_generation_failed':
      return 'Inspect the affected episode match and provider payload, correct the filename or match if needed, then generate a new locked plan.';
    case 'season_nfo_generation_failed':
      return 'Verify the affected season exists in the selected TMDB show, then replan before writing metadata.';
    default:
      return 'Inspect the metadata source and affected media, resolve the reported issue, then generate a new locked plan.';
  }
};

const diagnosticContext = (diagnostic: MetadataRecord) => {
  const season = numberValue(diagnostic.season);
  const episode = numberValue(diagnostic.episode);
  if (season !== undefined && episode !== undefined) {
    return `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;
  }
  if (season !== undefined) return `Season ${season}`;
  return stringValue(diagnostic.stage).replaceAll('_', ' ');
};

export function planDiagnostics(plan: ExecutionPlan | MetadataRecord): PlanDiagnosticView[] {
  const explicit = Array.isArray(plan.diagnostics) ? plan.diagnostics.map(recordValue) : [];
  const risks = Array.isArray(plan.risks)
    ? plan.risks.map(recordValue).filter(risk => diagnosticCodes.has(stringValue(risk.code)))
    : [];
  const seen = new Set<string>();

  return [...explicit, ...risks].flatMap((diagnostic) => {
    const code = stringValue(diagnostic.code) || 'metadata_diagnostic';
    const message = stringValue(diagnostic.message) || 'Metadata processing reported an incomplete result.';
    const context = diagnosticContext(diagnostic);
    const key = [code, context, message].join('|');
    if (seen.has(key)) return [];
    seen.add(key);
    const rawLevel = stringValue(diagnostic.level);
    const level = rawLevel === 'error' || rawLevel === 'info' ? rawLevel : 'warning';
    return [{
      code,
      level,
      message,
      context,
      guidance: diagnosticGuidance(code),
    }];
  });
}

export function derivePlanReviews(
  plans: PlanReviewRecord[],
  filter: PlanReviewFilter,
  query = '',
) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return [...plans]
    .filter((record) => {
      if (filter !== 'all' && record.review_status !== filter) return false;
      if (!normalizedQuery) return true;
      const item = recordValue(record.item);
      const plan = recordValue(item.plan);
      const candidate = recordValue(item.candidate);
      const diagnosticTerms = planDiagnostics(plan).flatMap(diagnostic => [
        diagnostic.code,
        diagnostic.message,
        diagnostic.context,
      ]);
      return [
        record.task_id,
        record.item_id,
        item.name,
        item.path,
        plan.title,
        plan.target_root,
        candidate.title,
        candidate.tmdb_id,
        record.settings_drift?.expected_revision,
        record.settings_drift?.current_revision,
        record.settings_drift ? 'settings changed after audit' : '',
        ...diagnosticTerms,
      ].some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery));
    })
    .sort((a, b) => Date.parse(b.task_updated_at || b.task_created_at || '') - Date.parse(a.task_updated_at || a.task_created_at || ''));
}

export function planReviewStats(plans: PlanReviewRecord[]) {
  return plans.reduce((stats, record) => {
    stats.total += 1;
    stats[record.review_status] += 1;
    return stats;
  }, { total: 0, ready: 0, blocked: 0, drifted: 0 });
}

export function planReviewTitle(record: PlanReviewRecord): string {
  const item = recordValue(record.item);
  const plan = recordValue(item.plan);
  const candidate = recordValue(item.candidate);
  return stringValue(plan.title)
    || stringValue(candidate.title)
    || stringValue(item.name)
    || record.item_id.split('/').filter(Boolean).pop()
    || 'Untitled media';
}

export function buildPlanReviewReplanPayload(record: PlanReviewRecord): Partial<TaskStartPayload> {
  const item = recordValue(record.item);
  const candidate = recordValue(item.candidate);
  const config = recordValue(record.task_config);
  const strategy = ['audit', 'organize', 'copy'].includes(stringValue(config.strategy))
    ? stringValue(config.strategy) as TaskStartPayload['intended_strategy']
    : 'audit';
  const searchMode = ['smart', 'tmdb_only', 'tavily_only'].includes(stringValue(config.search_mode))
    ? stringValue(config.search_mode) as TaskStartPayload['search_mode']
    : 'smart';

  return {
    input_dir: stringValue(item.path) || record.item_id,
    dry_run: true,
    inplace: strategy === 'organize',
    copy_mode: strategy === 'copy',
    output_dir: strategy === 'copy' ? stringValue(config.output_dir) || null : null,
    use_local_nfo: config.use_local_nfo === true,
    extra_images: config.extra_images === true,
    workers: typeof config.workers === 'number' ? config.workers : 1,
    media_type: stringValue(candidate.media_type) || stringValue(item.media_type) || null,
    tmdb_id: typeof candidate.tmdb_id === 'number'
      ? candidate.tmdb_id
      : typeof item.tmdb_id === 'number'
        ? item.tmdb_id
        : null,
    search_mode: searchMode,
    enable_fallback: config.enable_fallback !== false,
    multi_mode: false,
    fresh: config.fresh === true,
    enable_organize: config.enable_organize === true,
    overwrite_images: config.overwrite_images === true,
    rename_parent_dir: config.rename_parent_dir === true,
    conflict_strategy: ['error', 'skip', 'suffix', 'overwrite'].includes(stringValue(config.conflict_strategy))
      ? stringValue(config.conflict_strategy) as TaskStartPayload['conflict_strategy']
      : 'error',
    operation_scope: ['full', 'nfo_only', 'artwork_only', 'organize_only'].includes(stringValue(config.operation_scope))
      ? stringValue(config.operation_scope) as TaskStartPayload['operation_scope']
      : 'full',
    intended_strategy: strategy,
  };
}
