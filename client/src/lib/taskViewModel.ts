import type { ExecutionPlan, MatchExplanation, MetadataRecord, PlanSummary, TaskEvent, TaskSnapshot, TaskStartPayload } from './types';

export type TaskStatus = 'idle' | 'searching' | 'fetching' | 'processing' | 'completed' | 'partial' | 'failed' | 'dry_run' | 'audit_completed' | 'stopped';

export interface TaskViewModel {
  viewKey?: string;
  taskId?: string;
  threadId: string;
  createdAt: number;
  name: string;
  tmdbId?: string;
  mediaType?: string;
  fullPath?: string;
  posterPath?: string;
  status: TaskStatus;
  step: string;
  lastLog: string;
  logs: string[];
  isExpanded: boolean;
  hasExecuted?: boolean;
  resultSummary?: string;
  plan?: ExecutionPlan;
  planPath?: string;
  planSummary?: PlanSummary;
  match?: MatchExplanation;
  artwork?: MetadataRecord;
  issue?: MetadataRecord;
  lock?: MetadataRecord;
  taskSummary?: MetadataRecord;
  rollback?: MetadataRecord;
  rollbackAvailable?: boolean;
  config?: MetadataRecord;
}

export interface TaskViewLabels {
  scanning: string;
  extendedSearch: string;
  metadataMatch: string;
  finished: string;
  error: string;
  auditComplete: string;
  preparing: string;
  initializing: string;
}

export type TaskFilter = 'focus' | 'ready' | 'issues' | 'done' | 'all';

export interface TaskSortConfig {
  field: 'time' | 'name' | 'status';
  direction: 'desc' | 'asc';
}

export interface TaskBoardStats {
  finishedCount: number;
  runningCount: number;
  failedCount: number;
  plannedCount: number;
  readyCount: number;
  issueCount: number;
  doneOnlyCount: number;
}

export interface TaskBoardDerivedState {
  allVisibleTasks: TaskViewModel[];
  filteredTasks: TaskViewModel[];
  stats: TaskBoardStats;
}

export interface TaskExecutionConfig {
  strategy: 'audit' | 'organize' | 'copy';
  outputPath?: string;
  searchMode?: 'smart' | 'tmdb_only' | 'tavily_only';
  forceFresh?: boolean;
  extraImages?: boolean;
  enableOrganize?: boolean;
  overwriteImages?: boolean;
  renameParentDir?: boolean;
}

export const defaultTaskViewLabels: TaskViewLabels = {
  scanning: 'Scanning',
  extendedSearch: 'Extended search',
  metadataMatch: 'Metadata match',
  finished: 'Finished',
  error: 'Error',
  auditComplete: 'Audit complete',
  preparing: 'Preparing',
  initializing: 'Initializing',
};

export const asRecord = (value: unknown): MetadataRecord => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as MetadataRecord : {}
);

export const asOptionalRecord = (value: unknown): MetadataRecord | undefined => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as MetadataRecord : undefined
);

export const asString = (value: unknown): string | undefined => (
  typeof value === 'string' ? value : undefined
);

export const asNumber = (value: unknown): number | undefined => (
  typeof value === 'number' ? value : undefined
);

export const asStringArray = (value: unknown): string[] => (
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
);

export const formatPlanSummary = (summary?: PlanSummary) => {
  if (!summary) return undefined;
  const conflicts = summary.conflicts || 0;
  const blocked = summary.blocked || 0;
  const risks = summary.risks || 0;
  if (conflicts > 0 || blocked > 0) return `${conflicts} conflicts · ${blocked} blocked`;
  if (risks > 0) return `${summary.actions || 0} actions · ${risks} risks`;
  return `${summary.actions || 0} actions · ${summary.metadata_writes || 0} metadata`;
};

export const issueFromRecord = (record: MetadataRecord): MetadataRecord | undefined => {
  const error = asString(record.error);
  const result = asString(record.result);
  const status = asString(record.status);
  if (!error && !result && status !== 'failed' && status !== 'partial' && status !== 'stopped') return undefined;
  return {
    status,
    error,
    result,
    path: asString(record.path),
    name: asString(record.name) || asString(record.title),
  };
};

export const posterUrl = (poster?: string) => {
  if (!poster) return undefined;
  if (poster.startsWith('http')) return poster;
  return `https://image.tmdb.org/t/p/w200${poster}`;
};

export const getTaskViewKey = (task: TaskViewModel) => (
  task.viewKey || task.fullPath || task.threadId || `${task.mediaType || 'media'}:${task.tmdbId || task.name}`
);

