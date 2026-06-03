import os
import shutil
import time
from typing import Any, Dict, List, Optional

import requests


class ArtworkDownloader:
    def __init__(self, tmdb_api_key: str, proxy: Optional[Dict[str, str]] = None):
        self.tmdb_api_key = tmdb_api_key
        self.proxy = proxy
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

    def download_image(self, image_path: str, url: str, max_retries: int = 3, overwrite: bool = True) -> bool:
        """Download a single image with retry logic."""
        if not overwrite and os.path.exists(image_path):
            return True

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30, stream=True)
                response.raise_for_status()

                os.makedirs(os.path.dirname(image_path), exist_ok=True)
                with open(image_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
            except requests.exceptions.SSLError:
                if attempt == 0:
                    try:
                        response = self.session.get(url, timeout=30, stream=True, verify=False)
                        response.raise_for_status()

                        os.makedirs(os.path.dirname(image_path), exist_ok=True)
                        with open(image_path, "wb") as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        return True
                    except requests.RequestException as e:
                        print(f"SSL error, retry with verify=False also failed for {url}: {e}")
                        continue
                continue
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"Failed to download {url}: {e}")
                    return False
                print(f"Retry {attempt + 1}/{max_retries} for {url}")
                time.sleep(1)
        return False

    def _download_first(
        self,
        images: List[Dict[str, Any]],
        output_dir: str,
        filename: str,
        key: str,
        downloaded_images: Dict[str, List[str]],
        overwrite: bool,
    ) -> bool:
        downloaded_images[key] = []
        for image in images:
            file_path = image.get("file_path")
            if not file_path:
                continue
            dest = os.path.join(output_dir, filename)
            if self.download_image(dest, self._image_url(file_path), overwrite=overwrite):
                downloaded_images[key] = [filename]
                return True
        return False

    def _copy_companion(self, source: str, dest: str, overwrite: bool) -> bool:
        if not os.path.exists(source):
            return False
        if os.path.exists(dest) and not overwrite:
            return True
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(source, dest)
            return True
        except OSError:
            return False

    def _download_extra_group(
        self,
        images: List[Dict[str, Any]],
        output_dir: str,
        folder: str,
        stem: str,
        extension: str,
        limit: int,
        skip_first: bool,
        overwrite: bool,
    ) -> List[str]:
        if limit <= 0:
            return []

        group_dir = os.path.join(output_dir, "Extra", folder)
        downloaded = []
        candidates = images[1:] if skip_first else images

        for image in candidates[:limit]:
            file_path = image.get("file_path")
            if not file_path:
                continue
            index = len(downloaded) + 1
            filename = f"{stem}-{index:02d}.{extension}"
            dest = os.path.join(group_dir, filename)
            if self.download_image(dest, self._image_url(file_path), overwrite=overwrite):
                downloaded.append(f"Extra/{folder}/{filename}")
        return downloaded

    def download_all_images(
        self,
        media_type: str,
        tmdb_id: int,
        output_dir: str,
        verbose: bool = False,
        extra_images: bool = False,
        image_limits: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> Dict[str, List[str]]:
        """Download available artwork with Emby/Jellyfin-friendly names."""
        images_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/images"
        request_kwargs = self._tmdb_request_kwargs()

        images_data = None
        for attempt in range(3):
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

        posters = images_data.get("posters", []) if images_data else []
        backdrops = images_data.get("backdrops", []) if images_data else []
        logos = images_data.get("logos", []) if images_data else []

        downloaded_images: Dict[str, List[str]] = {}

        if verbose and extra_images:
            total_images = len(posters) + len(backdrops) + len(logos)
            print(f"   获取到图片数据: 共{total_images}张图片")

        if self._download_first(posters, output_dir, "poster.jpg", "poster", downloaded_images, overwrite) and verbose:
            print("   ✓ 设置主海报 (poster.jpg)")

        if self._download_first(backdrops, output_dir, "fanart.jpg", "fanart", downloaded_images, overwrite):
            banner_dest = os.path.join(output_dir, "banner.jpg")
            self._copy_companion(os.path.join(output_dir, "fanart.jpg"), banner_dest, overwrite)
            downloaded_images["banner"] = ["banner.jpg"]
            if verbose:
                print("   ✓ 设置主背景图 (fanart.jpg + banner.jpg)")
        else:
            downloaded_images["banner"] = []

        if self._download_first(logos, output_dir, "clearlogo.png", "logo", downloaded_images, overwrite):
            clearart_dest = os.path.join(output_dir, "clearart.png")
            self._copy_companion(os.path.join(output_dir, "clearlogo.png"), clearart_dest, overwrite)
            downloaded_images["clearart"] = ["clearart.png"]
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
                posters, output_dir, "posters", "poster", "jpg", poster_limit, skip_first=True, overwrite=overwrite
            )
            downloaded_images["backdrop_extra"] = self._download_extra_group(
                backdrops, output_dir, "backdrops", "backdrop", "jpg", backdrop_limit, skip_first=True, overwrite=overwrite
            )
            downloaded_images["logo_extra"] = self._download_extra_group(
                logos, output_dir, "logos", "logo", "png", logo_limit, skip_first=True, overwrite=overwrite
            )

            if media_type == "tv" and still_limit > 0:
                downloaded_images["stills"] = self._download_episode_stills(
                    tmdb_id, output_dir, request_kwargs, still_limit, overwrite, verbose
                )

            if actor_limit > 0:
                downloaded_images["actors"] = self._download_actor_images(
                    media_type, tmdb_id, output_dir, request_kwargs, actor_limit, overwrite, verbose
                )

        if verbose:
            total_downloaded = sum(len(images) for images in downloaded_images.values() if isinstance(images, list))
            print(f"   图片下载完成: 共{total_downloaded}张")

        return downloaded_images

    def _download_episode_stills(
        self,
        tmdb_id: int,
        output_dir: str,
        request_kwargs: Dict[str, Any],
        limit: int,
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
            if len(downloaded) >= limit:
                break
            still_path = episode.get("still_path")
            if not still_path:
                continue
            filename = f"S01E{episode['episode_number']:02d}.jpg"
            dest = os.path.join(stills_dir, filename)
            if self.download_image(dest, self._image_url(still_path), overwrite=overwrite):
                downloaded.append(f"Extra/stills/{filename}")

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
                downloaded.append(f"Extra/actors/{filename}")

        if verbose and downloaded:
            print(f"   ✓ 下载了{len(downloaded)}张演员头像")
        return downloaded
