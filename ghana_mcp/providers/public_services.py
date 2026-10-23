"""Public services and government entity provider for Ghana.
Searches 1,862 official MDAs, ministries, assemblies, and live government portals.
"""
import os
import json
import re
import urllib.request
import urllib.parse
import ssl
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT
from ghana_mcp.nlp import get_singular_plural_variants

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ghana_agencies.json")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

LIVE_GOV_APIS = [
    {
        "name": "Ghana Revenue Authority (GRA)",
        "base_url": "https://gra.gov.gh",
        "api_url": "https://gra.gov.gh/wp-json/wp/v2/posts?search={q}&per_page={limit}&_fields=id,date,link,title,excerpt",
    },
    {
        "name": "Ghana Standards Authority (GSA)",
        "base_url": "https://www.gsa.gov.gh",
        "api_url": "https://www.gsa.gov.gh/wp-json/wp/v2/posts?search={q}&per_page={limit}&_fields=id,date,link,title,excerpt",
    },
]


def _clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"').replace("&amp;", "&")
    return " ".join(text.split())


class PublicServicesProvider(BaseProvider):
    name = "ghana_public_services"
    category = "public_services"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        self.agencies: List[Dict[str, Any]] = []
        self._load_agencies()

    def _load_agencies(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.agencies = json.load(f)
            except Exception:
                self.agencies = []

    def _search_directory(self, tokens: List[str], limit: int) -> List[SearchResult]:
        """Search the 1,862 verified Ghana government agencies and ministries, supporting singular/plural variants."""
        # Expand each token into its singular and plural forms
        expanded_token_groups = [get_singular_plural_variants(t.lower()) for t in tokens if len(t) > 1]
        if not expanded_token_groups:
            return []

        matches = []
        for ag in self.agencies:
            name = ag.get("name", "")
            alias = ag.get("alias", "")
            category = ag.get("category", "")
            parent = ag.get("parent_ministry", "")
            text = f"{name} {alias} {category} {parent}".lower()

            # Check how many token groups match (via singular or plural)
            match_count = sum(1 for group in expanded_token_groups if any(variant in text for variant in group))
            if match_count > 0:
                score = match_count / len(expanded_token_groups)
                url = ag.get("website_url") or "https://www.ghana.gov.gh"
                snippet_parts = []
                if category:
                    snippet_parts.append(f"Category: {category}")
                if parent:
                    snippet_parts.append(f"Parent: {parent}")
                if ag.get("digital_address"):
                    snippet_parts.append(f"Digital Address: {ag['digital_address']}")
                if ag.get("address"):
                    snippet_parts.append(f"Address: {ag['address']}")

                snippet = ". ".join(snippet_parts) or f"Official government entity: {name}"

                matches.append(
                    (
                        score,
                        SearchResult(
                            title=name,
                            url=url,
                            snippet=snippet,
                            source="Ghana Government Directory",
                            category=self.category,
                            score=score,
                            metadata={
                                "alias": alias,
                                "category": category,
                                "parent_ministry": parent,
                                "digital_address": ag.get("digital_address"),
                            },
                        ),
                    )
                )

        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches[:limit]]

    def _search_live_portal(self, portal: Dict[str, str], query: str, limit: int) -> List[SearchResult]:
        """Search live government portals with open REST APIs (e.g. GRA, GSA)."""
        url = portal["api_url"].format(q=urllib.parse.quote(query), limit=limit)
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8-sig", errors="ignore"))
            if not isinstance(data, list):
                return []
            results = []
            for post in data[:limit]:
                title = _clean_html(post.get("title", {}).get("rendered", ""))
                excerpt = _clean_html(post.get("excerpt", {}).get("rendered", ""))
                link = post.get("link", "")
                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        snippet=excerpt,
                        source=portal["name"],
                        category=self.category,
                        published_date=post.get("date"),
                    )
                )
            return results

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        tokens = [t.lower() for t in keywords if len(t) > 1]
        if not tokens:
            return []

        query = " ".join(tokens)
        results = self._search_directory(tokens, limit)

        # Check live government portal APIs concurrently
        with ThreadPoolExecutor(max_workers=len(LIVE_GOV_APIS)) as executor:
            future_to_portal = {
                executor.submit(self._search_live_portal, p, query, 3): p["name"]
                for p in LIVE_GOV_APIS
            }
            for future in future_to_portal:
                try:
                    live_res = future.result()
                    if live_res:
                        results.extend(live_res)
                except Exception:
                    pass

        return results[: limit * 2]
