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

    def download_all_images(self, media_type: str, tmdb_id: int, output_dir: str, verbose: bool = False, extra_images: bool = False) -> Dict[str, List[str]]:
        """Download all available images for a media item with robust error handling and Emby standard naming."""
        # Get images from TMDB with retry logic
        images_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/images"
        params = {"api_key": self.tmdb_api_key}

        images_data = None
        for attempt in range(3):
            try:
                response = self.session.get(images_url, params=params, timeout=30)
                response.raise_for_status()
                images_data = response.json()
                # Only show total images count if extra_images is enabled, since we only use extra images in that case
                if verbose and extra_images:
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

        # Download required images (poster, fanart, logo) - always download these
        # Copy first poster to parent directory as main poster (Emby standard)
        if images_data and 'posters' in images_data and images_data['posters']:
            poster = images_data['posters'][0]  # First poster
            if poster.get('file_path'):
                file_path = poster['file_path']
                if not file_path.startswith('/'):
                    file_path = '/' + file_path
                url = self.base_image_url + file_path
                main_poster_path = os.path.join(output_dir, "poster.jpg")
                if self.download_image(main_poster_path, url):
                    downloaded_images['poster'] = ["poster.jpg"]
                    if verbose:
                        print(f"   ✓ 设置主海报 (poster.jpg)")
                else:
                    downloaded_images['poster'] = []
            else:
                downloaded_images['poster'] = []

        # Copy first fanart/backdrop to parent directory as main fanart (Emby standard)
        if images_data and 'backdrops' in images_data and images_data['backdrops']:
            backdrop = images_data['backdrops'][0]  # First backdrop
            if backdrop.get('file_path'):
                file_path = backdrop['file_path']
                if not file_path.startswith('/'):
                    file_path = '/' + file_path
                url = self.base_image_url + file_path
                main_fanart_path = os.path.join(output_dir, "fanart.jpg")
                banner_path = os.path.join(output_dir, "banner.jpg") if media_type == "tv" else None
                if self.download_image(main_fanart_path, url):
                    downloaded_images['fanart'] = ["fanart.jpg"]
                    # Also create banner.jpg for TV shows (use same image)
                    if banner_path and media_type == "tv":
                        try:
                            import shutil
                            shutil.copy2(main_fanart_path, banner_path)
                        except:
                            pass
                    if verbose:
                        if media_type == "tv":
                            print(f"   ✓ 设置主背景图 (fanart.jpg + banner.jpg)")
                        else:
                            print(f"   ✓ 设置主背景图 (fanart.jpg)")
                else:
                    downloaded_images['fanart'] = []
            else:
                downloaded_images['fanart'] = []

        # Copy first logo to parent directory (Emby standard naming)
        if images_data and 'logos' in images_data and images_data['logos']:
            logo = images_data['logos'][0]  # First logo
            if logo.get('file_path'):
                file_path = logo['file_path']
                if not file_path.startswith('/'):
                    file_path = '/' + file_path
                url = self.base_image_url + file_path
                clearlogo_path = os.path.join(output_dir, "clearlogo.png")
                clearart_path = os.path.join(output_dir, "clearart.png")
                if self.download_image(clearlogo_path, url):
                    downloaded_images['logo'] = ["clearlogo.png"]
                    try:
                        import shutil
                        shutil.copy2(clearlogo_path, clearart_path)
                    except:
                        pass
                    if verbose:
                        print(f"   ✓ 设置主标志 (clearlogo.png + clearart.png)")
                else:
                    downloaded_images['logo'] = []
            else:
                downloaded_images['logo'] = []

        # Download additional images only if extra_images is True
        if extra_images:
            images_dir = os.path.join(output_dir, "Extra")
            os.makedirs(images_dir, exist_ok=True)

            # Download all posters to Extra folder
            if images_data and 'posters' in images_data:
                downloaded_images['poster_extra'] = []
                posters = images_data['posters']
                if verbose and len(posters) > 1:
                    print(f"   下载额外 {len(posters)-1} 张海报")

                for i, poster in enumerate(posters):
                    if i == 0:  # Skip first poster (already downloaded)
                        continue
                    if poster.get('file_path'):
                        file_path = poster['file_path']
                        if not file_path.startswith('/'):
                            file_path = '/' + file_path
                        url = self.base_image_url + file_path
                        filename = f"poster.jpg"
                        filepath = os.path.join(images_dir, filename)
                        try:
                            if self.download_image(filepath, url):
                                downloaded_images['poster_extra'].append(filename)
                        except Exception as e:
                            if verbose:
                                print(f"     ✗ 额外海报 {i+1} 下载失败: {e}")
                            continue

            # Download all backdrops/fanart to Extra folder
            if images_data and 'backdrops' in images_data:
                downloaded_images['fanart_extra'] = []
                downloaded_images['backdrop_extra'] = []
                backdrops = images_data['backdrops']
                if verbose and len(backdrops) > 1:
                    print(f"   下载额外 {len(backdrops)-1} 张背景图")

                for i, backdrop in enumerate(backdrops):
                    if i == 0:  # Skip first backdrop (already downloaded)
                        continue
                    if backdrop.get('file_path'):
                        file_path = backdrop['file_path']
                        if not file_path.startswith('/'):
                            file_path = '/' + file_path
                        url = self.base_image_url + file_path

                        backdrop_filename = f"backdrop.jpg"
                        fanart_filename = f"fanart.jpg"

                        backdrop_filepath = os.path.join(images_dir, backdrop_filename)
                        fanart_filepath = os.path.join(images_dir, fanart_filename)

                        try:
                            if self.download_image(backdrop_filepath, url):
                                downloaded_images['backdrop_extra'].append(backdrop_filename)
                                # Copy the same file for fanart
                                import shutil
                                shutil.copy2(backdrop_filepath, fanart_filepath)
                                downloaded_images['fanart_extra'].append(fanart_filename)
                        except Exception as e:
                            if verbose:
                                print(f"     ✗ 额外背景图 {i+1} 下载失败: {e}")
                            continue

            # Download all logos to Extra folder
            if images_data and 'logos' in images_data:
                downloaded_images['logo_extra'] = []
                logos = images_data['logos']
                if verbose and len(logos) > 1:
                    print(f"   下载额外 {len(logos)-1} 张标志")

                for i, logo in enumerate(logos):
                    if i == 0:  # Skip first logo (already downloaded)
                        continue
                    if logo.get('file_path'):
                        file_path = logo['file_path']
                        if not file_path.startswith('/'):
                            file_path = '/' + file_path
                        url = self.base_image_url + file_path
                        filename = f"logo.png"
                        filepath = os.path.join(images_dir, filename)
                        try:
                            if self.download_image(filepath, url):
                                downloaded_images['logo_extra'].append(filename)
                        except Exception as e:
                            if verbose:
                                print(f"     ✗ 额外标志 {i+1} 下载失败: {e}")
                            continue

        # Create stills subdirectory for TV shows (only if extra_images is True)
        if media_type == 'tv' and extra_images:
            downloaded_images['stills'] = []
            extra_dir = os.path.join(output_dir, "Extra")
            os.makedirs(extra_dir, exist_ok=True)
            stills_dir = os.path.join(extra_dir, "stills")
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
                                episode_stills.append(f"Extra/stills/{filename}")
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

        # Download actor images - directly in root directory (not in actors folder)
        downloaded_images['actors'] = []

        # Get credits data to find actor profile paths
        try:
            credits_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/credits"
            response = self.session.get(credits_url, params={"api_key": self.tmdb_api_key}, timeout=30)
            response.raise_for_status()
            credits_data = response.json()

            actor_images = []
            for actor in credits_data.get('cast', [])[:10]:  # Limit to first 10 actors
                if actor.get('profile_path'):
                    profile_path = actor['profile_path']
                    if not profile_path.startswith('/'):
                        profile_path = '/' + profile_path

                    url = self.base_image_url + profile_path
                    # Use clean actor names directly in root directory
                    actor_name = actor.get('name', 'unknown')
                    actor_name_clean = "".join(c for c in actor_name if c.isalnum() or c in ' _-').strip()
                    actor_name_clean = actor_name_clean.replace(' ', '_')
                    filename = f"{actor_name_clean}.jpg"
                    filepath = os.path.join(output_dir, filename)

                    try:
                        if self.download_image(filepath, url):
                            actor_images.append(filename)
                    except Exception as e:
                        if verbose:
                            print(f"     ✗ 演员头像 {filename} 下载失败: {e}")
                        continue

            downloaded_images['actors'] = actor_images
            if verbose and actor_images:
                print(f"   ✓ 下载了{len(actor_images)}张演员头像到根目录")

        except requests.RequestException as e:
            if verbose:
                print(f"   ✗ 获取演员头像失败: {e}")

        if verbose:
            total_downloaded = sum(len(images) for images in downloaded_images.values() if isinstance(images, list))
            print(f"   图片下载完成: 共{total_downloaded}张")

        return downloaded_images
