"""Public services and government entity content search provider for Ghana.
Directly queries the live search APIs of 164 verified Ghanaian government portals,
ministries, departments, and agencies, returning direct URLs to specific content,
reports, policies, and public services (NOT generic homepages).
"""
import os
import json
import re
import urllib.request
import urllib.parse
import ssl
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT
from ghana_mcp.nlp import get_singular_plural_variants

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

VERIFIED_APIS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "verified_gov_apis.json"
)

# Core national government portals with verified live search APIs
CORE_NATIONAL_GOV_APIS = [
    {
        "name": "Ghana Revenue Authority (GRA)",
        "posts_api": "https://gra.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["tax", "taxes", "vat", "customs", "revenue", "income", "tin", "duties"],
    },
    {
        "name": "Ministry of Lands and Natural Resources",
        "posts_api": "https://mlnr.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["mining", "galamsey", "forestry", "timber", "lands", "natural resources", "minerals"],
    },
    {
        "name": "Minerals Income Investment Fund (MIIF)",
        "posts_api": "https://miif.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["mining", "gold", "minerals", "lithium", "royalties", "investment"],
    },
    {
        "name": "Food and Drugs Authority (FDA)",
        "posts_api": "https://fdaghana.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["food", "drugs", "cosmetics", "medical", "counterfeit", "health", "safety"],
    },
    {
        "name": "Ghana Standards Authority (GSA)",
        "posts_api": "https://gsa.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["standards", "certification", "inspection", "quality", "metrology"],
    },
    {
        "name": "Lands Commission",
        "posts_api": "https://www.lc.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["land", "title", "deed", "registration", "survey", "lease"],
    },
    {
        "name": "Ghana Investment Promotion Centre (GIPC)",
        "posts_api": "https://gipa.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["investment", "invest", "business", "foreign", "investors", "economy"],
    },
    {
        "name": "Ghana Free Zones Authority (GFZA)",
        "posts_api": "https://gfza.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["free zones", "export", "manufacturing", "trade", "enterprise"],
    },
    {
        "name": "Ghana Grid Company Limited (GRIDCo)",
        "posts_api": "https://gridcogh.com/wp-json/wp/v2/posts",
        "keywords": ["power", "electricity", "grid", "energy", "transmission"],
    },
    {
        "name": "Ministry of Gender, Children & Social Protection",
        "posts_api": "https://www.mogcsp.gov.gh/wp-json/wp/v2/posts",
        "keywords": ["gender", "children", "social", "protection", "women", "welfare", "leap"],
    },
]


def _clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&#8217;", "'")
        .replace("&#8216;", "'")
        .replace("&#8220;", '"')
        .replace("&#8221;", '"')
        .replace("&#8211;", "–")
        .replace("&amp;", "&")
        .replace("&nbsp;", " ")
    )
    return " ".join(text.split())