export const buildTaskStartPayload = (
  task: TaskViewModel,
  config: TaskExecutionConfig,
  overrides: Partial<Pick<TaskViewModel, 'tmdbId' | 'mediaType'>> = {},
): Partial<TaskStartPayload> => {
  const nextTmdbId = overrides.tmdbId ?? task.tmdbId;
  const configuredSearchMode = asString(task.config?.search_mode);
  const nextSearchMode = configuredSearchMode === 'smart' || configuredSearchMode === 'tmdb_only' || configuredSearchMode === 'tavily_only'
    ? configuredSearchMode
    : config.searchMode || 'smart';

  return {
    input_dir: task.fullPath || '',
    tmdb_id: nextTmdbId ? parseInt(nextTmdbId) : null,
    media_type: overrides.mediaType ?? task.mediaType ?? null,
    dry_run: false,
    inplace: config.strategy !== 'copy',
    copy_mode: config.strategy === 'copy',
    output_dir: config.strategy === 'copy' ? config.outputPath || null : null,
    fresh: config.forceFresh,
    extra_images: config.extraImages,
    enable_organize: config.enableOrganize,
    overwrite_images: config.overwriteImages,
    rename_parent_dir: config.renameParentDir,
    search_mode: nextSearchMode,
  };
};

export const normalizeTaskStatus = (status?: string): TaskStatus => {
  if (status === 'completed') return 'completed';
  if (status === 'partial') return 'partial';
  if (status === 'failed') return 'failed';
  if (status === 'audit_completed') return 'audit_completed';
  if (status === 'skipped') return 'completed';
  if (status === 'stopped') return 'stopped';
  if (status === 'fetching') return 'fetching';
  if (status === 'processing') return 'processing';
  if (status === 'planned') return 'idle';
  return 'idle';
};

export const taskStatusStep = (status: TaskStatus, labels: TaskViewLabels = defaultTaskViewLabels) => {
  if (status === 'processing') return labels.scanning;
  if (status === 'searching') return labels.extendedSearch;
  if (status === 'fetching') return labels.metadataMatch;
  if (status === 'completed') return labels.finished;
  if (status === 'partial') return 'Partial';
  if (status === 'failed') return labels.error;
  if (status === 'audit_completed' || status === 'dry_run') return labels.auditComplete;
  if (status === 'stopped') return 'Stopped';
  return labels.preparing;
};

export const taskLevelSummary = (snapshot: TaskSnapshot) => {
  const summary = snapshot.summary || {};
  const total = asNumber(summary.total) ?? 0;
  const completed = asNumber(summary.completed) ?? 0;
  const failed = asNumber(summary.failed) ?? 0;
  if (snapshot.error) return snapshot.error;
  const rollbackStatus = asString(snapshot.rollback?.status);
  if (rollbackStatus) return rollbackStatus === 'completed' ? '已回滚' : `回滚${rollbackStatus}`;
  if (total > 0) return `${completed}/${total} done · ${failed} failed`;
  return snapshot.input_dir;
};

export const taskFromSnapshot = (snapshot: TaskSnapshot, labels: TaskViewLabels = defaultTaskViewLabels): TaskViewModel => {
  const status = normalizeTaskStatus(snapshot.status);
  return {
    viewKey: snapshot.input_dir || snapshot.id,
    threadId: snapshot.id,
    taskId: snapshot.id,
    createdAt: Date.parse(snapshot.created_at),
    name: snapshot.input_dir.split('/').pop() || snapshot.input_dir || labels.initializing,
    fullPath: snapshot.input_dir,
    status,
    step: taskStatusStep(status, labels),
    lastLog: snapshot.error || '',
    logs: [],
    isExpanded: false,
    hasExecuted: status === 'completed',
    resultSummary: taskLevelSummary(snapshot),
    taskSummary: snapshot.summary,
    rollback: snapshot.rollback,
    issue: snapshot.error ? { status: snapshot.status, error: snapshot.error, path: snapshot.input_dir } : undefined,
    rollbackAvailable: !!snapshot.config?.enable_organize,
    config: snapshot.config,
  };
};

