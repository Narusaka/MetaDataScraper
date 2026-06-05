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
}

export type MetadataRecord = Record<string, unknown>;

export interface MatchExplanation {
  provider?: string | null;
  confidence?: string;
  reason?: string;
  score?: number | null;
  token_overlap?: number;
  selected_id?: number;
  external_id?: number;
  selected_title?: string;
  candidates?: Array<MetadataRecord>;
}

export interface PlanSummary {
  actions?: number;
  ready?: number;
  blocked?: number;
  conflicts?: number;
  risks?: number;
  media_files?: number;
  missing_episodes?: number;
  metadata_writes?: number;
}

export interface ExecutionPlan {
  mode?: string;
  rollback_available?: boolean;
  target_root?: string;
  summary?: PlanSummary;
  actions?: Array<MetadataRecord>;
  risks?: Array<MetadataRecord>;
  conflicts?: Array<MetadataRecord>;
  missing_episodes?: string[];
  artwork?: MetadataRecord;
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
  error?: string;
  items?: Record<string, MetadataRecord>;
}

export interface TaskSnapshotsResponse {
  tasks: TaskSnapshot[];
}

export interface RollbackResponse extends MetadataRecord {
  status?: string;
}

export interface PlanArtifactResponse {
  generated_at?: string;
  plan?: ExecutionPlan;
}
