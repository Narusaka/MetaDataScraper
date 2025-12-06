import requests
import re
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus
import time
import os


class GoogleSearchAdapter:
    def __init__(self, proxy: Optional[Dict[str, str]] = None, api_key: Optional[str] = None, search_engine_id: Optional[str] = None, quiet: bool = False):
        self.proxy = proxy
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY')
        self.search_engine_id = search_engine_id or os.getenv('GOOGLE_SEARCH_ENGINE_ID')

        self.session = requests.Session()
        if proxy and not quiet:
            self.session.proxies.update(proxy)
            print(f"   使用代理: {proxy}")
        elif proxy and quiet:
            self.session.proxies.update(proxy)

        # 检查是否配置了Google API
        if self.api_key and self.search_engine_id:
            if not quiet:
                print("   Google Custom Search API 已配置")
            self.use_api = True
        else:
            if not quiet:
                print("   Google Custom Search API 未配置，使用网页爬取模式")
            self.use_api = False

            # 使用一个现代的浏览器用户代理，模拟支持 JS 的环境
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
            })

    def search_tmdb_id(self, query: str, media_type: str = "movie", max_results: int = 3, verbose: bool = False) -> Optional[str]:
        """
        通过谷歌搜索找到 TMDB ID

        Args:
            query: 搜索查询（电影/电视剧名称）
            media_type: 媒体类型 ('movie' 或 'tv')
            max_results: 最大搜索结果数量

        Returns:
            TMDB ID 字符串，如果找不到则返回 None
        """
        if self.use_api:
            return self._search_with_api(query, media_type, max_results, verbose)
        else:
            return self._search_with_crawler(query, media_type, max_results, verbose)

    def _search_with_api(self, query: str, media_type: str = "movie", max_results: int = 3, verbose: bool = False) -> Optional[str]:
        """
        使用 Google Custom Search API 进行搜索
        """
        try:
            from googleapiclient.discovery import build
        except ImportError:
            if verbose:
                print("   Google API 客户端库未安装，无法使用 API 模式")
            return None

        if verbose:
            print(f"   使用 Google Custom Search API 搜索: '{query} tmdb'")

        try:
            service = build("customsearch", "v1", developerKey=self.api_key)
            search_query = f"{query} tmdb site:themoviedb.org"

            result = service.cse().list(
                q=search_query,
                cx=self.search_engine_id,
                num=max_results
            ).execute()

            items = result.get('items', [])
            if verbose:
                print(f"   API 返回 {len(items)} 个结果")

            for item in items:
                link = item.get('link', '')
                if verbose:
                    print(f"   检查链接: {link}")

                # 查找 TMDB 链接
                if f'themoviedb.org/{media_type}/' in link:
                    # 从 URL 中提取 ID
                    id_match = re.search(rf'/({media_type})/(\d+)', link)
                    if id_match:
                        tmdb_id = id_match.group(2)
                        if verbose:
                            print(f"   通过 API 找到 {media_type} ID: {tmdb_id}")
                        return tmdb_id

        except Exception as e:
            if verbose:
                print(f"   Google API 搜索失败: {e}")
            return None

        return None

    def _search_with_crawler(self, query: str, media_type: str = "movie", max_results: int = 3, verbose: bool = False) -> Optional[str]:
        """
        使用网页爬虫进行搜索（需要 JavaScript 支持）
        """
        if verbose:
            print("   使用网页爬虫模式（需要 JavaScript 支持）")

        # 构建搜索查询
        search_query = f"{query} tmdb"
        encoded_query = quote_plus(search_query)

        # 构建谷歌搜索URL
        search_url = f"https://www.google.com/search?q={encoded_query}&num={max_results}"

        # 尝试多种方法访问谷歌
        for attempt in range(2):
            try:
                # 使用不同的 headers 来模拟正常浏览器
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }

                response = self.session.get(search_url, headers=headers, timeout=15)
                response.raise_for_status()

                # 检查是否返回了 noscript 页面（谷歌的反爬虫措施）
                if '<noscript>' in response.text or 'enablejs' in response.text:
                    if verbose:
                        print("   谷歌检测到无 JavaScript 环境，返回 noscript 页面")
                        print("   提示：谷歌搜索需要 JavaScript 支持，当前环境不支持")
                        print("   建议：配置 Google Custom Search API 以获得更好的支持")
                    # 返回 None 表示无法搜索
                    return None

                if verbose:
                    print(f"   搜索关键词: '{search_query}'")
                    print(f"   响应状态码: {response.status_code}")
                    print(f"   响应内容长度: {len(response.text)} 字符")

                # 解析搜索结果中的 TMDB 链接
                tmdb_id = self._extract_tmdb_id_from_html(response.text, media_type, verbose)

                if tmdb_id:
                    return tmdb_id

            except requests.RequestException as e:
                if attempt == 1:  # 最后一次尝试失败
                    if verbose:
                        print(f"   网页爬虫搜索失败: {e}")
                    # 静默失败，不打印错误信息，因为这是备选方案
                    pass
                else:
                    # 短暂等待后重试
                    time.sleep(1)

        return None

    def _extract_tmdb_id_from_html(self, html: str, media_type: str, verbose: bool = False) -> Optional[str]:
        """
        从谷歌搜索结果HTML中提取 TMDB ID

        Args:
            html: 搜索结果的HTML内容
            media_type: 媒体类型 ('movie' 或 'tv')
            verbose: 是否显示详细调试信息

        Returns:
            TMDB ID 字符串
        """
        if verbose:
            print(f"   开始解析 HTML 内容 (长度: {len(html)})...")

            # 显示前三个搜索结果链接
            search_results = self._extract_search_results(html)
            if search_results:
                print("   前三个搜索结果:")
                for i, result in enumerate(search_results[:3], 1):
                    print(f"     {i}. {result['title']}")
                    print(f"        {result['url']}")
            else:
                print("   未找到搜索结果链接")

        # 首先查找所有 TMDB 相关的 URL
        all_tmdb_urls = re.findall(r'https://www\.themoviedb\.org/[a-zA-Z]+/\d+', html)

        if verbose:
            print(f"   找到的 TMDB URLs: {len(all_tmdb_urls)}")
            for i, url in enumerate(all_tmdb_urls[:5]):  # 只显示前5个
                print(f"     {i+1}: {url}")

        # 查找匹配媒体类型的 URL
        for url in all_tmdb_urls:
            if f'/{media_type}/' in url:
                # 从 URL 中提取 ID
                id_match = re.search(rf'/{media_type}/(\d+)', url)
                if id_match:
                    tmdb_id = id_match.group(1)
                    if verbose:
                        print(f"   匹配到 {media_type} ID: {tmdb_id}")
                    return tmdb_id

        # 如果没找到精确匹配，尝试更宽泛的搜索
        # 查找任何包含查询关键词和 TMDB 的 URL
        broader_patterns = [
            r'https://www\.themoviedb\.org/movie/\d+',  # 总是尝试 movie
            r'https://www\.themoviedb\.org/tv/\d+',     # 总是尝试 tv
        ]

        for pattern in broader_patterns:
            matches = re.findall(pattern, html)
            if matches:
                # 提取第一个匹配的 ID
                for match in matches:
                    id_match = re.search(r'/(\d+)', match)
                    if id_match:
                        tmdb_id = id_match.group(1)
                        if verbose:
                            print(f"   通过宽泛搜索找到 ID: {tmdb_id}")
                        return tmdb_id

        if verbose:
            print("   未找到任何 TMDB ID")

        return None

    def _extract_search_results(self, html: str) -> List[Dict[str, str]]:
        """
        从谷歌搜索结果HTML中提取搜索结果

        Args:
            html: 搜索结果的HTML内容

        Returns:
            搜索结果列表，每个包含 title 和 url
        """
        results = []

        # 尝试多种解析模式
        patterns = [
            # 模式1：标准谷歌搜索结果
            r'<h3[^>]*class="[^"]*LC20lb[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>.*?</h3>',
            # 模式2：简化的链接提取
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]{10,80})</a>',
            # 模式3：查找所有有效的HTTP链接和标题
            r'<div[^>]*class="[^"]*g[^"]*"[^>]*>.*?href="([^"]+)"[^>]*>([^<]+)</.*?/div>',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    url, title = match
                else:
                    continue

                # 清理URL
                if url.startswith('/url?q='):
                    url = url[7:].split('&')[0]  # 提取实际URL

                # 解码URL编码
                url = url.replace('%3A', ':').replace('%2F', '/').replace('%3F', '?').replace('%3D', '=')

                # 清理标题
                title = re.sub(r'<[^>]+>', '', title).strip()

                # 过滤有效的搜索结果
                if (url.startswith('http') and
                    len(title) > 5 and
                    not url.startswith('https://www.google.com') and
                    not 'google' in url.lower()):

                    results.append({
                        'title': title,
                        'url': url
                    })

                    if len(results) >= 5:  # 限制结果数量
                        break

            if results:
                break

        # 如果还是没找到，尝试最简单的链接提取
        if not results:
            # 查找所有包含 "url?q=" 的谷歌重定向链接
            google_links = re.findall(r'/url\?q=([^&]+)&[^"]*">([^<]+)</a>', html, re.IGNORECASE)
            for url, title in google_links:
                title = re.sub(r'<[^>]+>', '', title).strip()
                # 解码 URL
                decoded_url = url.replace('%3A', ':').replace('%2F', '/').replace('%3F', '?')
                if decoded_url.startswith('http') and len(title) > 3:
                    results.append({
                        'title': title,
                        'url': decoded_url
                    })

            # 如果还没找到，尝试查找所有有效的链接
            if not results:
                all_links = re.findall(r'href="([^"]+)"[^>]*>([^<]{5,100})</a>', html, re.IGNORECASE)
                for url, title in all_links[:15]:  # 增加数量限制
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    if url.startswith('http') and len(title) > 3 and 'google' not in url.lower():
                        results.append({
                            'title': title,
                            'url': url
                        })

        return results[:5]  # 返回前5个结果
