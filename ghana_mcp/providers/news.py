"""News search provider for top Ghanaian online news platforms."""
import re
import json
import time
import urllib.request
import urllib.parse
import ssl
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

# Setup permissive SSL context for news websites
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def _clean_html(text: str) -> str:
    """Strip HTML tags and unescape common HTML entities."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&#8217;", "'")
        .replace("&#8216;", "'")
        .replace("&#8220;", '"')
        .replace("&#8221;", '"')
        .replace("&#8211;", "–")
        .replace("&#8212;", "—")
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
    )
    return " ".join(text.split())


class NewsProvider(BaseProvider):
    name = "ghana_news"
    category = "news"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        }

    def _fetch_bft(self, query: str, limit: int) -> List[SearchResult]:
        """Fetch from B&FT Online (Next.js / Payload CMS API)."""
        url = f"https://thebftonline.com/api/search?query={urllib.parse.quote(query)}&page=1"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            results = []
            for doc in data.get("docs", [])[:limit]:
                slug = doc.get("slug", "")
                link = f"https://thebftonline.com/{slug}" if slug else "https://thebftonline.com"
                excerpt = doc.get("excerpt", "").strip()
                results.append(
                    SearchResult(
                        title=doc.get("title", "").strip(),
                        url=link,
                        snippet=excerpt,
                        source="B&FT Online",
                        category=self.category,
                        content=excerpt,
                        published_date=doc.get("publishedAt"),
                        metadata={"read_time": doc.get("readTime"), "category": doc.get("category", {}).get("name")},
                    )
                )
            return results

    def _fetch_3news(self, query: str, limit: int) -> List[SearchResult]:
        """Fetch from 3News (Media General / TV3 Next.js API)."""
        url = f"https://3news.com/api/search?q={urllib.parse.quote(query)}&per_page={limit}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            results = []
            for item in data.get("results", [])[:limit]:
                raw_url = item.get("url", "")
                link = f"https://3news.com{raw_url}" if raw_url.startswith("/") else raw_url
                snippet = f"3News breaking report on {item.get('title', '').strip()}"
                results.append(
                    SearchResult(
                        title=item.get("title", "").strip(),
                        url=link,
                        snippet=snippet,
                        source="3News (TV3)",
                        category=self.category,
                        content=snippet,
                        metadata={"item_id": item.get("id"), "type": item.get("type")},
                    )
                )
            return results

    def _fetch_yen(self, query: str, limit: int) -> List[SearchResult]:
        """Fetch from Yen.com.gh (AJAX endpoint)."""
        url = f"https://yen.com.gh/ajax/search/?query={urllib.parse.quote(query)}"
        headers = dict(self.headers)
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = f"https://yen.com.gh/search/?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            html_chunk = data.get("response", "")
            if not html_chunk:
                return []
            soup = BeautifulSoup(html_chunk, "html.parser")
            articles = soup.find_all("article")
            results = []
            for art in articles[:limit]:
                a_tag = art.find("a", class_=lambda c: c and "title" in c) or art.find("a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                link = a_tag.get("href", "")
                time_tag = art.find("time")
                date_str = time_tag.get_text(strip=True) if time_tag else None
                snippet_tag = art.find("p") or art.find("span")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else f"Report from Yen.com.gh: {title}"
                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        snippet=snippet,
                        source="Yen.com.gh",
                        category=self.category,
                        content=snippet,
                        published_date=date_str,
                    )
                )
            return results

    def _fetch_wp_endpoint(self, source_name: str, base_url: str, query: str, limit: int) -> List[SearchResult]:
        """Generic fetcher for WordPress REST APIs with full content extraction."""
        url = (
            f"{base_url}/wp-json/wp/v2/posts?search={urllib.parse.quote(query)}"
            f"&per_page={limit}&_fields=id,date,link,title,excerpt,content"
        )
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            raw = resp.read().decode("utf-8-sig", errors="ignore")
            posts = json.loads(raw)
            if not isinstance(posts, list):
                return []
            results = []
            for post in posts[:limit]:
                title = _clean_html(post.get("title", {}).get("rendered", ""))
                excerpt = _clean_html(post.get("excerpt", {}).get("rendered", ""))
                full_content = _clean_html(post.get("content", {}).get("rendered", ""))
                body_text = full_content if len(full_content) > 50 else excerpt
                link = post.get("link", "")
                date_str = post.get("date", "")
                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        snippet=excerpt,
                        source=source_name,
                        category=self.category,
                        content=body_text,
                        published_date=date_str,
                        metadata={"post_id": post.get("id")},
                    )
                )
            return results

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        """Search all queryable Ghanaian news outlets concurrently."""
        query = " ".join(keywords).strip()
        if not query:
            return []

        # List of endpoints to query in parallel
        tasks = [
            ("bft", lambda: self._fetch_bft(query, limit)),
            ("3news", lambda: self._fetch_3news(query, limit)),
            ("yen", lambda: self._fetch_yen(query, limit)),
            ("citi", lambda: self._fetch_wp_endpoint("Citi Newsroom", "https://citinewsroom.com", query, limit)),
            ("gna", lambda: self._fetch_wp_endpoint("Ghana News Agency (GNA)", "https://gna.org.gh", query, limit)),
            ("chronicle", lambda: self._fetch_wp_endpoint("The Chronicle", "https://thechronicle.com.gh", query, limit)),
            ("gbn", lambda: self._fetch_wp_endpoint("Ghana Business News", "https://www.ghanabusinessnews.com", query, limit)),
            ("starrfm", lambda: self._fetch_wp_endpoint("Starr FM Online", "https://starrfm.com.gh", query, limit)),
        ]

        all_results = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_to_source = {executor.submit(fn): name for name, fn in tasks}
            for future in as_completed(future_to_source):
                src = future_to_source[future]
                try:
                    res = future.result()
                    if res:
                        all_results.extend(res)
                except Exception:
                    # Ignore individual source failures so the rest return quickly
                    pass

        return all_results