export const taskFromSnapshotItem = (
  snapshot: TaskSnapshot,
  itemId: string,
  item: MetadataRecord,
  labels: TaskViewLabels = defaultTaskViewLabels,
): TaskViewModel => {
  const candidate = asRecord(item.candidate);
  const plan = item.plan as ExecutionPlan | undefined;
  const match = item.match as MatchExplanation | undefined;
  const planSummary = item.plan_summary as PlanSummary | undefined || plan?.summary;
  const status = normalizeTaskStatus(asString(item.status));
  const name = asString(candidate.title) || asString(item.name) || itemId.split('/').pop() || labels.initializing;
  const poster = posterUrl(asString(candidate.poster_url) || asString(candidate.poster_path) || asString(item.poster_path));
  const rollbackStatus = asString(snapshot.rollback?.status);
  const rollbackSummary = rollbackStatus ? (rollbackStatus === 'completed' ? '已回滚' : `回滚${rollbackStatus}`) : undefined;
  return {
    viewKey: asString(item.path) || itemId,
    threadId: itemId,
    taskId: snapshot.id,
    createdAt: asString(item.created_at) ? Date.parse(asString(item.created_at) as string) : Date.parse(snapshot.created_at),
    name,
    tmdbId: candidate.tmdb_id ? String(candidate.tmdb_id) : (item.tmdb_id ? String(item.tmdb_id) : undefined),
    mediaType: asString(candidate.media_type) || asString(item.media_type),
    fullPath: asString(item.path) || itemId,
    posterPath: poster,
    status,
    step: taskStatusStep(status, labels),
    lastLog: asString(item.error) || asString(item.result) || '',
    logs: asStringArray(item.logs),
    isExpanded: false,
    hasExecuted: status === 'completed',
    resultSummary: rollbackSummary || asString(item.error) || asString(item.result) || formatPlanSummary(planSummary),
    plan,
    planPath: asString(item.plan_path),
    planSummary,
    match,
    artwork: asOptionalRecord(item.artwork),
    issue: issueFromRecord(item),
    lock: asOptionalRecord(item.lock),
    taskSummary: snapshot.summary,
    rollback: snapshot.rollback,
    rollbackAvailable: !!(plan?.rollback_available ?? snapshot.config?.enable_organize),
    config: snapshot.config,
  };
};

