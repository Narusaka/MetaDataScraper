import os
import shutil
import time
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from src.core.cancellation import raise_if_cancelled

logger = logging.getLogger(__name__)


class ArtworkDownloader:
    def __init__(self, tmdb_api_key: str, proxy: Optional[Dict[str, str]] = None, manifest: Optional[Any] = None, cancel_event=None):
        self.tmdb_api_key = tmdb_api_key
        self.proxy = proxy
        self.manifest = manifest
        self.cancel_event = cancel_event
        self.session = requests.Session()

        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if proxy:
            self.session.proxies.update(proxy)
        self.base_image_url = "https://image.tmdb.org/t/p/original"

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _tmdb_request_kwargs(self) -> Dict[str, Any]:
        if self.tmdb_api_key and self.tmdb_api_key.startswith("eyJ") and self.tmdb_api_key.count(".") == 2:
            return {"headers": {"Authorization": f"Bearer {self.tmdb_api_key}"}}
        return {"params": {"api_key": self.tmdb_api_key}}

    def _image_url(self, file_path: str) -> str:
        if not file_path.startswith("/"):
            file_path = "/" + file_path
        return self.base_image_url + file_path

    def _safe_limit(self, image_limits: Optional[Dict[str, Any]], key: str, default: int) -> int:
        try:
            value = int((image_limits or {}).get(key, default))
            return max(value, 0)
        except (TypeError, ValueError):
            return default

    def _normalize_policy(self, policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        raw = policy or {}
        languages = raw.get("preferred_languages", ["zh", "en", "ja"])
        if isinstance(languages, str):
            languages = [item.strip() for item in languages.split(",")]
        normalized_languages = []
        for language in languages if isinstance(languages, list) else []:
            base = str(language or "").strip().lower().split("-")[0]
            if base and base not in normalized_languages:
                normalized_languages.append(base)
        if not normalized_languages:
            normalized_languages = ["zh", "en", "ja"]
        return {
            "preferred_languages": normalized_languages,
            "min_poster_width": self._safe_limit(raw, "min_poster_width", 500),
            "min_backdrop_width": self._safe_limit(raw, "min_backdrop_width", 1280),
            "min_logo_width": self._safe_limit(raw, "min_logo_width", 300),
        }

    def _rank_images(
        self,
        images: List[Dict[str, Any]],
        kind: str,
        policy: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        languages = policy["preferred_languages"]
        minimum_width = {
            "poster": policy["min_poster_width"],
            "backdrop": policy["min_backdrop_width"],
            "logo": policy["min_logo_width"],
        }.get(kind, 0)
        target_ratio = {"poster": 2 / 3, "backdrop": 16 / 9}.get(kind)

        valid = [dict(image) for image in images if isinstance(image, dict) and image.get("file_path")]
        eligible = [image for image in valid if int(image.get("width") or 0) >= minimum_width]
        candidates = eligible or valid

        def score(image: Dict[str, Any]):
            language = str(image.get("iso_639_1") or "").lower().split("-")[0]
            if language in languages:
                language_rank = languages.index(language)
            elif not language:
                language_rank = len(languages)
            else:
                language_rank = len(languages) + 1
            width = int(image.get("width") or 0)
            height = int(image.get("height") or 0)
            ratio = float(image.get("aspect_ratio") or (width / height if height else 0))
            ratio_distance = abs(ratio - target_ratio) if target_ratio and ratio else 99.0
            return (
                language_rank,
                -float(image.get("vote_average") or 0),
                -int(image.get("vote_count") or 0),
                -(width * height),
                ratio_distance,
                str(image.get("file_path") or ""),
            )

        ranked = sorted(candidates, key=score)
        for index, image in enumerate(ranked, start=1):
            image["_selection_rank"] = index
            image["_minimum_width_fallback"] = not bool(eligible) and bool(valid) and minimum_width > 0
        return ranked

    def download_image(self, image_path: str, url: str, max_retries: int = 3, overwrite: bool = True) -> bool:
        """Download a single image, validate it, then atomically publish it."""
        if not overwrite and os.path.exists(image_path):
            return True

        for attempt in range(max_retries):
            raise_if_cancelled(self.cancel_event, "artwork.download")
            try:
                return self._download_image_once(image_path, url, verify=True)
            except requests.exceptions.SSLError:
                if attempt == 0:
                    try:
                        return self._download_image_once(image_path, url, verify=False)
                    except requests.RequestException as e:
                        logger.warning("SSL error, retry with verify=False also failed for %s: %s", url, e)
                        continue
                continue
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    logger.warning("Failed to download %s: %s", url, e)
                    return False
                logger.warning("Retry %s/%s for %s", attempt + 1, max_retries, url)
                time.sleep(1)
        return False

    def _download_image_once(self, image_path: str, url: str, verify: bool = True) -> bool:
        raise_if_cancelled(self.cancel_event, "artwork.request")
        existed = os.path.exists(image_path)
        response = self.session.get(url, timeout=30, stream=True, verify=verify)
        response.raise_for_status()

        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        tmp_path = f"{image_path}.download"
        try:
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    raise_if_cancelled(self.cancel_event, "artwork.stream")
                    if chunk:
                        f.write(chunk)

            self._validate_downloaded_image(tmp_path, response)
            backup_path = self.manifest.backup_file(image_path) if self.manifest and existed else None
            os.replace(tmp_path, image_path)
            if self.manifest:
                extra = {"kind": "artwork", "url": url}
                if not verify:
                    extra["verify"] = False
                if backup_path:
                    extra["backup_path"] = str(backup_path)
                self.manifest.record(
                    "overwrite_file" if existed else "create_file",
                    None,
                    image_path,
                    extra=extra,
                )
            return True
        except Exception:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _validate_downloaded_image(self, image_path: str, response: requests.Response) -> None:
        size = os.path.getsize(image_path)
        if size < 32:
            raise requests.RequestException(f"Downloaded image is too small ({size} bytes)")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            raise requests.RequestException(f"Unexpected image content type: {content_type}")

        with open(image_path, "rb") as file:
            header = file.read(16)

        is_jpeg = header.startswith(b"\xff\xd8\xff")
        is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
        is_webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        is_gif = header.startswith((b"GIF87a", b"GIF89a"))
        if not any((is_jpeg, is_png, is_webp, is_gif)):
            raise requests.RequestException("Downloaded file is not a recognized image")

    def _download_first(
        self,
        images: List[Dict[str, Any]],
        output_dir: str,
        filename: str,
        key: str,
        downloaded_images: Dict[str, List[str]],
        assets: List[Dict[str, Any]],
        overwrite: bool,
    ) -> bool:
        downloaded_images[key] = []
        for image in images:
            raise_if_cancelled(self.cancel_event, f"artwork.{key}")
            file_path = image.get("file_path")
            if not file_path:
                continue
            dest = os.path.join(output_dir, filename)
            if self.download_image(dest, self._image_url(file_path), overwrite=overwrite):
                downloaded_images[key] = [filename]
                assets.append(self._asset_record(key, filename, self._image_url(file_path), image))
                return True
        return False

    def _copy_companion(self, source: str, dest: str, overwrite: bool) -> bool:
        if not os.path.exists(source):
            return False
        if os.path.exists(dest) and not overwrite:
            return True
        try:
            existed = os.path.exists(dest)
            backup_path = self.manifest.backup_file(dest) if self.manifest and existed else None
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(source, dest)
            if self.manifest:
                extra = {"kind": "artwork", "derived_from": source}
                if backup_path:
                    extra["backup_path"] = str(backup_path)
                self.manifest.record(
                    "overwrite_file" if existed else "create_file",
                    None,
                    dest,
                    extra=extra,
                )
            return True
        except OSError:
            return False

    def _asset_record(
        self,
        kind: str,
        relative_path: str,
        url: Optional[str] = None,
        source_data: Optional[Dict[str, Any]] = None,
        derived_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        source_data = source_data or {}
        record = {
            "kind": kind,
            "path": relative_path,
            "url": url,
            "downloaded_at": self._utc_now(),
        }
        if derived_from:
            record["derived_from"] = derived_from
        for key in ("file_path", "iso_639_1", "width", "height", "aspect_ratio", "vote_average", "vote_count", "name"):
            if source_data.get(key) is not None:
                record[key] = source_data.get(key)
        if source_data.get("_selection_rank") is not None:
            record["selection_rank"] = source_data["_selection_rank"]
        if source_data.get("_minimum_width_fallback"):
            record["minimum_width_fallback"] = True
        return record

    def _download_extra_group(
        self,
        images: List[Dict[str, Any]],
        output_dir: str,
        folder: str,
        stem: str,
        extension: str,
        limit: int,
        skip_first: bool,
        kind: str,
        assets: List[Dict[str, Any]],
        overwrite: bool,
    ) -> List[str]:
        if limit <= 0:
            return []

        group_dir = os.path.join(output_dir, "Extra", folder)
        downloaded = []
        candidates = images[1:] if skip_first else images

        for image in candidates[:limit]:
            raise_if_cancelled(self.cancel_event, f"artwork.{kind}")
            file_path = image.get("file_path")
            if not file_path:
                continue
            index = len(downloaded) + 1
            filename = f"{stem}-{index:02d}.{extension}"
            dest = os.path.join(group_dir, filename)
            relative_path = f"Extra/{folder}/{filename}"
            if self.download_image(dest, self._image_url(file_path), overwrite=overwrite):
                downloaded.append(relative_path)
                assets.append(self._asset_record(kind, relative_path, self._image_url(file_path), image))
        return downloaded

    def _write_artwork_manifest(
        self,
        output_dir: str,
        media_type: str,
        tmdb_id: int,
        assets: List[Dict[str, Any]],
        downloaded_images: Dict[str, List[str]],
        policy: Dict[str, Any],
    ) -> None:
        payload = {
            "version": 1,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "generated_at": self._utc_now(),
            "selection_policy": policy,
            "summary": {
                key: len(value)
                for key, value in downloaded_images.items()
                if isinstance(value, list)
            },
            "assets": assets,
        }
        manifest_path = os.path.join(output_dir, "artwork-manifest.json")
        existed = os.path.exists(manifest_path)
        backup_path = self.manifest.backup_file(manifest_path) if self.manifest and existed else None
        tmp_path = manifest_path + ".tmp"
        os.makedirs(output_dir, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, manifest_path)
        if self.manifest:
            extra = {"kind": "artwork_manifest"}
            if backup_path:
                extra["backup_path"] = str(backup_path)
            self.manifest.record(
                "overwrite_file" if existed else "create_file",
                None,
                manifest_path,
                extra=extra,
            )

    def download_all_images(
        self,
        media_type: str,
        tmdb_id: int,
        output_dir: str,
        verbose: bool = False,
        extra_images: bool = False,
        image_limits: Optional[Dict[str, Any]] = None,
        artwork_policy: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> Dict[str, List[str]]:
        """Download available artwork with Emby/Jellyfin-friendly names."""
        images_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/images"
        policy = self._normalize_policy(artwork_policy)
        request_kwargs = self._tmdb_request_kwargs()
        request_kwargs["params"] = {
            **request_kwargs.get("params", {}),
            "include_image_language": ",".join(policy["preferred_languages"] + ["null"]),
        }

        images_data = None
        for attempt in range(3):
            raise_if_cancelled(self.cancel_event, "artwork.catalog")
            try:
                response = self.session.get(images_url, timeout=30, **request_kwargs)
                response.raise_for_status()
                images_data = response.json()
                break
            except requests.RequestException as e:
                if attempt == 2:
                    if verbose:
                        print(f"Failed to get images for {media_type} {tmdb_id}: {e}")
                    return {}
                if verbose:
                    print(f"Retry {attempt + 1}/3 for images API")
                time.sleep(1)

        posters = self._rank_images(images_data.get("posters", []) if images_data else [], "poster", policy)
        backdrops = self._rank_images(images_data.get("backdrops", []) if images_data else [], "backdrop", policy)
        logos = self._rank_images(images_data.get("logos", []) if images_data else [], "logo", policy)

        downloaded_images: Dict[str, List[str]] = {}
        assets: List[Dict[str, Any]] = []

        if verbose and extra_images:
            total_images = len(posters) + len(backdrops) + len(logos)
            print(f"   获取到图片数据: 共{total_images}张图片")

        if self._download_first(posters, output_dir, "poster.jpg", "poster", downloaded_images, assets, overwrite) and verbose:
            print("   ✓ 设置主海报 (poster.jpg)")

        if self._download_first(backdrops, output_dir, "fanart.jpg", "fanart", downloaded_images, assets, overwrite):
            banner_dest = os.path.join(output_dir, "banner.jpg")
            if self._copy_companion(os.path.join(output_dir, "fanart.jpg"), banner_dest, overwrite):
                downloaded_images["banner"] = ["banner.jpg"]
                assets.append(self._asset_record("banner", "banner.jpg", derived_from="fanart.jpg"))
            if verbose:
                print("   ✓ 设置主背景图 (fanart.jpg + banner.jpg)")
        else:
            downloaded_images["banner"] = []

        if self._download_first(logos, output_dir, "clearlogo.png", "logo", downloaded_images, assets, overwrite):
            clearart_dest = os.path.join(output_dir, "clearart.png")
            if self._copy_companion(os.path.join(output_dir, "clearlogo.png"), clearart_dest, overwrite):
                downloaded_images["clearart"] = ["clearart.png"]
                assets.append(self._asset_record("clearart", "clearart.png", derived_from="clearlogo.png"))
            if verbose:
                print("   ✓ 设置主标志 (clearlogo.png + clearart.png)")
        else:
            downloaded_images["clearart"] = []

        if extra_images:
            poster_limit = self._safe_limit(image_limits, "posters", 20)
            backdrop_limit = self._safe_limit(image_limits, "backdrops", 5)
            logo_limit = self._safe_limit(image_limits, "logos", 5)
            still_limit = self._safe_limit(image_limits, "stills", 10)
            actor_limit = self._safe_limit(image_limits, "actors", 10)

            downloaded_images["poster_extra"] = self._download_extra_group(
                posters, output_dir, "posters", "poster", "jpg", poster_limit, skip_first=True, kind="poster_extra", assets=assets, overwrite=overwrite
            )
            downloaded_images["backdrop_extra"] = self._download_extra_group(
                backdrops, output_dir, "backdrops", "backdrop", "jpg", backdrop_limit, skip_first=True, kind="backdrop_extra", assets=assets, overwrite=overwrite
            )
            downloaded_images["logo_extra"] = self._download_extra_group(
                logos, output_dir, "logos", "logo", "png", logo_limit, skip_first=True, kind="logo_extra", assets=assets, overwrite=overwrite
            )

            if media_type == "tv" and still_limit > 0:
                downloaded_images["stills"] = self._download_episode_stills(
                    tmdb_id, output_dir, request_kwargs, still_limit, assets, overwrite, verbose
                )

            if actor_limit > 0:
                downloaded_images["actors"] = self._download_actor_images(
                    media_type, tmdb_id, output_dir, request_kwargs, actor_limit, assets, overwrite, verbose
                )

        if verbose:
            total_downloaded = sum(len(images) for images in downloaded_images.values() if isinstance(images, list))
            print(f"   图片下载完成: 共{total_downloaded}张")

        if assets:
            self._write_artwork_manifest(output_dir, media_type, tmdb_id, assets, downloaded_images, policy)

        return downloaded_images

    def _download_episode_stills(
        self,
        tmdb_id: int,
        output_dir: str,
        request_kwargs: Dict[str, Any],
        limit: int,
        assets: List[Dict[str, Any]],
        overwrite: bool,
        verbose: bool,
    ) -> List[str]:
        try:
            episodes_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/1"
            response = self.session.get(episodes_url, timeout=30, **request_kwargs)
            response.raise_for_status()
            season_data = response.json()
        except requests.RequestException as e:
            if verbose:
                print(f"   ✗ 获取剧集截图失败: {e}")
            return []

        downloaded = []
        stills_dir = os.path.join(output_dir, "Extra", "stills")
        for episode in season_data.get("episodes", []):
            raise_if_cancelled(self.cancel_event, "artwork.stills")
            if len(downloaded) >= limit:
                break
            still_path = episode.get("still_path")
            if not still_path:
                continue
            filename = f"S01E{episode['episode_number']:02d}.jpg"
            dest = os.path.join(stills_dir, filename)
            if self.download_image(dest, self._image_url(still_path), overwrite=overwrite):
                relative_path = f"Extra/stills/{filename}"
                downloaded.append(relative_path)
                assets.append(self._asset_record("still", relative_path, self._image_url(still_path), {"file_path": still_path}))

        if verbose and downloaded:
            print(f"   ✓ 下载了 {len(downloaded)} 张剧集截图")
        return downloaded

    def _download_actor_images(
        self,
        media_type: str,
        tmdb_id: int,
        output_dir: str,
        request_kwargs: Dict[str, Any],
        limit: int,
        assets: List[Dict[str, Any]],
        overwrite: bool,
        verbose: bool,
    ) -> List[str]:
        try:
            credits_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/credits"
            response = self.session.get(credits_url, timeout=30, **request_kwargs)
            response.raise_for_status()
            credits_data = response.json()
        except requests.RequestException as e:
            if verbose:
                print(f"   ✗ 获取演员头像失败: {e}")
            return []

        downloaded = []
        actors_dir = os.path.join(output_dir, "Extra", "actors")
        for actor in credits_data.get("cast", []):
            raise_if_cancelled(self.cancel_event, "artwork.actors")
            if len(downloaded) >= limit:
                break
            profile_path = actor.get("profile_path")
            if not profile_path:
                continue
            actor_name = actor.get("name", "unknown")
            actor_name_clean = "".join(c for c in actor_name if c.isalnum() or c in " _-").strip()
            actor_name_clean = actor_name_clean.replace(" ", "_") or "actor"
            filename = f"{actor_name_clean}.jpg"
            dest = os.path.join(actors_dir, filename)
            if self.download_image(dest, self._image_url(profile_path), overwrite=overwrite):
                relative_path = f"Extra/actors/{filename}"
                downloaded.append(relative_path)
                assets.append(self._asset_record("actor", relative_path, self._image_url(profile_path), {"file_path": profile_path, "name": actor_name}))

        if verbose and downloaded:
            print(f"   ✓ 下载了{len(downloaded)}张演员头像")
        return downloaded
