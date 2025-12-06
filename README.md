# Media Metadata Agent

🧠 Media Metadata Agent (LangGraph)

构建一个 LangGraph 驱动的智能元数据 Agent，支持通过代理访问 TMDB / OMDB 等源，自动获取影视元数据、下载所有图片、生成符合 Infuse / Emby / Jellyfin / Kodi 标准的 .nfo 文件与目录结构。

## 功能特性

- ✅ TMDB + LangGraph 全链路集成
- ✅ OMDB 演员信息补全
- ✅ 全面图片下载 (poster/fanart/banner/backdrop/logo/stills)
- ✅ 中英文双语支持，优先中文输出
- ✅ LLM 驱动的智能翻译
- ✅ Infuse / Emby / Jellyfin / Kodi 标准目录结构
- ✅ XML NFO 文件自动生成

## 安装

1. 克隆项目
```bash
git clone <repository-url>
cd Media-Metadata-Agent
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置 API 密钥
```bash
# 设置环境变量或修改配置文件
export TMDB_API_KEY="d17bc8d9f1f1fa66368b54d95a296235"
export OMDB_API_KEY="http://www.omdbapi.com/?i=tt3896198&apikey=330effac"
```

4. 启动本地 LLM 服务
```bash
# 使用提供的脚本启动 llama-server
./llama_server.sh
```

## 配置

复制示例配置文件：
```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml` 中的 API 密钥和其他设置。

### Google 搜索增强功能（可选）

为了获得更好的谷歌搜索支持，您可以配置 Google Custom Search API：

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 启用 Custom Search JSON API
3. 创建 API 密钥
4. 创建自定义搜索引擎（CSE）
5. 在 `config.yaml` 中配置：

```yaml
google:
  api_key: "您的 Google API 密钥"
  search_engine_id: "您的搜索引擎 ID"
```

配置后重新安装依赖：
```bash
pip install -r requirements.txt
```

如果不配置 Google API，系统将使用网页爬取模式，但可能受 JavaScript 限制。

## 使用

### 命令行界面

```bash
# 处理电影
python -m src.app.cli "初恋时间" --type movie --output ./output

# 处理电视剧
python -m src.app.cli "The Crown" --type tv --tmdb-id 77560 --output ./output

python -m src.app.cli --type tv --tmdb-id 77560 --output ./output --verbose
# 显示详细输出
python -m src.app.cli "Oppenheimer" --verbose
```

### 参数说明

- `query`: 电影/电视剧名称 (可选，如果提供 --tmdb-id 则不需要)
- `--type, -t`: 媒体类型 (movie/tv，默认: movie)
- `--tmdb-id`: TMDB ID (可选，如果提供 query 则不需要)
- `--output, -o`: 输出目录 (默认: ./output)
- `--config, -c`: 配置文件路径
- `--verbose, -v`: 详细输出
- `--aid-search`: 启用谷歌辅助搜索（当 TMDB 搜索无结果时）

**注意**: `query` 和 `--tmdb-id` 至少需要提供一个。

### 高级用法

```bash
# 启用谷歌辅助搜索（当 TMDB 无结果时自动搜索）
python -m src.app.cli "小众电影名" --type movie --aid-search --verbose

# 静默模式（只输出结果）
python -m src.app.cli "电影名" --quiet

# 指定输出目录
python -m src.app.cli "电影名" --output /path/to/output
```

## 输出结构

```
Movies/
└── 初恋时间 (2023)/
    ├── 初恋时间 (2023).nfo
    ├── 初恋时间 (2023).mp4
    └── images/
        ├── poster.jpg
        ├── fanart.jpg
        ├── banner.jpg
        ├── backdrop1.jpg
        ├── backdrop2.jpg
        ├── logo.png
        └── stills/
            ├── 01.jpg
            ├── 02.jpg

TV/
└── 初恋时间 (2023)/
    ├── tvshow.nfo
    ├── images/
    │   ├── poster.jpg
    │   ├── fanart.jpg
    │   ├── banner.jpg
    │   └── backdrop1.jpg
    └── Season 01/
        ├── 初恋时间.S01E01.女仆的秘密.mp4
        ├── 初恋时间.S01E01.女仆的秘密.nfo
        └── images/
            ├── S01E01.jpg
            └── S01E01_banner.jpg
```

## 工作流程

1. **ParseInputNode**: 解析输入参数
2. **SearchNode**: 搜索媒体项目
3. **SelectCandidateNode**: 选择最佳候选
4. **FetchNode**: 获取 TMDB 详细信息
5. **TranslateNode**: LLM 翻译缺失的中文字段
6. **OMDBEnrichNode**: OMDB 演员信息补全
7. **NormalizeNode**: 数据标准化
8. **PlanArtworkNode**: 规划图片下载
9. **DownloadAllImagesNode**: 下载所有图片
10. **LLMMapToNFONode**: LLM 映射到 NFO 格式
11. **ValidateNFONode**: 验证 NFO 数据
12. **RenderXMLNode**: 渲染 XML
13. **WriteOutputNode**: 写入文件
14. **ReportNode**: 生成报告

## API 密钥

- **TMDB API Key**: 从 [TMDB](https://www.themoviedb.org/settings/api) 获取
- **OMDB API Key**: 从 [OMDB](http://www.omdbapi.com/apikey.aspx) 获取

## 语言支持

支持多语言优先级配置：
- zh-CN (简体中文)
- zh-TW (繁体中文)
- en-US (英语)

## 缓存

系统使用本地缓存减少 API 调用，缓存文件存储在 `.cache/` 目录下。

## 开发

### 项目结构

```
src/
  app/
    cli.py          # 命令行接口
    graph.py        # LangGraph 工作流
    state.py        # 状态定义
  adapters/
    tmdb.py         # TMDB API 适配器
    OMDB.py         # OMDB API 适配器
  core/
    schema_internal.py  # 内部数据结构
    schema_nfo.py       # NFO 数据结构
    normalize.py        # 数据标准化
    translator.py       # LLM 翻译
    llm_mapper.py       # LLM 映射
    artwork.py          # 图片下载
    nfo_renderer.py     # XML 渲染
    filesystem.py       # 文件系统操作
    cache.py            # 缓存管理
tests/
  test_graph.py
  test_tmdb_fetch.py
  test_translate.py
config.example.yaml
requirements.txt
README.md
```

### 运行测试

```bash
python -m pytest tests/
```

## 许可证

[MIT License](LICENSE)

## 贡献

欢迎提交 Issue 和 Pull Request！

## 致谢

- [The Movie Database (TMDB)](https://www.themoviedb.org/)
- [OMDB API](http://www.omdbapi.com/)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [Llama.cpp](https://github.com/ggerganov/llama.cpp)