export const applyTaskEvent = (
  tasks: Record<string, TaskViewModel>,
  event: TaskEvent,
  labels: TaskViewLabels = defaultTaskViewLabels,
): Record<string, TaskViewModel> => {
  const payload = event.payload || {};
  const next = { ...tasks };

  if (!event.item_id) {
    if (['task.completed', 'task.partial', 'task.failed', 'task.stopped'].includes(event.type)) {
      const summary = asRecord(payload.summary);
      Object.entries(next).forEach(([key, task]) => {
        if (task.taskId !== event.task_id) return;
        const nextStatus = event.type === 'task.completed'
          ? 'completed'
          : event.type === 'task.partial'
            ? 'partial'
            : event.type === 'task.failed'
              ? 'failed'
              : 'stopped';
        const shouldOverrideItemStatus = ['processing', 'searching', 'fetching', 'idle'].includes(task.status);
        next[key] = {
          ...task,
          status: shouldOverrideItemStatus ? nextStatus : task.status,
          step: shouldOverrideItemStatus ? taskStatusStep(nextStatus, labels) : task.step,
          taskSummary: summary,
          lastLog: asString(payload.error) || task.lastLog,
          resultSummary: summary.total !== undefined
            ? `${asNumber(summary.completed) || 0}/${asNumber(summary.total) || 0} done · ${asNumber(summary.failed) || 0} failed`
            : (asString(payload.error) || task.resultSummary),
        };
      });
    }

    if (event.type === 'task.stopped') {
      Object.entries(next).forEach(([key, task]) => {
        if (task.taskId === event.task_id && ['processing', 'searching', 'fetching'].includes(task.status)) {
          next[key] = { ...task, status: 'stopped', step: 'Stopped', lastLog: 'Task stopped' };
        }
      });
    }

    if (event.type === 'task.rollback_completed') {
      Object.entries(next).forEach(([key, task]) => {
        if (task.taskId === event.task_id) {
          next[key] = {
            ...task,
            rollback: payload,
            status: 'stopped',
            step: 'Rolled back',
            resultSummary: asString(payload.status) === 'completed' ? '已回滚' : `回滚${asString(payload.status) || 'partial'}`,
          };
        }
      });
    }

    return next;
  }

  const key = event.item_id;
  const existing = next[key] || {
    viewKey: asString(payload.path) || key,
    threadId: key,
    taskId: event.task_id,
    createdAt: Date.parse(event.timestamp),
    name: asString(payload.name) || key.split('/').pop() || labels.initializing,
    status: 'idle',
    step: labels.preparing,
    lastLog: '',
    logs: [],
    isExpanded: false,
    fullPath: asString(payload.path) || key,
  } as TaskViewModel;

  const updated: TaskViewModel = {
    ...existing,
    taskId: event.task_id,
    viewKey: asString(payload.path) || existing.viewKey || key,
    name: asString(payload.title) || asString(payload.name) || existing.name,
    fullPath: asString(payload.path) || existing.fullPath || key,
    mediaType: asString(payload.media_type) || existing.mediaType,
    tmdbId: payload.tmdb_id ? String(payload.tmdb_id) : existing.tmdbId,
    posterPath: posterUrl(asString(payload.poster_url) || asString(payload.poster_path)) || existing.posterPath,
    lastLog: asString(payload.error) || asString(payload.result) || existing.lastLog,
    logs: [...existing.logs.slice(-50), `${event.type}: ${asString(payload.error) || asString(payload.result) || asString(payload.name) || asString(payload.title) || ''}`],
    plan: existing.plan,
    planPath: existing.planPath,
    planSummary: existing.planSummary,
    match: existing.match,
    artwork: asOptionalRecord(payload.artwork) || existing.artwork,
    lock: asOptionalRecord(payload.lock) || existing.lock,
    issue: existing.issue,
  };

  if (event.type === 'item.started') updated.status = 'processing';
  if (event.type === 'item.planned') {
    updated.status = 'idle';
    const fileCount = asNumber(payload.video_count) || asNumber(payload.file_count);
    updated.resultSummary = fileCount ? `${fileCount} files` : undefined;
  }
  if (event.type === 'item.plan_ready') {
    updated.plan = (asOptionalRecord(payload.plan) || payload) as ExecutionPlan;
    updated.planPath = asString(payload.plan_path) || updated.planPath;
    updated.planSummary = updated.plan?.summary;
    updated.resultSummary = formatPlanSummary(updated.planSummary) || updated.resultSummary;
  }
  if (event.type === 'candidate.selected') updated.status = 'fetching';
  if (event.type === 'candidate.selected' && payload.match) {
    updated.match = payload.match as MatchExplanation;
  }
  if (payload.match) {
    updated.match = payload.match as MatchExplanation;
  }
  if (event.type === 'item.lock_acquired') {
    updated.resultSummary = 'Execution lock acquired';
  }
  if (event.type === 'item.audit_completed') {
    updated.status = 'audit_completed';
    updated.hasExecuted = false;
    updated.planSummary = payload.plan_summary as PlanSummary | undefined || updated.planSummary;
    updated.resultSummary = asString(payload.result) || formatPlanSummary(updated.planSummary) || '检测通过/PASS';
  }
  if (event.type === 'item.completed') {
    updated.status = 'completed';
    updated.hasExecuted = true;
    updated.resultSummary = asString(payload.result) || '任务成功';
    updated.artwork = asOptionalRecord(payload.artwork) || updated.artwork;
    updated.planSummary = payload.plan_summary as PlanSummary | undefined || updated.planSummary;
  }
  if (event.type === 'item.skipped') {
    updated.status = 'completed';
    updated.hasExecuted = true;
    updated.resultSummary = '任务成功，元数据已存在';
  }
  if (event.type === 'item.failed') {
    updated.status = 'failed';
    updated.planSummary = payload.plan_summary as PlanSummary | undefined || updated.planSummary;
    updated.lock = asOptionalRecord(payload.lock) || updated.lock;
    updated.issue = issueFromRecord(payload) || updated.issue;
    updated.resultSummary = asString(payload.error) || '任务失败';
  }

  updated.step = taskStatusStep(updated.status, labels);
  next[key] = updated;
  return next;
};

export const hasPlanBlockers = (task: TaskViewModel) => {
  const summary = task.planSummary || task.plan?.summary;
  return (summary?.blocked || 0) > 0 || (summary?.conflicts || 0) > 0;
};

export const hasTaskIssue = (task: TaskViewModel) => {
  const summary = task.planSummary || task.plan?.summary;
  return task.status === 'failed' || task.status === 'partial' || task.status === 'stopped' || (summary?.blocked || 0) > 0 || (summary?.conflicts || 0) > 0;
};

export const isTaskReady = (task: TaskViewModel) => (
  (task.status === 'audit_completed' || task.status === 'dry_run') && !hasPlanBlockers(task)
);

export const isTaskRunning = (task: TaskViewModel) => ['processing', 'searching', 'fetching'].includes(task.status);

