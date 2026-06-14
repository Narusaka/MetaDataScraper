export interface FileSystemItem {
  name: string;
  path: string;
  is_dir: boolean;
  has_children?: boolean;
}

export interface FileSystemResponse {
  current: string;
  items: FileSystemItem[];
}

export interface FileSystemCheckResponse {
  exists: boolean;
  is_dir: boolean;
  path: string;
}

export interface LibraryScanIssue {
  code: string;
  level: 'info' | 'warning' | 'error';
  message: string;
  episode?: string;
  sources?: string[];
}

export interface LibraryScanItem {
  id: string;
  name: string;
  path: string;
  source_root?: string;
  kind: 'directory' | 'loose_files' | 'quarantined';
  status: 'ready' | 'review' | 'quarantined';
  media_type: 'movie' | 'tv';
  parsed_title?: string;
  year?: number;
  parse_confidence?: string;
  parse_reasons: string[];
  tmdb_id?: number;
  local_nfo_type?: 'movie' | 'tv';
  video_count: number;
  subtitle_count: number;
  nfo_count: number;
  episode_count: number;
  artwork: Record<string, number>;
  issues: LibraryScanIssue[];
  sources?: string[];
  truncated: boolean;
}

export interface LibraryScanResponse {
  root: string;
  mode: 'single' | 'batch';
  read_only: boolean;
  truncated: boolean;
  summary: {
    items: number;
    ready: number;
    review: number;
    quarantined: number;
    movies: number;
    tv: number;
    videos: number;
    nfo: number;
    with_tmdb_id: number;
  };
  items: LibraryScanItem[];
}

export interface ConnectivityServiceStatus {
  status?: 'ok' | 'failed' | 'error' | 'skipped' | string;
  code?: number;
  message?: string;
  checked_keys?: number;
}

export interface ConnectivityStatus {
  tmdb?: ConnectivityServiceStatus;
  tavily?: ConnectivityServiceStatus;
  checked_at?: string;
  error?: string;
}

export interface AppConfig {
  _meta?: { revision: number };
  tmdb?: { api_key: string };
  omdb?: { api_key: string };
  tavily?: { api_key: string; api_keys?: string[] };
  model?: {
    base_url: string;
    api_key: string;
    model: string;
    temperature?: number;
  };
  matching?: {
    minimum_title_similarity?: number;
    minimum_token_overlap?: number;
    high_confidence_title_similarity?: number;
    high_confidence_token_overlap?: number;
    localized_title_min_similarity?: number;
    strict_year?: boolean;
  };
  output?: {
    conflict_strategy?: 'error' | 'skip' | 'suffix' | 'overwrite';
    nfo_policy?: {
      profile?: 'universal';
      targets?: Array<'jellyfin' | 'emby' | 'kodi'>;
      include_uniqueid?: boolean;
      include_legacy_tmdbid?: boolean;
      episode_sidecars?: 'present_only';
    };
    image_limit?: {
      posters?: number;
      backdrops?: number;
      logos?: number;
      stills?: number;
      actors?: number;
    };
    artwork_policy?: {
      preferred_languages?: string[];
      min_poster_width?: number;
      min_backdrop_width?: number;
      min_logo_width?: number;
    };
  };
  [key: string]: unknown;
}

export interface SettingsSaveResponse {
  status?: string;
  config?: AppConfig;
  revision?: SettingsRevision | null;
}

export interface SettingsRevision {
  revision: number;
  changed_at: string;
  actor: string;
  changed_paths: string[];
  config_fingerprint: string;
}

export interface SettingsHistoryResponse {
  revisions: SettingsRevision[];
}

export interface TaskStartPayload {
  input_dir: string;
  workers: number;
  dry_run: boolean;
  inplace: boolean;
  copy_mode: boolean;
  output_dir: string | null;
  use_local_nfo: boolean;
  extra_images: boolean;
  media_type: string | null;
  tmdb_id: number | null;
  search_mode: 'smart' | 'tmdb_only' | 'tavily_only';
  enable_fallback: boolean;
  multi_mode: boolean | null;
  fresh: boolean;
  enable_organize: boolean;
  overwrite_images: boolean;
  rename_parent_dir: boolean;
  conflict_strategy?: 'error' | 'skip' | 'suffix' | 'overwrite';
  operation_scope?: 'full' | 'nfo_only' | 'artwork_only' | 'organize_only';
  intended_strategy?: 'audit' | 'organize' | 'copy';
}

