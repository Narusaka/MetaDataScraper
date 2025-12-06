#!/usr/bin/env python3
"""
Media Metadata Agent CLI

Command line interface for the Media Metadata Agent.
"""

import argparse
import json
import os
import sys
from typing import Dict, Any, Optional
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from .graph import MediaMetadataGraph
from .state import GraphState


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from file."""
    if not config_path:
        # Try default locations
        candidates = [
            "config.yaml",
            "config.yml",
            "config.example.yaml",
            "model_config.json"
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if not config_path:
        raise FileNotFoundError("No configuration file found")

    if config_path.endswith('.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # For YAML files, we'd need PyYAML
        # For now, assume JSON
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)


def create_default_config() -> Dict[str, Any]:
    """Create default configuration."""
    return {
        "proxy": {
            "http": "http://127.0.0.1:7897",
            "https": "http://127.0.0.1:7897"
        },
        "tmdb": {
            "base_url": "https://api.themoviedb.org/3",
            "api_key": os.getenv("TMDB_API_KEY", "d17bc8d9f1f1fa66368b54d95a296235")
        },
        "omdb": {
            "api_key": os.getenv("OMDB_API_KEY", "330effac")
        },
        "model": {
            "base_url": "http://127.0.0.1:32668/v1",
            "api_key": "EMPTY",
            "model": "local-4b",
            "max_retries": 2,
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 20,
            "min_p": 0,
            "max_tokens": 8000
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Media Metadata Agent")
    parser.add_argument(
        "query",
        nargs="?",
        help="Movie/TV show name (optional if --tmdb-id is provided)"
    )
    parser.add_argument(
        "--type", "-t",
        choices=["movie", "tv"],
        default="movie",
        help="Media type (default: movie)"
    )
    parser.add_argument(
        "--tmdb-id",
        type=int,
        help="TMDB ID (required if query is not provided)"
    )
    parser.add_argument(
        "--omdb-id",
        help="OMDB ID (can be used instead of TMDB ID)"
    )
    parser.add_argument(
        "--output", "-o",
        default="./output",
        help="Output directory (default: ./output)"
    )
    parser.add_argument(
        "--config", "-c",
        help="Configuration file path"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Quiet mode - minimal output"
    )
    parser.add_argument(
        "--aid-search",
        action="store_true",
        help="Enable auxiliary search using Google when TMDB search fails"
    )
    parser.add_argument(
        "--lang",
        choices=["zh-CN", "zh-TW", "en-US"],
        default="zh-CN",
        help="Preferred language for metadata (default: zh-CN)"
    )
    parser.add_argument(
        "--translate",
        action="store_true",
        help="Translate missing content to target language when original is unavailable"
    )
    parser.add_argument(
        "--translate-tags",
        action="store_true",
        default=True,
        help="Translate tags/keywords to Chinese (default: enabled)"
    )
    parser.add_argument(
        "--no-translate-tags",
        action="store_false",
        dest="translate_tags",
        help="Disable tag translation"
    )

    args = parser.parse_args()

    # Validate that at least one of query, tmdb_id, or omdb_id is provided
    if not args.query and not args.tmdb_id and not args.omdb_id:
        parser.error("Either 'query', '--tmdb-id', or '--omdb-id' must be provided")

    try:
        # Load configuration
        if args.config:
            config = load_config(args.config)
        else:
            config = create_default_config()

        # Check if we have direct IDs (TMDB or OMDB)
        has_direct_id = bool(args.tmdb_id or args.omdb_id)

        # Create graph with quiet mode for Google search if we have direct IDs
        graph_builder = MediaMetadataGraph(
            config,
            quiet_google=has_direct_id,
            preferred_language=args.lang,
            verbose=args.verbose,
            quiet=args.quiet
        )
        workflow = graph_builder.create_graph()
        app = workflow.compile()

        # Prepare input
        input_data = {
            "media_type": args.type,
            "query": args.query,
            "output_dir": args.output,
            "verbose": args.verbose,
            "quiet": args.quiet,
            "aid_search": args.aid_search,
            "language": args.lang,
            "translate": args.translate,
            "translate_tags": args.translate_tags
        }

        if args.tmdb_id:
            input_data["tmdb_id"] = args.tmdb_id

        if args.omdb_id:
            input_data["omdb_id"] = args.omdb_id

        # Initialize state
        initial_state = GraphState(
            input=input_data,
            search={},
            source_data={},
            normalized={},
            artwork={},
            nfo={},
            output={},
            errors={}
        )

        # Run workflow
        if args.verbose:
            print(f"Processing {args.type}: {args.query}")
            print(f"Output directory: {args.output}")

        result = app.invoke(initial_state)

        if args.verbose:
            print("Processing completed successfully!")
            print(f"Report: {result.get('output', {}).get('report', 'N/A')}")

        # Print final output
        print(json.dumps(result.get("output", {}), ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