export const isTaskDone = (task: TaskViewModel) => task.status === 'completed';

const taskDedupeKey = (task: TaskViewModel) => (
  getTaskViewKey(task)
);

const taskQualityScore = (candidate: TaskViewModel) => {
  let value = 0;
  if (candidate.fullPath) value += 4;
  if (candidate.tmdbId) value += 3;
  if (candidate.posterPath) value += 2;
  if (candidate.resultSummary) value += 1;
  if (['completed', 'failed', 'audit_completed'].includes(candidate.status)) value += 6;
  if (['processing', 'searching', 'fetching'].includes(candidate.status)) value += 3;
  return value;
};

export const mergeDuplicateTasks = (tasks: Record<string, TaskViewModel>) => (
  Object.values(tasks).reduce((acc, task) => {
    const key = taskDedupeKey(task);
    if (!acc[key]) {
      acc[key] = { ...task, viewKey: key };
      return acc;
    }

    const existing = acc[key];
    if (taskQualityScore(task) > taskQualityScore(existing)) {
      acc[key] = {
        ...task,
        viewKey: key,
        logs: [...task.logs, ...existing.logs].slice(-50),
        posterPath: task.posterPath || existing.posterPath,
        tmdbId: task.tmdbId || existing.tmdbId,
        mediaType: task.mediaType || existing.mediaType,
        resultSummary: task.resultSummary || existing.resultSummary,
      };
    } else {
      acc[key] = {
        ...existing,
        viewKey: key,
        logs: [...existing.logs, ...task.logs].slice(-50),
        posterPath: existing.posterPath || task.posterPath,
        tmdbId: existing.tmdbId || task.tmdbId,
        mediaType: existing.mediaType || task.mediaType,
        resultSummary: existing.resultSummary || task.resultSummary,
      };
    }
    return acc;
  }, {} as Record<string, TaskViewModel>)
);

export const sortTasks = (tasks: TaskViewModel[], sortConfig: TaskSortConfig) => (
  [...tasks].sort((a, b) => {
    const { field, direction } = sortConfig;
    let comparison = 0;

    if (field === 'time') {
      comparison = (a.createdAt || 0) - (b.createdAt || 0);
    } else if (field === 'status') {
      const priority: Record<string, number> = {
        failed: 0,
        partial: 0,
        processing: 1,
        searching: 2,
        fetching: 3,
        dry_run: 4,
        audit_completed: 5,
        completed: 6,
        idle: 7,
      };
      comparison = (priority[a.status] ?? 99) - (priority[b.status] ?? 99);
    } else {
      comparison = (a.name || '').localeCompare(b.name || '');
    }

    return direction === 'asc' ? comparison : -comparison;
  })
);

export const taskBoardStats = (tasks: TaskViewModel[]): TaskBoardStats => ({
  finishedCount: tasks.filter((task) => ['completed', 'partial', 'failed', 'audit_completed', 'dry_run'].includes(task.status)).length,
  runningCount: tasks.filter(isTaskRunning).length,
  failedCount: tasks.filter((task) => ['failed', 'partial', 'stopped'].includes(task.status)).length,
  plannedCount: tasks.filter((task) => task.status === 'idle').length,
  readyCount: tasks.filter(isTaskReady).length,
  issueCount: tasks.filter(hasTaskIssue).length,
  doneOnlyCount: tasks.filter(isTaskDone).length,
});

export const filterTasks = (tasks: TaskViewModel[], taskFilter: TaskFilter) => (
  tasks.filter((task) => {
    if (taskFilter === 'all') return true;
    if (taskFilter === 'ready') return isTaskReady(task);
    if (taskFilter === 'issues') return hasTaskIssue(task);
    if (taskFilter === 'done') return isTaskDone(task);
    return isTaskRunning(task) || isTaskReady(task) || hasTaskIssue(task);
  })
);

export const deriveTaskBoardState = (
  tasks: Record<string, TaskViewModel>,
  sortConfig: TaskSortConfig,
  taskFilter: TaskFilter,
): TaskBoardDerivedState => {
  const merged = mergeDuplicateTasks(tasks);
  const allVisibleTasks = sortTasks(
    Object.values(merged).filter((task) => !(task.status === 'idle' && !task.fullPath)),
    sortConfig,
  );
  return {
    allVisibleTasks,
    filteredTasks: filterTasks(allVisibleTasks, taskFilter),
    stats: taskBoardStats(allVisibleTasks),
  };
};