export type MetadataRecord = Record<string, unknown>;

export interface MatchExplanation {
  provider?: string | null;
  confidence?: string;
  reason?: string;
  score?: number | null;
  title_similarity?: number;
  token_overlap?: number;
  evidence?: MetadataRecord;
  selected_id?: number;
  external_id?: number;
  selected_title?: string;
  matched_title?: string;
  matched_field?: string;
  target_year?: number;
  review_required?: boolean;
  review_reason?: string;
  candidates?: Array<MetadataRecord>;
}

export interface PlanSummary {
  actions?: number;
  ready?: number;
  blocked?: number;
  skipped?: number;
  resolved_conflicts?: number;
  conflicts?: number;
  risks?: number;
  media_files?: number;
  missing_episodes?: number;
  metadata_writes?: number;
}

export interface ExecutionPlan {
  media_type?: string;
  title?: string;
  year?: number;
  source_path?: string;
  mode?: string;
  operation_scope?: string;
  conflict_strategy?: string;
  rollback_available?: boolean;
  target_root?: string;
  summary?: PlanSummary;
  actions?: Array<MetadataRecord>;
  diagnostics?: Array<MetadataRecord>;
  preflight?: MetadataRecord;
  risks?: Array<MetadataRecord>;
  conflicts?: Array<MetadataRecord>;
  missing_episodes?: string[];
  artwork?: MetadataRecord;
  nfo?: MetadataRecord;
  review?: MetadataRecord;
  compact?: boolean;
  full_plan_available?: boolean;
  preview_omitted?: boolean;
}

export interface TaskEvent {
  task_id: string;
  item_id?: string;
  type: string;
  timestamp: string;
  payload: MetadataRecord;
}

export interface TaskSnapshot {
  id: string;
  status: string;
  input_dir: string;
  created_at: string;
  updated_at?: string;
  config?: MetadataRecord;
  summary?: MetadataRecord;
  rollback?: MetadataRecord;
  recovery?: MetadataRecord;
  cancel?: MetadataRecord;
  interruption?: MetadataRecord;
  error?: string;
  items?: Record<string, MetadataRecord>;
  manifest_summary?: ManifestSummary;
  rollback_available?: boolean;
  rolled_back?: boolean;
}

export interface TaskSnapshotsResponse {
  tasks: TaskSnapshot[];
}

export interface TaskHistoryResponse {
  tasks: TaskSnapshot[];
}

export interface MatchReviewRecord {
  task_id: string;
  task_status?: string;
  task_config?: MetadataRecord;
  item_id: string;
  item: MetadataRecord;
}

export interface MatchReviewResponse {
  reviews: MatchReviewRecord[];
}

export interface MatchReviewResolutionResponse {
  status: 'resolved';
  task_id: string;
  item_id: string;
  review: MetadataRecord;
}

export interface SavedMatch {
  id: number;
  normalized_title: string;
  display_title: string;
  year: number;
  media_type: 'movie' | 'tv';
  tmdb_id: number;
  source_task_id?: string;
  source_item_id?: string;
  created_at: string;
  updated_at: string;
  last_used_at?: string;
  use_count: number;
}

export interface SavedMatchesResponse {
  matches: SavedMatch[];
}

export interface RejectedMatch {
  id: number;
  normalized_title: string;
  display_title: string;
  year: number;
  media_type: 'movie' | 'tv';
  tmdb_id: number;
  reason: string;
  source_task_id?: string;
  source_item_id?: string;
  created_at: string;
  updated_at: string;
  last_hit_at?: string;
  hit_count: number;
}

export interface RejectedMatchesResponse {
  rejections: RejectedMatch[];
}

