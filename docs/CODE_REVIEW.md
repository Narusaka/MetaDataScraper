# Code Review Report: Media Metadata Agent

**Reviewer**: Senior Software Engineer (Simulated)
**Date**: 2026-01-26
**Scope**: Whole Project (Focus on `src/` and `batch_scraper.py`)

---

## 🛑 Critical Issues (必须修复)

### 1. Security: Hardcoded API Keys
在 `src/app/cli.py` (Line 59, 62) 和 `batch_scraper.py` (Line 123, 126) 中发现了硬编码的 TMDB 和 OMDB API Keys。
*   **问题**: 这是一个严重的安全漏洞。将凭证提交到代码库是绝对禁止的。
*   **风险**: 凭证可能被滥用，导致配额耗尽或账户被封禁。
*   **修复**: 移除所有默认 Key。必须强制要求用户通过环境变量 (`TMDB_API_KEY`) 或 `config.yaml` 显式提供。如果没有 Key，程序应该报错退出，而不是使用一个"默认且公开"的 Key。

### 2. Architecture: God Class (`batch_scraper.py`)
`batch_scraper.py` 单文件超过 2000 行，承担了过多的职责：
*   CLI 参数解析
*   文件系统遍历与扫描
*   NFO 解析逻辑
*   业务调度逻辑
*   文件重命名与移动操作
*   **修复**: 违反单一职责原则 (SRP)。建议重构：
    *   将 NFO 解析逻辑移至 `src/core/nfo_parser.py`。
    *   将文件扫描与匹配逻辑移至 `src/core/scanner.py`。
    *   将重命名操作封装为 `MediaFileOperator` 类。

---

## ⚠️ Major Issues (建议修复)

### 3. Naming Convention: Misleading `LLMMapper`
`src/core/llm_mapper.py` 中的 `LLMMapper` 本质上是 `DirectMapper` 的别名 (`LLMMapper = DirectMapper`)，且代码逻辑完全是确定性的字典映射 (`map_to_movie_nfo`)，**根本没有调用 LLM**。
*   **问题**: 命名严重误导维护者。这看起来像是未完成功能的残留。
*   **修复**: 既然是直接映射，就应该叫 `SchemaMapper` 或 `DirectMapper`。如果未来打算接入 LLM，应该使用策略模式 (`MapperStrategy`) 区分 `LLM` 和 `Direct` 实现。

### 4. Safety: Default In-Place Operation
默认行为是 **In-place Renaming** (原地重命名)。
*   **风险**: 如果刮削匹配错误（Automated matching is never 100% accurate），原始文件名（通常包含 Release Group 等重要信息）会被立即覆盖且无法恢复。这对于用户数据来说是极度危险的。
*   **修复**:
    *   默认应开启 `Dry Run` 模式（仅打印计划的操作）。
    *   或者默认行为改为 `Copy` 或 `Link`，保留源文件。
    *   至少在执行破坏性重命名之前，强制要求用户确认，或者提供 `Undo` 脚本生成。

### 5. Type Safety: Overuse of `Dict[str, Any]`
`GraphState` 虽然定义了 Pydantic 模型，但在各个 Node (`fetch_node`, `normalize_node`) 之间传递数据时，大量使用了非结构化的 `Dict` 操作 (`state.source_data.get(...)`)。
*   **问题**: 失去了类型系统的保护，容易导致 `KeyError` 或 `AttributeError`，IDE 的自动补全也失效了。
*   **修复**: 在各个 Stage 之间传递强类型的 Pydantic Model 对象，而不是 raw dict。

---

## ℹ️ Minor Issues & Performance

### 6. Error Handling: Catch-All Exceptions
`batch_scraper.py` 中充斥着 `except Exception as e: print(...)`。
*   **问题**: 这种宽泛的捕获会吞掉 `KeyboardInterrupt` (Ctrl+C)，导致用户无法优雅地终止长时间运行的批量任务。
*   **修复**: 捕获具体的异常类型，或者至少在 catch 块中重新抛出 `SystemExit` / `KeyboardInterrupt`。

### 7. Performance: Serial Processing
批量处理 (`_run_multi_mode`)是单线程串行的。
*   **问题**: 刮削任务是典型的 I/O 密集型（大量网络请求）。串行处理会导致处理大库时非常缓慢。
*   **修复**: 使用 `concurrent.futures.ThreadPoolExecutor` 或 `asyncio` 来并发处理多个 Shows。

### 8. Testing
虽然有部分单元测试，但缺乏 **Integration Tests**（集成测试）。例如，在没有真实网络请求的情况下（Mock TMDB），测试整个 Pipeline 从 Input 到 Output NFO 生成的完整流程。

---

## 总结
该项目作为一个 POC (Proof of Concept) 或个人脚本是合格的，但作为一个生产级的工程项目，在架构分层、安全性和健壮性上还有显著差距。建议先解决 API Key 和数据安全（In-place 风险）问题，再进行重构。
