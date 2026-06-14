from pathlib import Path


def is_hidden_path(path: Path) -> bool:
    """Identify dotfiles, AppleDouble files, and content below hidden dirs."""
    return any(part.startswith(".") for part in path.parts if part not in {".", ".."})