export interface ManifestSummary {
  exists: boolean;
  operation_count: number;
  attempted_count?: number;
  failed_count?: number;
  reversible_count: number;
  action_counts: Record<string, number>;
  created_at?: string;
  updated_at?: string;
  error?: string;
}

export interface ClearTaskHistoryResponse {
  removed: number;
  task_ids: string[];
  retained_count?: number;
  retained?: Array<{
    task_id: string;
    reasons: string[];
  }>;
  plan_cleanup_errors?: Array<{
    task_id: string;
    artifact: string;
    error: string;
  }>;
}

export interface TaskHistoryCleanupPreview {
  eligible_count: number;
  task_ids: string[];
  retained_count: number;
  retained: Array<{
    task_id: string;
    reasons: string[];
  }>;
}

export interface RollbackResponse extends MetadataRecord {
  status?: string;
  preview?: boolean;
  operations?: Array<MetadataRecord>;
}

export interface RecoveryPreviewResponse extends MetadataRecord {
  status: 'ready' | 'manual_review';
  strategy: 'retry' | 'rollback_then_retry' | 'manual_review';
  rollback_required: boolean;
  reason?: string;
  review_count?: number;
  operations?: Array<MetadataRecord>;
}

export interface RecoveryResponse extends MetadataRecord {
  status: 'restarted';
  source_task_id: string;
  task_id: string;
  strategy: 'retry' | 'rollback_then_retry';
  rollback?: RollbackResponse | null;
}

export interface ManifestResponse extends MetadataRecord {
  task_id?: string;
  operations?: Array<MetadataRecord>;
  created_at?: string;
  updated_at?: string;
}

export interface PlanArtifactResponse {
  version?: number;
  generated_at?: string;
  plan_digest?: string;
  artifact_digest?: string;
  integrity_status?: 'verified';
  baseline?: Array<MetadataRecord>;
  plan?: ExecutionPlan;
}

export interface PlanReviewRecord {
  task_id: string;
  task_status?: string;
  task_created_at?: string;
  task_updated_at?: string;
  task_config: MetadataRecord;
  item_id: string;
  review_status: 'ready' | 'blocked' | 'drifted';
  artifact_integrity?: {
    status?: 'verified' | 'invalid' | 'missing';
    code?: string;
    message?: string;
    version?: number;
    artifact_digest?: string;
  };
  settings_drift?: {
    expected_revision?: number;
    current_revision?: number;
    expected_fingerprint?: string;
    current_fingerprint?: string;
  };
  item: MetadataRecord;
}

export interface PlanReviewResponse {
  plans: PlanReviewRecord[];
}

export interface PlanExecutionResponse {
  status: 'started';
  task_id: string;
  source_plan_task_id: string;
  source_plan_item_id: string;
  plan_digest: string;
}

export interface ExecutionTimelineEvent {
  id?: string;
  type: string;
  timestamp: string;
  item_id?: string;
  payload: MetadataRecord;
}

export interface ExecutionProgress {
  total?: number;
  processed?: number;
  completed?: number;
  partial?: number;
  failed?: number;
  cancelled?: number;
  quarantined?: number;
}

export interface ExecutionRecord extends TaskSnapshot {
  phase?: string;
  progress?: ExecutionProgress;
  timeline?: ExecutionTimelineEvent[];
}

export interface ExecutionsResponse {
  executions: ExecutionRecord[];
}

export interface DashboardSummary {
  generated_at: string;
  worker: {
    running: boolean;
    active_task_id?: string | null;
    workers: number;
  };
  queues: {
    match_reviews: number;
    plan_reviews: {
      total: number;
      ready: number;
      blocked: number;
      drifted: number;
    };
    executions: {
      total: number;
      running: number;
      issues: number;
    };
    history: {
      finished: number;
      failed: number;
      rollback_ready: number;
    };
  };
  services: {
    tmdb: { configured: boolean };
    tavily: { configured: boolean };
    model: { configured: boolean };
  };
  stats: {
    total_tasks: number;
    total_media: number;
    total_success: number;
    total_failed: number;
    total_duration: number;
  };
  recent: TaskSnapshot[];
}
