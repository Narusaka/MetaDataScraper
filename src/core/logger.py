"""
Media Metadata Agent Logger

A comprehensive logging system that provides both terminal output and detailed log file storage.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Union
from pathlib import Path


class MetadataLogger:
    """Logger for Media Metadata Agent with terminal and file output."""

    def __init__(self, log_dir: str = "./logs", log_level: str = "INFO", verbose: bool = False, quiet: bool = False):
        """
        Initialize the logger.

        Args:
            log_dir: Directory to store log files
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
            verbose: Whether to show verbose output in terminal
            quiet: Whether to suppress terminal output
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.verbose = verbose
        self.quiet = quiet

        # Create timestamp for log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"metadata_agent_{timestamp}.log"

        # Setup Python logging
        self.logger = logging.getLogger("MetadataAgent")
        self.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # Remove any existing handlers
        self.logger.handlers.clear()

        # File handler - logs everything
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

        # Store processing data for comprehensive logging
        self.processing_data = {
            "start_time": datetime.now().isoformat(),
            "input": {},
            "search": {},
            "fetch": {},
            "translate": {},
            "normalize": {},
            "nfo": {},
            "output": {},
            "errors": []
        }

    def log_input(self, data: Dict[str, Any]) -> None:
        """Log input parameters."""
        self.processing_data["input"] = data

        if not self.quiet:
            print("📋 解析输入参数...")
            if self.verbose:
                print(f"   媒体类型: {data.get('media_type', 'unknown')}")
                print(f"   查询: {data.get('query', 'N/A')}")
                print(f"   TMDB ID: {data.get('tmdb_id', 'N/A')}")
                print(f"   输出目录: {data.get('output_dir', 'N/A')}")

        self.logger.info("Input parameters parsed")
        self.logger.debug(f"Input data: {json.dumps(data, ensure_ascii=False, indent=2)}")

    def log_search(self, results: Dict[str, Any], skip_search: bool = False) -> None:
        """Log search results."""
        self.processing_data["search"] = {"results": results, "skip_search": skip_search}

        if not self.quiet:
            if skip_search:
                if self.verbose:
                    print("🔍 跳过搜索，直接使用 ID")
            else:
                result_count = len(results.get("results", []))
                if self.verbose:
                    print(f"   找到 {result_count} 个结果")

        self.logger.info(f"Search completed: {len(results.get('results', []))} results")
        self.logger.debug(f"Search results: {json.dumps(results, ensure_ascii=False, indent=2)}")

    def log_fetch(self, source_data: Dict[str, Any]) -> None:
        """Log fetched data from APIs."""
        self.processing_data["fetch"] = source_data

        if not self.quiet:
            main_data = source_data.get("main", {})
            credits_data = source_data.get("credits", {})
            keywords_data = source_data.get("keywords", {})

            media_type = "tv" if source_data.get("episodes") else "movie"
            title = main_data.get("name", main_data.get("title", "Unknown"))
            print(f"📥 获取 {media_type} 数据 (TMDB ID: {main_data.get('id', 'N/A')})")

            if self.verbose:
                print(f"   标题: {title}")
                cast_count = len(credits_data.get("cast", []))
                print(f"   演员数量: {cast_count}")

                # Handle different keyword formats
                keywords_list = keywords_data.get("keywords", []) or keywords_data.get("results", [])
                print(f"   关键词数量: {len(keywords_list)}")

                if media_type == "tv":
                    episodes_data = source_data.get("episodes", [])
                    seasons_data = source_data.get("seasons", [])
                    season_count = len([s for s in seasons_data if s.get("season_number", 0) > 0])
                    print(f"   季数量: {season_count}")
                    print(f"   总集数: {len(episodes_data)}")

        # Log full metadata to file
        self.logger.info("Data fetching completed")
        self.logger.debug(f"Main data: {json.dumps(source_data.get('main', {}), ensure_ascii=False, indent=2)}")
        self.logger.debug(f"Credits data: {json.dumps(source_data.get('credits', {}), ensure_ascii=False, indent=2)}")
        self.logger.debug(f"Keywords data: {json.dumps(source_data.get('keywords', {}), ensure_ascii=False, indent=2)}")

        if source_data.get("episodes"):
            self.logger.debug(f"Episodes data: {json.dumps(source_data.get('episodes', []), ensure_ascii=False, indent=2)}")
        if source_data.get("seasons"):
            self.logger.debug(f"Seasons data: {json.dumps(source_data.get('seasons', []), ensure_ascii=False, indent=2)}")
        if source_data.get("omdb"):
            self.logger.debug(f"OMDB data: {json.dumps(source_data.get('omdb', {}), ensure_ascii=False, indent=2)}")

    def log_translate(self, translated_data: Dict[str, Any], episodes_data: Optional[list] = None) -> None:
        """Log translation results."""
        self.processing_data["translate"] = {
            "translated": translated_data,
            "episodes": episodes_data
        }

        if not self.quiet:
            print("🌐 处理元数据语言...")
            if self.verbose:
                print("   📊 标准化数据:")
                print(f"     标题: {translated_data.get('title', 'N/A')}")
                print(f"     中文标题: {translated_data.get('title_zh', 'N/A')}")
                print(f"     英文关键词: {translated_data.get('keywords', 'N/A')}")

                if episodes_data:
                    print(f"   翻译 {len(episodes_data)} 个剧集标题...")

        self.logger.info("Translation processing completed")
        self.logger.debug(f"Translated data: {json.dumps(translated_data, ensure_ascii=False, indent=2)}")
        if episodes_data:
            self.logger.debug(f"Translated episodes: {json.dumps(episodes_data, ensure_ascii=False, indent=2)}")

    def log_normalize(self, normalized_data: Dict[str, Any]) -> None:
        """Log normalization results."""
        self.processing_data["normalize"] = normalized_data

        if not self.quiet and self.verbose:
            print("🔧 数据标准化...")
            print("   📋 标准化结果:")
            print(f"     最终标题: {normalized_data.get('title_zh', normalized_data.get('title', 'N/A'))}")
            print(f"     最终关键词: {normalized_data.get('keywords', 'N/A')}")
            print(f"     演员数量: {len(normalized_data.get('cast', []))}")
            print(f"     导演: {normalized_data.get('directors', 'N/A')}")
            print(f"     类型: {normalized_data.get('genres_zh', normalized_data.get('genres', 'N/A'))}")

        self.logger.info("Data normalization completed")
        self.logger.debug(f"Normalized data: {json.dumps(normalized_data, ensure_ascii=False, indent=2)}")

    def log_nfo(self, nfo_data: Dict[str, Any], xml_content: Optional[str] = None) -> None:
        """Log NFO generation results."""
        self.processing_data["nfo"] = {"data": nfo_data, "xml": xml_content}

        if not self.quiet and self.verbose:
            print("📝 映射到NFO格式...")
            print("   📋 NFO数据结构:")
            print(f"     标题: {nfo_data.get('title', 'N/A')}")
            print(f"     年份: {nfo_data.get('year', 'N/A')}")
            print(f"     类型: {nfo_data.get('genre', 'N/A')}")
            print(f"     标签: {nfo_data.get('tags', 'N/A')}")

        self.logger.info("NFO generation completed")
        self.logger.debug(f"NFO data: {json.dumps(nfo_data, ensure_ascii=False, indent=2)}")
        if xml_content:
            self.logger.debug(f"NFO XML content:\n{xml_content}")

    def log_output(self, output_data: Dict[str, Any]) -> None:
        """Log final output results."""
        self.processing_data["output"] = output_data

        if not self.quiet:
            print("💾 写入输出文件...")

            files_created = output_data.get("files", {})
            if files_created.get("media_dir"):
                print(f"   媒体目录: {files_created['media_dir']}")
            if files_created.get("nfo_file"):
                print(f"   NFO 文件: {files_created['nfo_file']}")

            if self.verbose:
                print(f"   创建了 {len(files_created)} 个文件/目录")

        self.logger.info("Output generation completed")
        self.logger.debug(f"Output data: {json.dumps(output_data, ensure_ascii=False, indent=2)}")

    def log_error(self, error: Union[str, Exception]) -> None:
        """Log errors."""
        error_msg = str(error)
        self.processing_data["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "error": error_msg
        })

        if not self.quiet:
            print(f"❌ 错误: {error_msg}")

        self.logger.error(f"Error occurred: {error_msg}")

    def log_info(self, message: str, level: str = "info") -> None:
        """Log general information messages."""
        if level == "verbose" and not self.verbose:
            return
        if not self.quiet:
            print(message)

        log_method = getattr(self.logger, level.lower(), self.logger.info)
        log_method(message)

    def finalize(self) -> str:
        """Finalize logging and return log file path."""
        self.processing_data["end_time"] = datetime.now().isoformat()

        # Write complete processing data to log file
        self.logger.info("=== PROCESSING SUMMARY ===")
        self.logger.info(f"Log file: {self.log_file}")
        self.logger.info(f"Processing completed successfully")

        # Write full processing data as JSON
        try:
            summary_file = self.log_dir / f"processing_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(self.processing_data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Processing summary saved to: {summary_file}")
        except Exception as e:
            self.logger.error(f"Failed to save processing summary: {e}")

        return str(self.log_file)
