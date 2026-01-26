
import sys
import argparse
import logging
import time
from pathlib import Path
from logging.handlers import RotatingFileHandler
from src.batch import BatchMediaScraper

def setup_logging(project_root):
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "media_agent.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
        ]
    )

def run_scraper(args, multi_mode: bool, workers: int):
    # Determine inplace logic
    inplace = args.inplace or (args.output is None and not multi_mode)
    if args.output:
        inplace = args.inplace

    # Warning for destructive operations
    if inplace and not args.dry_run and not args.no_confirm:
        print("\n⚠️  WARNING: You are about to perform IN-PLACE renaming.")
        if multi_mode:
            print(f"   Mode: BATCH (Processing all subdirectories in '{args.input_dir}')")
        else:
            print(f"   Mode: SINGLE (Processing '{args.input_dir}')")
        print(f"   This operation cannot be easily undone.")
        
        try:
            print("   Press Ctrl+C within 5 seconds to cancel...", end='', flush=True)
            for _ in range(5):
                time.sleep(1)
                print(".", end='', flush=True)
            print("\n   Starting now!")
        except KeyboardInterrupt:
            print("\n\n❌ Operation cancelled by user.")
            sys.exit(0)
            
    # Resolve Project Root for Config
    # Assuming code is in src/interface/cli.py -> project_root is ../../
    project_root = Path(__file__).resolve().parent.parent.parent
    config_path = project_root / "config" / "config.yaml"

    try:
        scraper = BatchMediaScraper(
            config_path=str(config_path),
            copy_files=args.copy,
            inplace_rename=inplace,
            output_dir=args.output,
            multi_mode=multi_mode,
            tmdb_id=getattr(args, 'tmdb_id', None), # Only available in single mode usually
            use_local_nfo=args.use_local_nfo,
            extra_images=args.extra_images,
            media_type=args.type,
            max_workers=workers,
            dry_run=args.dry_run
        )
        scraper.run(args.input_dir, args.output)
    except KeyboardInterrupt:
        print("\n❌ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    setup_logging(project_root)

    parser = argparse.ArgumentParser(description="Media Metadata Scraper CLI")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # Shared Arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("input_dir", help="Input directory path")
    parent_parser.add_argument("--output", "-o", help="Output directory (default: in-place)")
    parent_parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    parent_parser.add_argument("--copy", action="store_true", help="Copy instead of move")
    parent_parser.add_argument("--inplace", action="store_true", help="Force inplace mode")
    parent_parser.add_argument("--no-confirm", action="store_true", help="Skip confirmation prompt")
    parent_parser.add_argument("--use-local-nfo", action="store_true", help="Use existing NFO for IDs")
    parent_parser.add_argument("--type", choices=["movie", "tv"], help="Force media type (disable auto-detection)")
    parent_parser.add_argument("--extra-images", action="store_true", help="Download extra images")

    # Command: SINGLE
    single_parser = subparsers.add_parser("single", parents=[parent_parser], help="Process a SINGLE movie/show directory")
    single_parser.add_argument("--tmdb-id", type=int, help="Force specific TMDB ID")
    
    # Command: BATCH
    batch_parser = subparsers.add_parser("batch", parents=[parent_parser], help="Process MULTIPLE directories in a folder")
    batch_parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers")

    args = parser.parse_args()

    if args.command == "single":
        # Single mode: force 1 worker, multi_mode=False
        run_scraper(args, multi_mode=False, workers=1)
    elif args.command == "batch":
        # Batch mode: use workers arg, multi_mode=True
        run_scraper(args, multi_mode=True, workers=args.workers)

if __name__ == "__main__":
    main()
