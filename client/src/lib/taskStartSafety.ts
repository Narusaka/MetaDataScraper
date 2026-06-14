import type { TaskStartPayload } from './types';

export type StartStrategy = 'audit' | 'organize' | 'copy';

export interface StartSafetyConfig {
  strategy: StartStrategy;
  inputPath: string;
  outputPath?: string;
  extraImages?: boolean;
  overwriteImages?: boolean;
  renameParentDir?: boolean;
  forceFresh?: boolean;
  enableOrganize?: boolean;
  workers?: number;
  searchMode?: TaskStartPayload['search_mode'];
  conflictStrategy?: TaskStartPayload['conflict_strategy'];
  operationScope?: TaskStartPayload['operation_scope'];
}

export const validateStartSafetyConfig = (config: StartSafetyConfig) => {
  const inputPath = config.inputPath.trim();
  const outputPath = (config.outputPath || '').trim();
  if (!inputPath) return 'Target path is required';
  if (config.strategy === 'copy' && !outputPath) return 'Output path is required for copy mode';
  if (config.strategy === 'copy' && outputPath === inputPath) return 'Output path must be different from target path';
  if (config.operationScope === 'organize_only' && config.strategy === 'audit') {
    return 'Files-only scope requires Organize or Copy as the plan target';
  }
  if ((config.operationScope === 'nfo_only' || config.operationScope === 'artwork_only') && config.strategy !== 'audit') {
    return 'NFO-only and artwork-only scopes use the Metadata plan target';
  }
  return null;
};
