import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

export const languageOptions = {
  en: 'English',
  zh: '中文',
} as const;

export type Language = keyof typeof languageOptions;

type TranslationKey =
  | 'audit_result'
  | 'auto'
  | 'back'
  | 'col_actions'
  | 'col_file'
  | 'col_metadata_name'
  | 'col_result'
  | 'col_status'
  | 'col_tmdb_id'
  | 'col_type'
  | 'col_year'
  | 'concurrency'
  | 'dashboard'
  | 'done'
  | 'empty_state_help'
  | 'episodes_details'
  | 'error'
  | 'extended_search'
  | 'finished'
  | 'force_refresh_danger'
  | 'initializing'
  | 'items'
  | 'live_logs'
  | 'loading'
  | 'media_settings'
  | 'metadata_match'
  | 'mission_configuration'
  | 'mission_control'
  | 'modal_title'
  | 'mode_audit'
  | 'mode_batch'
  | 'mode_copy'
  | 'mode_organize'
  | 'mode_single'
  | 'monitoring'
  | 'movie'
  | 'name'
  | 'nav_appearance'
  | 'opt_enable_organize'
  | 'opt_extra_images'
  | 'opt_local_nfo'
  | 'opt_overwrite_images'
  | 'opt_rename_parent'
  | 'optional'
  | 'organizing'
  | 'output_placeholder'
  | 'parameters'
  | 'path_not_found'
  | 'preparing'
  | 'process_mode'
  | 'processed'
  | 'running'
  | 'scanning'
  | 'select_folder'
  | 'settings'
  | 'skipped_exists'
  | 'smart'
  | 'status'
  | 'status_audit_complete'
  | 'status_online'
  | 'status_standby'
  | 'strategy'
  | 'success_rate'
  | 'system_status'
  | 'target_path'
  | 'threads'
  | 'time'
  | 'tmdb_override'
  | 'tmdb_placeholder'
  | 'tv'
  | 'waiting_logs'
  | 'waiting_missions';

type TranslationTable = Record<TranslationKey, string>;

const en: TranslationTable = {
  audit_result: 'Audit Result',
  auto: 'Auto',
  back: 'Back',
  col_actions: 'Actions',
  col_file: 'File',
  col_metadata_name: 'Metadata Name',
  col_result: 'Result',
  col_status: 'Status',
  col_tmdb_id: 'TMDB ID',
  col_type: 'Type',
  col_year: 'Year',
  concurrency: 'Concurrency',
  dashboard: 'Dashboard',
  done: 'Done',
  empty_state_help: 'Start a mission to see detected media and processing results here.',
  episodes_details: 'Episode Details',
  error: 'Error',
  extended_search: 'Extended Search',
  finished: 'Finished',
  force_refresh_danger: 'Force Refresh',
  initializing: 'Initializing',
  items: 'items',
  live_logs: 'Live Logs',
  loading: 'Loading',
  media_settings: 'Media Settings',
  metadata_match: 'Metadata Match',
  mission_configuration: 'Mission Configuration',
  mission_control: 'Mission Control',
  modal_title: 'Select Folder',
  mode_audit: 'Audit',
  mode_batch: 'Batch',
  mode_copy: 'Copy',
  mode_organize: 'Organize',
  mode_single: 'Single',
  monitoring: 'Monitoring',
  movie: 'Movie',
  name: 'Name',
  nav_appearance: 'Appearance',
  opt_enable_organize: 'Enable Organize',
  opt_extra_images: 'Extra Images',
  opt_local_nfo: 'Use Local NFO',
  opt_overwrite_images: 'Overwrite Images',
  opt_rename_parent: 'Rename Parent Dir',
  optional: 'Optional',
  organizing: 'Organizing',
  output_placeholder: '/path/to/output',
  parameters: 'Parameters',
  path_not_found: 'Path not found',
  preparing: 'Preparing',
  process_mode: 'Process Mode',
  processed: 'Processed',
  running: 'Running',
  scanning: 'Scanning',
  select_folder: 'Select folder',
  settings: 'Settings',
  skipped_exists: 'Skipped (Exists)',
  smart: 'Smart',
  status: 'Status',
  status_audit_complete: 'Audit Complete',
  status_online: 'Online',
  status_standby: 'Standby',
  strategy: 'Strategy',
  success_rate: 'Success Rate',
  system_status: 'System Status',
  target_path: 'Target Path',
  threads: 'Threads',
  time: 'Time',
  tmdb_override: 'TMDB Override',
  tmdb_placeholder: 'Optional TMDB ID',
  tv: 'TV',
  waiting_logs: 'Waiting for logs...',
  waiting_missions: 'Waiting for missions',
};

const zh: TranslationTable = {
  audit_result: '审计结果',
  auto: '自动',
  back: '返回',
  col_actions: '操作',
  col_file: '文件',
  col_metadata_name: '元数据名称',
  col_result: '结果',
  col_status: '状态',
  col_tmdb_id: 'TMDB ID',
  col_type: '类型',
  col_year: '年份',
  concurrency: '并发',
  dashboard: '仪表盘',
  done: '完成',
  empty_state_help: '启动任务后，识别到的媒体和处理结果会显示在这里。',
  episodes_details: '剧集详情',
  error: '错误',
  extended_search: '扩展搜索',
  finished: '已完成',
  force_refresh_danger: '强制刷新',
  initializing: '初始化',
  items: '项',
  live_logs: '实时日志',
  loading: '加载中',
  media_settings: '媒体设置',
  metadata_match: '元数据匹配',
  mission_configuration: '任务配置',
  mission_control: '任务控制',
  modal_title: '选择文件夹',
  mode_audit: '审计',
  mode_batch: '批量',
  mode_copy: '复制',
  mode_organize: '整理',
  mode_single: '单个',
  monitoring: '监控',
  movie: '电影',
  name: '名称',
  nav_appearance: '外观',
  opt_enable_organize: '启用整理',
  opt_extra_images: '额外图片',
  opt_local_nfo: '使用本地 NFO',
  opt_overwrite_images: '覆盖图片',
  opt_rename_parent: '重命名父目录',
  optional: '可选',
  organizing: '整理中',
  output_placeholder: '/输出目录',
  parameters: '参数',
  path_not_found: '路径不存在',
  preparing: '准备中',
  process_mode: '处理模式',
  processed: '已处理',
  running: '运行中',
  scanning: '扫描中',
  select_folder: '选择文件夹',
  settings: '设置',
  skipped_exists: '已跳过（存在）',
  smart: '智能',
  status: '状态',
  status_audit_complete: '审计完成',
  status_online: '在线',
  status_standby: '待机',
  strategy: '策略',
  success_rate: '成功率',
  system_status: '系统状态',
  target_path: '目标路径',
  threads: '线程',
  time: '时间',
  tmdb_override: 'TMDB 覆盖',
  tmdb_placeholder: '可选 TMDB ID',
  tv: '电视剧',
  waiting_logs: '等待日志...',
  waiting_missions: '等待任务',
};

const translations: Record<Language, TranslationTable> = { en, zh };

interface LanguageContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: TranslationKey | string) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => {
    const saved = localStorage.getItem('language');
    return saved === 'zh' || saved === 'en' ? saved : 'en';
  });

  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage: (nextLanguage) => {
      localStorage.setItem('language', nextLanguage);
      setLanguageState(nextLanguage);
    },
    t: (key) => translations[language][key as TranslationKey] ?? key,
  }), [language]);

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useTranslation() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useTranslation must be used within LanguageProvider');
  }
  return context;
}
