import type { ExecutionPlan, MatchExplanation, MetadataRecord, PlanSummary, TaskEvent, TaskSnapshot, TaskStartPayload } from './types';

export type TaskStatus = 'idle' | 'searching' | 'fetching' | 'processing' | 'verifying' | 'completed' | 'partial' | 'failed' | 'dry_run' | 'audit_completed' | 'stopped' | 'quarantined' | 'cancel_requested' | 'cancelled';

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
  planDigest?: string;
  planSummary?: PlanSummary;
  match?: MatchExplanation;
  artwork?: MetadataRecord;
  verification?: MetadataRecord;
  nfoOutputs?: MetadataRecord[];
  issue?: MetadataRecord;
  lock?: MetadataRecord;
  taskSummary?: MetadataRecord;
  rollback?: MetadataRecord;
  recovery?: MetadataRecord;
  planConfirmation?: MetadataRecord;
  rollbackRiskCount?: number;
  rollbackAvailable?: boolean;
  outputPath?: string;
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

export interface PlanReviewItem {
  code: string;
  message: string;
  guidance: string;
  episode?: string;
  source?: string;
  destination?: string;
  sources: string[];
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
  conflictStrategy?: 'error' | 'skip' | 'suffix' | 'overwrite';
  operationScope?: 'full' | 'nfo_only' | 'artwork_only' | 'organize_only';
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

export const rollbackRiskCount = (rollback?: MetadataRecord) => {
  const warningStatuses = new Set(['missing_destination', 'dir_not_empty', 'missing_backup', 'current_modified', 'failed', 'error']);
  const operations = Array.isArray(rollback?.operations) ? rollback.operations : [];
  return operations.reduce((count, item) => {
    const operation = asRecord(item);
    const status = asString(operation.status);
    return warningStatuses.has(status || '') ? count + 1 : count;
  }, 0);
};

export const rollbackResultPresentation = (rollback?: MetadataRecord) => {
  const status = asString(rollback?.status) || 'failed';
  const riskCount = rollbackRiskCount(rollback);
  if (status === 'running') {
    return { status, completed: false, retryable: false, riskCount, step: 'Rolling back', summary: 'Rollback in progress' };
  }
  if (status === 'completed') {
    return { status, completed: true, retryable: false, riskCount, step: 'Rolled back', summary: '已回滚' };
  }
  if (status === 'partial') {
    return {
      status,
      completed: false,
      retryable: true,
      riskCount,
      step: 'Rollback needs review',
      summary: riskCount > 0 ? `回滚需复核 · ${riskCount} 项` : '回滚需复核',
    };
  }
  return {
    status,
    completed: false,
    retryable: true,
    riskCount,
    step: 'Rollback failed',
    summary: riskCount > 0 ? `回滚失败 · ${riskCount} 项` : '回滚失败',
  };
};

export const taskOutputPath = (item: MetadataRecord, plan?: ExecutionPlan) => (
  asString(item.output_path)
  || asString(asRecord(item.output).media_dir)
  || asString(plan?.target_root)
  || asString(item.path)
);

export const summarizeManifestOperations = (manifest?: MetadataRecord) => {
  const operations = Array.isArray(manifest?.operations) ? manifest.operations : [];
  const reversibleActions = new Set(['move_file', 'copy_file', 'rename_dir', 'create_file', 'create_dir', 'overwrite_file', 'replace_file']);
  const riskyStatuses = new Set(['missing_destination', 'missing_source', 'source_exists', 'dir_not_empty', 'missing_backup', 'current_modified', 'failed', 'error']);
  const counts = operations.reduce((acc, item) => {
    const operation = asRecord(item);
    const action = asString(operation.action) || 'unknown';
    acc[action] = (acc[action] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const reversible = operations.filter((item) => {
    const operation = asRecord(item);
    const action = asString(operation.action);
    return reversibleActions.has(action || '');
  }).length;
  const review = operations.filter((item) => {
    const operation = asRecord(item);
    const status = asString(operation.status);
    return riskyStatuses.has(status || '');
  }).length;
  const preview = operations.slice(0, 8).map((item) => {
    const operation = asRecord(item);
    return {
      action: asString(operation.action) || 'unknown',
      status: asString(operation.status) || 'recorded',
      source: asString(operation.source),
      destination: asString(operation.destination),
      kind: asString(operation.kind),
    };
  });
  return {
    total: operations.length,
    reversible,
    review,
    counts,
    preview,
    omitted: Math.max(0, operations.length - preview.length),
  };
};

export const summarizePlanPreview = (plan?: ExecutionPlan) => {
  const summary = plan?.summary || {};
  const visibleActions = Array.isArray(plan?.actions) ? plan.actions.length : 0;
  const visibleRisks = Array.isArray(plan?.risks) ? plan.risks.length : 0;
  const visibleConflicts = Array.isArray(plan?.conflicts) ? plan.conflicts.length : 0;
  const totalActions = summary.actions ?? visibleActions;
  const totalRisks = summary.risks ?? visibleRisks;
  const totalConflicts = summary.conflicts ?? visibleConflicts;
  const compact = !!(plan?.compact || plan?.preview_omitted || plan?.full_plan_available);
  const hiddenActions = Math.max(0, totalActions - visibleActions);
  const hiddenRisks = Math.max(0, totalRisks - visibleRisks);
  const hiddenConflicts = Math.max(0, totalConflicts - visibleConflicts);
  return {
    compact,
    fullPlanAvailable: !!plan?.full_plan_available,
    totalActions,
    totalRisks,
    totalConflicts,
    visibleActions,
    visibleRisks,
    visibleConflicts,
    hiddenActions,
    hiddenRisks,
    hiddenConflicts,
    hasHiddenPreview: hiddenActions + hiddenRisks + hiddenConflicts > 0 || !!plan?.preview_omitted,
  };
};

const reviewGuidance = (code: string) => {
  switch (code) {
    case 'duplicate_episode_files':
      return 'Rename the incorrectly numbered video so every episode marker is unique, then generate a new plan.';
    case 'destination_exists':
    case 'planned_destination_collision':
      return 'Inspect the existing destination and choose skip, suffix, or overwrite-with-backup before replanning.';
    case 'episode_not_in_metadata':
      return 'Verify the season and episode marker against the provider entry, then rename the file or choose another match.';
    case 'unparseable_episode_file':
      return 'Add a stable SxxExx episode marker to the filename, then generate a new plan.';
    default:
      return 'Resolve the listed filesystem or naming issue, then generate a new locked plan.';
  }
};

export const planReviewItems = (plan?: ExecutionPlan): PlanReviewItem[] => {
  if (!plan) return [];
  const explicitReview = asRecord(plan.review);
  const explicitReasons = Array.isArray(explicitReview.reasons) ? explicitReview.reasons.map(asRecord) : [];
  const errorRisks = Array.isArray(plan.risks)
    ? plan.risks.map(asRecord).filter((risk) => asString(risk.level) === 'error')
    : [];
  const blockedConflicts = Array.isArray(plan.conflicts)
    ? plan.conflicts.map(asRecord).filter((conflict) => asString(conflict.resolution) === 'blocked')
    : [];
  const blockedActions = Array.isArray(plan.actions)
    ? plan.actions.map(asRecord).filter((action) => asString(action.status) === 'blocked')
    : [];

  const rawItems = explicitReasons.length
    ? explicitReasons
    : [
        ...errorRisks,
        ...blockedConflicts,
        ...blockedActions,
      ];
  const seen = new Set<string>();
  return rawItems.flatMap((item) => {
    const code = asString(item.code) || asString(item.reason) || asString(item.kind) || 'manual_review';
    const episode = asString(item.episode);
    const source = asString(item.source);
    const destination = asString(item.destination);
    const key = code === 'duplicate_episode_files' && episode
      ? [code, episode].join('|')
      : [code, episode, source, destination].join('|');
    if (seen.has(key)) return [];
    seen.add(key);
    const sources = asStringArray(item.sources);
    return [{
      code,
      message: asString(item.message) || `${code.replaceAll('_', ' ')} requires review.`,
      guidance: reviewGuidance(code),
      episode,
      source,
      destination,
      sources: sources.length ? sources : source ? [source] : [],
    }];
  });
};

export const planReviewHeadline = (plan?: ExecutionPlan) => {
  const items = planReviewItems(plan);
  if (items.length === 0) return 'Plan requires review';
  const first = items[0];
  if (first.code === 'duplicate_episode_files' && first.episode) {
    return `${first.episode} is claimed by ${first.sources.length || 2} video files`;
  }
  return first.message;
};

export const rollbackPreviewConfirmationMessage = (preview?: MetadataRecord) => {
  const operationCount = Array.isArray(preview?.operations) ? preview.operations.length : 0;
  const riskCount = rollbackRiskCount(preview);
  return [
    `Rollback preview: ${operationCount} operations will be evaluated.`,
    riskCount ? `${riskCount} operations need review or may be skipped.` : 'No modified-file conflicts detected.',
    'Continue with rollback now?',
  ].join('\n');
};

export const issueFromRecord = (record: MetadataRecord): MetadataRecord | undefined => {
  const error = asString(record.error);
  const result = asString(record.result);
  const status = asString(record.status);
  const reason = asString(record.reason);
  if (!error && !result && !reason && status !== 'failed' && status !== 'partial' && status !== 'stopped' && status !== 'quarantined') return undefined;
  return {
    status,
    error,
    result,
    ...(reason ? { reason } : {}),
    ...(record.parse ? { parse: asOptionalRecord(record.parse) } : {}),
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
    dry_run: true,
    inplace: config.strategy !== 'copy',
    copy_mode: config.strategy === 'copy',
    output_dir: config.strategy === 'copy' ? config.outputPath || null : null,
    fresh: config.forceFresh,
    extra_images: config.extraImages,
    enable_organize: config.enableOrganize,
    overwrite_images: config.overwriteImages,
    rename_parent_dir: config.renameParentDir,
    conflict_strategy: config.conflictStrategy,
    operation_scope: (asString(task.config?.operation_scope) as TaskStartPayload['operation_scope']) || config.operationScope || 'full',
    search_mode: nextSearchMode,
    intended_strategy: config.strategy,
  };
};

export const normalizeTaskStatus = (status?: string): TaskStatus => {
  if (status === 'completed') return 'completed';
  if (status === 'partial') return 'partial';
  if (status === 'failed') return 'failed';
  if (status === 'audit_completed') return 'audit_completed';
  if (status === 'skipped') return 'completed';
  if (status === 'stopped') return 'stopped';
  if (status === 'quarantined') return 'quarantined';
  if (status === 'cancel_requested') return 'cancel_requested';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'fetching') return 'fetching';
  if (status === 'verifying') return 'verifying';
  if (status === 'processing') return 'processing';
  if (status === 'planned') return 'idle';
  return 'idle';
};

export const taskStatusStep = (status: TaskStatus, labels: TaskViewLabels = defaultTaskViewLabels) => {
  if (status === 'processing') return labels.scanning;
  if (status === 'searching') return labels.extendedSearch;
  if (status === 'fetching') return labels.metadataMatch;
  if (status === 'verifying') return 'Verifying outputs';
  if (status === 'completed') return labels.finished;
  if (status === 'partial') return 'Partial';
  if (status === 'failed') return labels.error;
  if (status === 'audit_completed' || status === 'dry_run') return labels.auditComplete;
  if (status === 'stopped') return 'Stopped';
  if (status === 'quarantined') return 'Needs naming';
  if (status === 'cancel_requested') return 'Cancelling';
  if (status === 'cancelled') return 'Cancelled';
  return labels.preparing;
};

export const taskLevelSummary = (snapshot: TaskSnapshot) => {
  const summary = snapshot.summary || {};
  const total = asNumber(summary.total) ?? 0;
  const completed = asNumber(summary.completed) ?? 0;
  const partial = asNumber(summary.partial) ?? 0;
  const failed = asNumber(summary.failed) ?? 0;
  const quarantined = asNumber(summary.quarantined) ?? 0;
  if (snapshot.error) return snapshot.error;
  if (snapshot.status === 'cancel_requested') return 'Cancellation requested';
  if (snapshot.status === 'cancelled') {
    const stage = asString(snapshot.cancel?.stage);
    return stage ? `Cancelled at ${stage}` : 'Cancelled';
  }
  const rollbackStatus = asString(snapshot.rollback?.status);
  if (rollbackStatus) return rollbackResultPresentation(snapshot.rollback).summary;
  if (total > 0) return `${completed}/${total} done${partial ? ` · ${partial} partial` : ''} · ${failed} failed${quarantined ? ` · ${quarantined} quarantined` : ''}`;
  return snapshot.input_dir;
};

export const taskFromSnapshot = (snapshot: TaskSnapshot, labels: TaskViewLabels = defaultTaskViewLabels): TaskViewModel => {
  const status = normalizeTaskStatus(snapshot.status);
  const riskCount = rollbackRiskCount(snapshot.rollback);
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
    recovery: snapshot.recovery,
    rollbackRiskCount: riskCount,
    issue: snapshot.error ? { status: snapshot.status, error: snapshot.error, path: snapshot.input_dir } : undefined,
    rollbackAvailable: !!(snapshot.rollback_available ?? snapshot.config?.enable_organize) && snapshot.rollback?.status !== 'completed',
    outputPath: snapshot.input_dir,
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
  const rollbackPresentation = rollbackResultPresentation(snapshot.rollback);
  const riskCount = rollbackPresentation.riskCount;
  const rollbackSummary = rollbackStatus ? rollbackPresentation.summary : undefined;
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
    planDigest: asString(item.plan_digest),
    planSummary,
    match,
    artwork: asOptionalRecord(item.artwork),
    verification: asOptionalRecord(item.verification),
    nfoOutputs: Array.isArray(item.nfo_outputs) ? item.nfo_outputs.map(asRecord) : [],
    issue: issueFromRecord(item),
    lock: asOptionalRecord(item.lock),
    taskSummary: snapshot.summary,
    rollback: snapshot.rollback,
    recovery: snapshot.recovery,
    planConfirmation: asOptionalRecord(item.plan_confirmation),
    rollbackRiskCount: riskCount,
    rollbackAvailable: !!(snapshot.rollback_available ?? plan?.rollback_available ?? snapshot.config?.enable_organize) && snapshot.rollback?.status !== 'completed',
    outputPath: taskOutputPath(item, plan),
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
    if (['task.completed', 'task.partial', 'task.failed', 'task.stopped', 'task.cancel_requested', 'task.cancelled'].includes(event.type)) {
      const summary = asRecord(payload.summary);
      Object.entries(next).forEach(([key, task]) => {
        if (task.taskId !== event.task_id) return;
        const nextStatus = event.type === 'task.completed'
          ? 'completed'
          : event.type === 'task.partial'
            ? 'partial'
            : event.type === 'task.failed'
              ? 'failed'
              : event.type === 'task.cancel_requested'
                ? 'cancel_requested'
                : event.type === 'task.cancelled'
                  ? 'cancelled'
                  : 'stopped';
        const shouldOverrideItemStatus = ['processing', 'searching', 'fetching', 'verifying', 'idle', 'cancel_requested'].includes(task.status);
        next[key] = {
          ...task,
          status: shouldOverrideItemStatus ? nextStatus : task.status,
          step: shouldOverrideItemStatus ? taskStatusStep(nextStatus, labels) : task.step,
          taskSummary: summary,
          lastLog: asString(payload.error) || task.lastLog,
          resultSummary: summary.total !== undefined
            ? `${asNumber(summary.completed) || 0}/${asNumber(summary.total) || 0} done · ${asNumber(summary.failed) || 0} failed${asNumber(summary.quarantined) ? ` · ${asNumber(summary.quarantined)} quarantined` : ''}`
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

    if (['task.rollback_started', 'task.rollback_completed', 'task.rollback_partial', 'task.rollback_failed'].includes(event.type)) {
      const presentation = rollbackResultPresentation(payload);
      Object.entries(next).forEach(([key, task]) => {
        if (task.taskId === event.task_id) {
          next[key] = {
            ...task,
            rollback: payload,
            rollbackRiskCount: presentation.riskCount,
            rollbackAvailable: presentation.completed ? false : task.rollbackAvailable,
            step: presentation.step,
            resultSummary: presentation.summary,
          };
        }
      });
    }

    if (['task.recovery_started', 'task.recovery_completed', 'task.recovery_failed'].includes(event.type)) {
      Object.entries(next).forEach(([key, task]) => {
        if (task.taskId !== event.task_id) return;
        const recoveryStatus = event.type === 'task.recovery_started'
          ? 'running'
          : event.type === 'task.recovery_completed'
            ? 'restarted'
            : 'failed';
        next[key] = {
          ...task,
          recovery: { ...payload, status: recoveryStatus },
          resultSummary: event.type === 'task.recovery_started'
            ? 'Preparing safe recovery'
            : event.type === 'task.recovery_completed'
              ? `Recovered as ${asString(payload.retry_task_id) || 'new task'}`
              : asString(payload.error) || 'Recovery failed',
        };
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
    verification: asOptionalRecord(payload.verification) || existing.verification,
    nfoOutputs: existing.nfoOutputs || [],
    lock: asOptionalRecord(payload.lock) || existing.lock,
    issue: existing.issue,
    outputPath: taskOutputPath(payload, existing.plan) || existing.outputPath,
    rollbackRiskCount: existing.rollbackRiskCount,
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
    updated.planDigest = asString(payload.plan_digest) || updated.planDigest;
    updated.planSummary = updated.plan?.summary;
    updated.outputPath = taskOutputPath(payload, updated.plan);
    updated.rollbackAvailable = !!(updated.plan?.rollback_available ?? updated.rollbackAvailable);
    updated.resultSummary = formatPlanSummary(updated.planSummary) || updated.resultSummary;
  }
  if (event.type === 'candidate.selected') updated.status = 'fetching';
  if (event.type === 'nfo.written') {
    updated.nfoOutputs = [...(updated.nfoOutputs || []).slice(-99), payload];
    updated.resultSummary = `${updated.nfoOutputs.length} NFO written`;
  }
  if (event.type === 'candidate.selected' && payload.match) {
    updated.match = payload.match as MatchExplanation;
  }
  if (payload.match) {
    updated.match = payload.match as MatchExplanation;
  }
  if (event.type === 'item.lock_acquired') {
    updated.resultSummary = 'Execution lock acquired';
  }
  if (event.type === 'item.verification_started') {
    updated.status = 'verifying';
    updated.resultSummary = 'Verifying filesystem outputs';
  }
  if (event.type === 'item.verification_completed') {
    updated.verification = asOptionalRecord(payload.verification) || payload;
    const verificationStatus = asString(updated.verification.status) || 'unknown';
    updated.resultSummary = `Verification ${verificationStatus}`;
  }
  if (event.type === 'item.audit_completed') {
    updated.status = 'audit_completed';
    updated.hasExecuted = false;
    updated.planSummary = payload.plan_summary as PlanSummary | undefined || updated.planSummary;
    updated.resultSummary = asString(payload.result) || formatPlanSummary(updated.planSummary) || '检测通过/PASS';
  }
  if (event.type === 'item.plan_drifted') {
    updated.planConfirmation = { ...payload, status: 'drifted' };
    updated.hasExecuted = false;
    updated.resultSummary = 'Source changed after audit. Run a new plan.';
  }
  if (event.type === 'item.execution_confirmed' || event.type === 'item.execution_started') {
    updated.planConfirmation = {
      ...payload,
      status: event.type === 'item.execution_started' ? 'executing' : 'confirmed',
    };
    updated.hasExecuted = true;
    updated.resultSummary = event.type === 'item.execution_started'
      ? 'Locked plan is executing'
      : 'Plan confirmed';
  }
  if (event.type === 'item.completed') {
    updated.status = 'completed';
    updated.hasExecuted = true;
    updated.resultSummary = asString(payload.result) || '任务成功';
    updated.artwork = asOptionalRecord(payload.artwork) || updated.artwork;
    updated.planSummary = payload.plan_summary as PlanSummary | undefined || updated.planSummary;
    updated.outputPath = taskOutputPath(payload, updated.plan);
  }
  if (event.type === 'item.partial') {
    updated.status = 'partial';
    updated.hasExecuted = true;
    updated.verification = asOptionalRecord(payload.verification) || updated.verification;
    updated.artwork = asOptionalRecord(payload.artwork) || updated.artwork;
    updated.issue = issueFromRecord({ ...payload, status: 'partial', reason: asString(payload.result) }) || updated.issue;
    updated.resultSummary = asString(payload.result) || 'Execution completed with warnings';
  }
  if (event.type === 'item.skipped') {
    updated.status = 'completed';
    updated.hasExecuted = true;
    updated.resultSummary = '任务成功，元数据已存在';
  }
  if (event.type === 'item.quarantined') {
    updated.status = 'quarantined';
    updated.hasExecuted = false;
    updated.issue = issueFromRecord({ ...payload, status: 'quarantined' });
    updated.resultSummary = asString(payload.reason) || 'Filename needs manual review';
  }
  if (event.type === 'item.cancelled') {
    updated.status = 'cancelled';
    updated.hasExecuted = false;
    updated.resultSummary = `Cancelled${asString(payload.stage) ? ` during ${asString(payload.stage)}` : ''}`;
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
  return task.status === 'failed' || task.status === 'partial' || task.status === 'stopped' || task.status === 'quarantined' || (summary?.blocked || 0) > 0 || (summary?.conflicts || 0) > 0;
};

export const isTaskReady = (task: TaskViewModel) => (
  (task.status === 'audit_completed' || task.status === 'dry_run') && !hasPlanBlockers(task)
);

export const isTaskRunning = (task: TaskViewModel) => ['processing', 'searching', 'fetching', 'cancel_requested'].includes(task.status);

export const isTaskDone = (task: TaskViewModel) => task.status === 'completed';

export const isTaskHistoryClearable = (task: TaskViewModel) => (
  ['completed', 'failed', 'partial', 'stopped', 'quarantined', 'cancelled'].includes(task.status)
);

export const clearTaskHistoryItems = (
  tasks: Record<string, TaskViewModel>,
  removedTaskIds?: Iterable<string>,
) => {
  const removed = removedTaskIds ? new Set(removedTaskIds) : undefined;
  return (
  Object.fromEntries(
    Object.entries(tasks).filter(([, task]) => (
      removed
        ? !removed.has(task.taskId || task.threadId)
        : !isTaskHistoryClearable(task)
    ))
  ) as Record<string, TaskViewModel>
  );
};

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
    const taskIsNewer = (task.createdAt || 0) > (existing.createdAt || 0);
    const sameTimestamp = (task.createdAt || 0) === (existing.createdAt || 0);
    const primary = taskIsNewer || (sameTimestamp && taskQualityScore(task) > taskQualityScore(existing))
      ? task
      : existing;
    const secondary = primary === task ? existing : task;
    acc[key] = {
      ...primary,
      viewKey: key,
      posterPath: primary.posterPath || secondary.posterPath,
      tmdbId: primary.tmdbId || secondary.tmdbId,
      mediaType: primary.mediaType || secondary.mediaType,
    };
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
        quarantined: 0,
        cancel_requested: 1,
        cancelled: 6,
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
  finishedCount: tasks.filter((task) => ['completed', 'partial', 'failed', 'audit_completed', 'dry_run', 'quarantined', 'cancelled'].includes(task.status)).length,
  runningCount: tasks.filter(isTaskRunning).length,
  failedCount: tasks.filter((task) => ['failed', 'partial', 'stopped', 'quarantined'].includes(task.status)).length,
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
