
# Media Metadata Scraper

**Media Metadata Scraper** is a powerful, autonomous tool for standardizing media libraries.
**Media Metadata Scraper** 是一个强大的自动化媒体库整理工具，支持智能化元数据获取与重命名。

[🇺🇸 English](#english) | [🇨🇳 中文指南](#中文指南)

---

<a id="english"></a>

## English

### Features
- 🧠 **Smart Detection**: Automatically distinguishes between Movies and TV Shows.
- 🔍 **Robust Search**: Uses TMDB as primary source, with Tavily AI fallbacks for hard-to-find content.
- 🈯 **Localization**: AI-powered translation for metadata (Optional).
- 📂 **Organization**: Renames files and reorganizes directories (In-place or Copy).
- 🖼️ **Artwork**: Downloads Posters, Fanart, Logos, and Actor images.

### Structure
```
media-metadata-scraper/
├── config/             # Configuration files
├── logs/               # Runtime logs
├── src/                # Source code
├── .env                # API Keys (Create from .env.example)
├── main.py             # Entry point
└── requirements.txt    # Dependencies
```

### Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Secrets**:
   Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   # Edit .env:
   # TMDB_API_KEY=...
   ```

3. **Configure Settings** (Optional):
   Modify `config/config.yaml` for proxies, language preferences, etc.

### Usage

#### 1. Process a Single Directory (Single Mode)
**Best for**: A specific movie folder or a single TV show folder (e.g., `Inception (2010)` or `Breaking Bad`).
```bash
# Basic usage
python main.py single /path/to/media/Inception

# If path contains spaces, use quotes!
python main.py single "/path/to/My TV Show"

# Force specific TMDB ID (if search fails)
python main.py single "/path/to/Show" --tmdb-id 27205
```

#### 2. Process Multiple Directories (Batch Mode)
**Best for**: A library root folder containing many subfolders (e.g., `Movies/` or `TV Shows/`).
*Note: Do NOT use this on a single show folder, or it might mistake Season folders for different shows.*
```bash
python main.py batch /path/to/media_library --workers 8
```

#### Options
- `--dry-run`: Preview changes without applying them (Highly Recommended for first run).
- `--inplace`: **Rename files and folders directly in the source.**
- `--copy`: Copy files to Output Directory instead of renaming in-place.
- `--output /path/to/output`: Specify output directory.
- `--no-confirm`: Skip confirmation prompts.
- `--use-local-nfo`: Parse existing NFO files for TMDB ID to skip search.
- `--extra-images`: Download extended artwork (posters/backdrops/logos).

---

<a id="中文指南"></a>

## 中文指南

### 功能特性
- 🧠 **智能检测**: 自动区分电影和电视剧。
- 🔍 **强力搜索**: 以 TMDB 为主数据源，利用 AI (Tavily) 解决搜索难题。
- 🈯 **本地化**: 支持通过 LLM 将元数据翻译为中文（可选）。
- 📂 **自动化整理**: 标准化重命名文件和目录（支持原地修改或复制）。
- 🖼️ **刮削增强**: 自动下载海报、背景图、Logo 以及演员头像。

### 目录结构
```
media-metadata-scraper/
├── config/             # 配置文件
├── logs/               # 运行日志
├── src/                # 源代码
├── .env                # API 密钥 (从 .env.example 复制)
├── main.py             # 程序入口
└── requirements.txt    # 依赖库
```

### 安装配置

1. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```

2. **配置密钥**:
   复制 `.env.example` 为 `.env` 并填入您的 API Key：
   ```bash
   cp .env.example .env
   # 编辑 .env:
   # TMDB_API_KEY=...
   ```

3. **系统设置** (可选):
   修改 `config/config.yaml` 来配置代理、语言偏好等。

### 使用方法

#### 1. 处理单个目录 (Single 模式)
**适用于**: 单独的一部电影文件夹或一部剧集文件夹（例如 `盗梦空间` 或 `绝命毒师`）。
```bash
# 基本用法
python main.py single /path/to/media/Inception

# 如果路径包含空格，请务必加上引号！
python main.py single "/path/to/My TV Show"

# 强制指定 TMDB ID (如果搜索不准)
python main.py single "/path/to/Show" --tmdb-id 27205
```

#### 2. 批量处理 (Batch 模式)
**适用于**: 包含多个子文件夹的媒体库根目录（例如 `Movies/` 或 `TV Shows/`）。
*注意：请勿在单部剧集文件夹上使用此模式，否则可能会错误地将 `Season` 文件夹识别为别的剧。*
```bash
python main.py batch /path/to/media_library --workers 8
```

#### 常用选项
- `--dry-run`: 仅预览变更，不实际修改文件（**强烈推荐**首次运行时开启）。
- `--inplace`: **直接在原目录原地重命名及整理**。
- `--copy`: 将文件**复制**到输出目录，而不是原地重命名。
- `--output /path/to/output`: 指定输出目录。
- `--no-confirm`: 跳过确认提示（适用于无人值守脚本）。
- `--use-local-nfo`: 优先读取目录下已有的 NFO 文件中的 TMDB ID，跳过搜索步骤（适用于已刮削过的库）。
- `--extra-images`: 下载额外的图片资源（多张海报、Logo、背景图）。

## License
MIT
