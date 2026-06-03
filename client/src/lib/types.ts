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
