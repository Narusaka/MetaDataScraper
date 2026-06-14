import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree


class ExecutionVerifier:
    """Verify that an execution plan produced the promised filesystem state."""

    IMAGE_SIGNATURES = {
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
    }

    def verify(self, plan: Dict[str, Any], artwork: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        for action in plan.get("actions") or []:
            if not isinstance(action, dict) or action.get("status") in {"blocked", "skipped"}:
                continue
            checks.append(self._verify_action(action))

        checks.extend(self._verify_diagnostics(plan))
        checks.extend(self._verify_artwork(plan, artwork or {}))
        failed = [check for check in checks if check["status"] == "failed"]
        warnings = [check for check in checks if check["status"] == "warning"]
        passed = [check for check in checks if check["status"] == "passed"]
        skipped = [check for check in checks if check["status"] == "skipped"]
        status = "failed" if failed else "partial" if warnings else "passed"
        return {
            "status": status,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "checked": len(passed) + len(failed) + len(warnings),
            "passed": len(passed),
            "failed": len(failed),
            "warnings": len(warnings),
            "skipped": len(skipped),
            "checks": checks[:200],
            "failure_codes": [check["code"] for check in failed],
            "warning_codes": [check["code"] for check in warnings],
        }

    def _verify_diagnostics(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        checks = []
        for diagnostic in plan.get("diagnostics") or []:
            if not isinstance(diagnostic, dict):
                continue
            level = str(diagnostic.get("level") or "warning")
            checks.append({
                "type": "metadata_diagnostic",
                "kind": str(diagnostic.get("stage") or "metadata"),
                "status": "failed" if level == "error" else "warning",
                "code": str(diagnostic.get("code") or "metadata_diagnostic"),
                "message": str(diagnostic.get("message") or "Metadata processing was incomplete."),
                "required": level == "error",
                "season": diagnostic.get("season"),
                "episode": diagnostic.get("episode"),
            })
        return checks

    def _verify_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(action.get("type") or "")
        source = Path(action["source"]) if action.get("source") else None
        destination = Path(action["destination"]) if action.get("destination") else None
        required = bool(action.get("required", True))
        kind = str(action.get("kind") or action_type)

        if destination is None:
            return self._result(action, "failed", "missing_destination", "Plan action has no destination.")

        destination_ok = destination.is_dir() if action_type in {"create_dir", "rename_dir"} else self._valid_file(destination, kind)
        if not destination_ok:
            status = "failed" if required else "skipped"
            code = "required_output_missing" if required else "optional_output_missing"
            return self._result(action, status, code, f"Expected output is missing or invalid: {destination}")

        if action_type in {"move_file", "replace_file", "rename_dir"} and source and source != destination and source.exists():
            return self._result(action, "failed", "source_still_exists", f"Source still exists after {action_type}: {source}")

        if action_type in {"copy_file", "overwrite_file"} and source and not source.exists():
            return self._result(action, "failed", "copy_source_missing", f"Copy source no longer exists: {source}")

        return self._result(action, "passed", "output_verified", f"Verified {destination}")

    def _verify_artwork(self, plan: Dict[str, Any], artwork: Dict[str, Any]) -> List[Dict[str, Any]]:
        status = str(artwork.get("status") or "skipped")
        if status == "skipped":
            return []
        if status == "failed":
            return [{
                "type": "artwork",
                "kind": "artwork",
                "status": "failed",
                "code": "artwork_download_failed",
                "message": str(artwork.get("error") or "Artwork download failed."),
                "required": True,
            }]

        target_root = Path(str(plan.get("target_root") or plan.get("source_path") or "."))
        checks: List[Dict[str, Any]] = []
        files = artwork.get("files") if isinstance(artwork.get("files"), dict) else {}
        for kind, values in files.items():
            if not isinstance(values, list):
                continue
            for relative_path in values:
                path = target_root / str(relative_path)
                valid = self._valid_file(path, f"artwork:{kind}")
                checks.append({
                    "type": "artwork",
                    "kind": str(kind),
                    "destination": str(path),
                    "required": True,
                    "status": "passed" if valid else "failed",
                    "code": "artwork_file_verified" if valid else "artwork_file_missing",
                    "message": f"{'Verified' if valid else 'Missing or invalid'} artwork file: {path}",
                })

        total = int(artwork.get("total") or 0)
        manifest = target_root / "artwork-manifest.json"
        if total > 0:
            manifest_valid = self._valid_json(manifest)
            checks.append({
                "type": "artwork_manifest",
                "kind": "artwork_manifest",
                "destination": str(manifest),
                "required": True,
                "status": "passed" if manifest_valid else "failed",
                "code": "artwork_manifest_verified" if manifest_valid else "artwork_manifest_invalid",
                "message": f"{'Verified' if manifest_valid else 'Missing or invalid'} artwork manifest: {manifest}",
            })

        missing_core = [str(item) for item in artwork.get("missing_core") or []]
        if status == "empty" or missing_core:
            checks.append({
                "type": "artwork_coverage",
                "kind": "artwork_coverage",
                "required": False,
                "status": "warning",
                "code": "artwork_incomplete",
                "message": "No artwork was downloaded." if status == "empty" else f"Missing artwork types: {', '.join(missing_core)}",
                "missing": missing_core,
            })
        return checks

    def _valid_file(self, path: Path, kind: str) -> bool:
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            if "nfo" in kind or path.suffix.lower() == ".nfo":
                ElementTree.parse(path)
            elif "manifest" in kind or path.name == "artwork-manifest.json":
                return self._valid_json(path)
            elif path.suffix.lower() in self.IMAGE_SIGNATURES:
                header = path.read_bytes()[:12]
                signatures = self.IMAGE_SIGNATURES[path.suffix.lower()]
                if not any(header.startswith(signature) for signature in signatures):
                    return False
                if path.suffix.lower() == ".webp" and header[8:12] != b"WEBP":
                    return False
            return True
        except (OSError, ElementTree.ParseError, ValueError):
            return False

    @staticmethod
    def _valid_json(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False

    @staticmethod
    def _result(action: Dict[str, Any], status: str, code: str, message: str) -> Dict[str, Any]:
        return {
            "type": action.get("type"),
            "kind": action.get("kind"),
            "source": action.get("source"),
            "destination": action.get("destination"),
            "required": bool(action.get("required", True)),
            "status": status,
            "code": code,
            "message": message,
        }