class PublicServicesProvider(BaseProvider):
    name = "ghana_public_services"
    category = "public_services"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        self.verified_apis: List[Dict[str, Any]] = []
        self._load_apis()

    def _load_apis(self):
        if os.path.exists(VERIFIED_APIS_FILE):
            try:
                with open(VERIFIED_APIS_FILE, "r", encoding="utf-8") as f:
                    self.verified_apis = json.load(f)
            except Exception:
                self.verified_apis = []

    def _search_ghanadistricts(self, query: str, limit: int = 5) -> List[SearchResult]:
        """Search https://www.ghanadistricts.com for district assembly news and reports."""
        url = "https://www.ghanadistricts.com/Home/SearchData"
        headers = dict(self.headers)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Referer"] = "https://www.ghanadistricts.com/Home/News"

        data = urllib.parse.urlencode({"SearchInput": query}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
                from bs4 import BeautifulSoup
                html = resp.read().decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html, "html.parser")

            results = []
            rows = soup.find_all("tr")
            for row in rows:
                tds = row.find_all("td")
                if len(tds) >= 2:
                    a_tag = row.find("a", href=True)
                    if a_tag and "Reader" in a_tag["href"]:
                        href = a_tag["href"]
                        link = f"https://www.ghanadistricts.com{href if href.startswith('/') else '/' + href}"
                        texts = [td.get_text(strip=True) for td in tds if td.get_text(strip=True) and td.get_text(strip=True) != "Read News"]
                        title = texts[0] if texts else "District Assembly Report"
                        # Skip header rows
                        if "Page 1 of" in title or "Loading" in title:
                            continue
                        date_str = texts[1][:10] if len(texts) > 1 else None

                        results.append(
                            SearchResult(
                                title=title,
                                url=link,  # Direct Reader Content URL
                                snippet=f"Official local government report from GhanaDistricts: {title}",
                                source="GhanaDistricts Repository (261 MMDAs)",
                                category=self.category,
                                published_date=date_str,
                                metadata={"type": "district assembly news / local governance"},
                            )
                        )
                        if len(results) >= limit:
                            break
            return results
        except Exception:
            return []

    def _fetch_portal_content(
        self, portal_name: str, api_url: str, query: str, limit: int
    ) -> List[SearchResult]:
        """Query a government website's REST API for specific articles/services/policies."""
        url = (
            f"{api_url}?search={urllib.parse.quote(query)}"
            f"&per_page={limit}&_fields=id,date,link,title,excerpt"
        )
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8-sig", errors="ignore"))
            if not isinstance(data, list):
                return []

            results = []
            for item in data[:limit]:
                title = _clean_html(item.get("title", {}).get("rendered", ""))
                link = item.get("link", "")
                excerpt = _clean_html(item.get("excerpt", {}).get("rendered", ""))
                date_str = item.get("date", "")

                # Exclude empty titles or non-content links
                if not title or not link or link == api_url:
                    continue

                # Filter out obvious spam injected on unattended assemblies
                spam_markers = ["casino", "betting", "poker", "spins", "slot", "viagra"]
                if any(m in title.lower() for m in spam_markers):
                    continue

                snippet = excerpt if excerpt else f"Official publication from {portal_name}: {title}"

                results.append(
                    SearchResult(
                        title=title,
                        url=link,  # DIRECT CONTENT URL
                        snippet=snippet,
                        source=f"Ghana Public Services ({portal_name})",
                        category=self.category,
                        published_date=date_str[:10] if date_str else None,
                        metadata={
                            "portal": portal_name,
                            "type": "government content / policy / report",
                        },
                    )
                )
            return results

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        """Search live Ghanaian public service portals for content matching keywords."""
        if not keywords:
            return []

        query = " ".join(keywords).strip()
        lower_query = query.lower()

        # 1. Expand query tokens with singular/plural variants
        expanded_tokens = set()
        for kw in keywords:
            for w in kw.split():
                expanded_tokens.update(get_singular_plural_variants(w.lower()))

        # 2. Select the most relevant government portals to query
        portals_to_query: List[Dict[str, str]] = []

        # Check core national agencies
        for national in CORE_NATIONAL_GOV_APIS:
            name = national["name"]
            api_url = national["posts_api"]
            tags = national.get("keywords", [])
            if any(t in lower_query or t in expanded_tokens for t in tags):
                portals_to_query.append({"name": name, "api_url": api_url})

        # Also search verified government APIs from the 164 discovered portals
        for api in self.verified_apis:
            name = api.get("name", "")
            base = api.get("base_url", "")
            posts_api = api.get("posts_api")
            name_lower = name.lower()

            # Match on name or domain
            if any(t in name_lower for t in expanded_tokens):
                if posts_api and not any(p["api_url"] == posts_api for p in portals_to_query):
                    portals_to_query.append({"name": name, "api_url": posts_api})

        # If few portals matched specifically, include top national departments (GRA, MLNR, FDA, GSA)
        if len(portals_to_query) < 4:
            for national in CORE_NATIONAL_GOV_APIS[:4]:
                if not any(p["api_url"] == national["posts_api"] for p in portals_to_query):
                    portals_to_query.append({"name": national["name"], "api_url": national["posts_api"]})

        # Limit concurrent portal queries to avoid latency spikes
        portals_to_query = portals_to_query[:10]

        all_results = []
        with ThreadPoolExecutor(max_workers=len(portals_to_query) + 1) as executor:
            future_to_portal = {
                executor.submit(self._fetch_portal_content, p["name"], p["api_url"], query, limit=3): p["name"]
                for p in portals_to_query
            }
            # Add GhanaDistricts repository search
            future_to_portal[executor.submit(self._search_ghanadistricts, query, limit=3)] = "GhanaDistricts"

            for future in as_completed(future_to_portal):
                portal_name = future_to_portal[future]
                try:
                    res = future.result()
                    if res:
                        all_results.extend(res)
                except Exception:
                    pass

        return all_results
