"""Wikipedia search provider tailored for Ghana-focused knowledge and geotagged places."""
import json
import urllib.request
import urllib.parse
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary"

FOREIGN_COUNTRIES = {
    "kenya", "nigeria", "uganda", "tanzania", "south africa", "zimbabwe",
    "zambia", "rwanda", "cameroon", "liberia", "sierra leone", "senegal",
    "ivory coast", "côte d'ivoire", "togo", "benin", "mali", "niger",
    "burkina faso", "ethiopia", "somalia", "sudan", "egypt", "angola",
    "mozambique", "botswana", "namibia", "malawi", "gambia", "congo"
}


def is_ghana_wiki_article(title: str, extract: str) -> bool:
    """Validate that Wikipedia article strictly pertains to Ghana and not another nation."""
    tl = title.lower()
    el = (extract or "").lower()

    # Reject if another country is in the title unless Ghana is also explicitly in the title
    for country in FOREIGN_COUNTRIES:
        if country in tl and "ghana" not in tl:
            return False

    # Reject if summary explicitly focuses on another country's government/institutions without Ghana
    for country in FOREIGN_COUNTRIES:
        if (f"government of {country}" in el or f"president of {country}" in el or f"in {country}" in el) and "ghana" not in el:
            return False

    return True


class WikipediaGhanaProvider(BaseProvider):
    name = "wikipedia_ghana"
    category = "wikipedia"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    def _fetch_page_summary(self, title: str) -> dict:
        """Fetch extract summary for a Wikipedia article."""
        url = f"{WIKI_REST_SUMMARY}/{urllib.parse.quote(title.replace(' ', '_'))}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {}

    def _cirrus_search(self, query: str, limit: int) -> List[SearchResult]:
        """Perform CirrusSearch strictly scoped to Category:Ghana and subcategories."""
        # Use deepcat:"Ghana" to strictly confine Wikipedia results to the Ghanaian category tree
        search_term = f'{query} deepcat:"Ghana"'
        params = {
            "action": "query",
            "list": "search",
            "srsearch": search_term,
            "srlimit": min(limit * 2, 20),
            "format": "json",
            "utf8": 1,
        }
        url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("query", {}).get("search", [])

        results = []
        # Fetch summary extracts for matches in parallel
        titles = [item["title"] for item in items[:limit * 2]]
        summaries = {}
        with ThreadPoolExecutor(max_workers=min(len(titles), 5) or 1) as executor:
            future_to_title = {executor.submit(self._fetch_page_summary, t): t for t in titles}
            for future in as_completed(future_to_title):
                t = future_to_title[future]
                try:
                    summaries[t] = future.result()
                except Exception:
                    summaries[t] = {}

        for item in items:
            title = item["title"]
            sum_data = summaries.get(title, {})
            extract = sum_data.get("extract")
            if not extract:
                raw_snippet = item.get("snippet", "")
                extract = raw_snippet.replace('<span class="searchmatch">', "").replace("</span>", "")

            # Strict Ghana validation: exclude non-Ghana articles
            if not is_ghana_wiki_article(title, extract):
                continue

            desktop_url = sum_data.get("content_urls", {}).get("desktop", {}).get("page")
            if not desktop_url:
                desktop_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"

            results.append(
                SearchResult(
                    title=title,
                    url=desktop_url,
                    snippet=extract,
                    source="Wikipedia (Ghana)",
                    category=self.category,
                    content=extract,
                    metadata={"pageid": item.get("pageid")},
                )
            )
            if len(results) >= limit:
                break
        return results

    def _geosearch_ghana(self, limit: int = 3) -> List[SearchResult]:
        """Search nearby landmark pages in Accra / Ghana."""
        # Accra coordinates: 5.6037 N, 0.1870 W
        params = {
            "action": "query",
            "list": "geosearch",
            "gscoord": "5.6037|-0.1870",
            "gsradius": "10000",
            "gslimit": limit,
            "format": "json",
            "utf8": 1,
        }
        url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("query", {}).get("geosearch", [])

        results = []
        for item in items:
            title = item["title"]
            results.append(
                SearchResult(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                    snippet=f"Geotagged location in Accra, Ghana (Lat: {item.get('lat')}, Lon: {item.get('lon')})",
                    source="Wikipedia (Geotagged Ghana)",
                    category=self.category,
                    metadata={"lat": item.get("lat"), "lon": item.get("lon"), "pageid": item.get("pageid")},
                )
            )
        return results

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        query = " ".join(keywords).strip()
        if not query:
            return self._geosearch_ghana(limit=limit)

        try:
            return self._cirrus_search(query, limit)
        except Exception:
            return []
