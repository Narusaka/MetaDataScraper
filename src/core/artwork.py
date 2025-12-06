import requests
import os
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
import time


class ArtworkDownloader:
    def __init__(self, tmdb_api_key: str, proxy: Optional[Dict[str, str]] = None):
        self.tmdb_api_key = tmdb_api_key
        self.proxy = proxy
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update(proxy)
        self.base_image_url = "https://image.tmdb.org/t/p/original"

    def download_image(self, image_path: str, url: str, max_retries: int = 3) -> bool:
        """Download a single image with retry logic."""
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30, stream=True)
                response.raise_for_status()

                os.makedirs(os.path.dirname(image_path), exist_ok=True)
                with open(image_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
            except requests.exceptions.SSLError as e:
                # If SSL error occurs, try with verify=False
                if attempt == 0:  # Only try once with verify=False
                    try:
                        response = self.session.get(url, timeout=30, stream=True, verify=False)
                        response.raise_for_status()

                        os.makedirs(os.path.dirname(image_path), exist_ok=True)
                        with open(image_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        return True
                    except requests.RequestException as e2:
                        print(f"SSL error, retry with verify=False also failed for {url}: {e2}")
                        continue
                else:
                    continue
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"Failed to download {url}: {e}")
                    return False
                print(f"Retry {attempt + 1}/{max_retries} for {url}")
                time.sleep(1)  # Wait before retry
        return False

    def download_all_images(self, media_type: str, tmdb_id: int, output_dir: str, verbose: bool = False) -> Dict[str, List[str]]:
        """Download all available images for a media item with robust error handling and Emby standard naming."""
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        # Get images from TMDB with retry logic
        images_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/images"
        params = {"api_key": self.tmdb_api_key}

        images_data = None
        for attempt in range(3):
            try:
                response = self.session.get(images_url, params=params, timeout=30)
                response.raise_for_status()
                images_data = response.json()
                if verbose:
                    total_images = len(images_data.get('posters', [])) + len(images_data.get('backdrops', [])) + len(images_data.get('logos', []))
                    print(f"   获取到图片数据: 共{total_images}张图片")
                break
            except requests.RequestException as e:
                if attempt == 2:
                    if verbose:
                        print(f"Failed to get images for {media_type} {tmdb_id}: {e}")
                    return {}
                if verbose:
                    print(f"Retry {attempt + 1}/3 for images API")
                time.sleep(1)

        downloaded_images = {}

        # Download all posters
        if images_data and 'posters' in images_data:
            downloaded_images['poster'] = []
            posters = images_data['posters']
            if verbose:
                print(f"   下载 {len(posters)} 张海报")

            for i, poster in enumerate(posters):
                if poster.get('file_path'):
                    file_path = poster['file_path']
                    if not file_path.startswith('/'):
                        file_path = '/' + file_path
                    url = self.base_image_url + file_path
                    filename = f"poster{i+1}.jpg"
                    filepath = os.path.join(images_dir, filename)
                    try:
                        if self.download_image(filepath, url):
                            downloaded_images['poster'].append(filename)
                            # Copy first poster to parent directory as main poster (Emby standard)
                            if i == 0:
                                parent_dir = os.path.dirname(images_dir)
                                main_poster_path = os.path.join(parent_dir, "poster.jpg")
                                try:
                                    import shutil
                                    shutil.copy2(filepath, main_poster_path)
                                    if verbose:
                                        print(f"   ✓ 设置主海报 (poster.jpg)")
                                except Exception as e:
                                    if verbose:
                                        print(f"   ✗ 复制主海报失败: {e}")
                    except Exception as e:
                        if verbose:
                            print(f"     ✗ 海报 {i+1} 下载失败: {e}")
                        continue

        # Download all backdrops/fanart
        if images_data and 'backdrops' in images_data:
            downloaded_images['fanart'] = []
            downloaded_images['backdrop'] = []
            backdrops = images_data['backdrops']
            if verbose:
                print(f"   下载 {len(backdrops)} 张背景图")

            for i, backdrop in enumerate(backdrops):
                if backdrop.get('file_path'):
                    file_path = backdrop['file_path']
                    if not file_path.startswith('/'):
                        file_path = '/' + file_path
                    url = self.base_image_url + file_path

                    backdrop_filename = f"backdrop{i+1}.jpg"
                    fanart_filename = f"fanart{i+1}.jpg"

                    backdrop_filepath = os.path.join(images_dir, backdrop_filename)
                    fanart_filepath = os.path.join(images_dir, fanart_filename)

                    try:
                        if self.download_image(backdrop_filepath, url):
                            downloaded_images['backdrop'].append(backdrop_filename)
                            # Copy the same file for fanart
                            import shutil
                            shutil.copy2(backdrop_filepath, fanart_filepath)
                            downloaded_images['fanart'].append(fanart_filename)

                            # Copy first fanart to parent directory as main fanart (Emby standard)
                            if i == 0:
                                parent_dir = os.path.dirname(images_dir)
                                main_fanart_path = os.path.join(parent_dir, "fanart.jpg")
                                # Also create banner.jpg for TV shows (use same image)
                                banner_path = os.path.join(parent_dir, "banner.jpg") if media_type == "tv" else None
                                try:
                                    shutil.copy2(fanart_filepath, main_fanart_path)
                                    if banner_path and media_type == "tv":
                                        shutil.copy2(fanart_filepath, banner_path)
                                    if verbose:
                                        if media_type == "tv":
                                            print(f"   ✓ 设置主背景图 (fanart.jpg + banner.jpg)")
                                        else:
                                            print(f"   ✓ 设置主背景图 (fanart.jpg)")
                                except Exception as e:
                                    if verbose:
                                        print(f"   ✗ 复制主背景图失败: {e}")
                    except Exception as e:
                        if verbose:
                            print(f"     ✗ 背景图 {i+1} 下载失败: {e}")
                        continue

        # Download all logos
        if images_data and 'logos' in images_data:
            downloaded_images['logo'] = []
            logos = images_data['logos']
            if verbose:
                print(f"   下载 {len(logos)} 张标志")

            for i, logo in enumerate(logos):
                if logo.get('file_path'):
                    file_path = logo['file_path']
                    if not file_path.startswith('/'):
                        file_path = '/' + file_path
                    url = self.base_image_url + file_path
                    filename = f"logo{i+1}.png"
                    filepath = os.path.join(images_dir, filename)
                    try:
                        if self.download_image(filepath, url):
                            downloaded_images['logo'].append(filename)

                            # Copy first logo to parent directory (Emby standard naming)
                            if i == 0:
                                parent_dir = os.path.dirname(images_dir)
                                # Emby standard: clearlogo.png for transparent logo
                                clearlogo_path = os.path.join(parent_dir, "clearlogo.png")
                                # Also create clearart.png (same image)
                                clearart_path = os.path.join(parent_dir, "clearart.png")
                                try:
                                    import shutil
                                    shutil.copy2(filepath, clearlogo_path)
                                    shutil.copy2(filepath, clearart_path)
                                    if verbose:
                                        print(f"   ✓ 设置主标志 (clearlogo.png + clearart.png)")
                                except Exception as e:
                                    if verbose:
                                        print(f"   ✗ 复制主标志失败: {e}")
                    except Exception as e:
                        if verbose:
                            print(f"     ✗ 标志 {i+1} 下载失败: {e}")
                        continue

        # Create stills subdirectory for TV shows
        if media_type == 'tv':
            downloaded_images['stills'] = []
            stills_dir = os.path.join(images_dir, "stills")
            os.makedirs(stills_dir, exist_ok=True)

            # Get episode stills for the first season
            try:
                episodes_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/1"
                response = self.session.get(episodes_url, params={"api_key": self.tmdb_api_key}, timeout=30)
                response.raise_for_status()
                season_data = response.json()

                episode_stills = []
                for episode in season_data.get('episodes', [])[:5]:  # Limit to first 5 episodes
                    if episode.get('still_path'):
                        still_path = episode['still_path']
                        if not still_path.startswith('/'):
                            still_path = '/' + still_path
                        url = self.base_image_url + still_path
                        filename = f"S01E{episode['episode_number']:02d}.jpg"
                        filepath = os.path.join(stills_dir, filename)
                        try:
                            if self.download_image(filepath, url):
                                episode_stills.append(f"stills/{filename}")
                        except Exception as e:
                            if verbose:
                                print(f"     ✗ 剧集截图 {filename} 下载失败: {e}")
                            continue

                downloaded_images['stills'] = episode_stills
                if verbose and episode_stills:
                    print(f"   ✓ 下载了 {len(episode_stills)} 张剧集截图")

            except requests.RequestException as e:
                if verbose:
                    print(f"   ✗ 获取剧集截图失败: {e}")

        # Download actor images (Emby standard: actors in root ./actors/ directory)
        downloaded_images['actors'] = []
        # For both TV and movies, put actors in root actors directory (Emby recommended)
        # This avoids duplication across seasons and follows Emby best practices
        actors_dir = os.path.join(output_dir, "actors")
        os.makedirs(actors_dir, exist_ok=True)

        # Get credits data to find actor profile paths
        try:
            credits_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/credits"
            response = self.session.get(credits_url, params={"api_key": self.tmdb_api_key}, timeout=30)
            response.raise_for_status()
            credits_data = response.json()

            actor_images = []
            for actor in credits_data.get('cast', []):  # Download all available actor images
                if actor.get('profile_path'):
                    profile_path = actor['profile_path']
                    if not profile_path.startswith('/'):
                        profile_path = '/' + profile_path

                    url = self.base_image_url + profile_path
                    # Emby standard: use underscores for actor names
                    actor_name = actor.get('name', 'unknown')
                    actor_name_clean = "".join(c for c in actor_name if c.isalnum() or c in ' _-').strip()
                    actor_name_clean = actor_name_clean.replace(' ', '_')  # Emby standard: underscores
                    filename = f"{actor_name_clean}.jpg"
                    filepath = os.path.join(actors_dir, filename)

                    try:
                        if self.download_image(filepath, url):
                            # Both TV and movies use root ./actors/ directory (Emby standard)
                            actor_images.append(f"./actors/{filename}")
                    except Exception as e:
                        if verbose:
                            print(f"     ✗ 演员头像 {filename} 下载失败: {e}")
                        continue

            downloaded_images['actors'] = actor_images
            if verbose and actor_images:
                print(f"   ✓ 下载了 {len(actor_images)} 张演员头像")

        except requests.RequestException as e:
            if verbose:
                print(f"   ✗ 获取演员头像失败: {e}")

        if verbose:
            total_downloaded = sum(len(images) for images in downloaded_images.values() if isinstance(images, list))
            print(f"   图片下载完成: 共{total_downloaded}张")

        return downloaded_images
