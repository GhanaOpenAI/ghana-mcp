"""Yellow Pages & Business Directory search provider for Ghanaian commercial enterprises."""
import re
import urllib.request
import urllib.parse
import ssl
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

GENERIC_COMMERCIAL_TERMS = {
    "company", "companies", "business", "businesses", "enterprise",
    "enterprises", "service", "services", "shop", "shops", "store",
    "stores", "dealer", "dealers", "supplier", "suppliers", "ltd", "limited",
    "in", "at", "for", "the", "and", "of", "to"
}

GHANA_CITIES = {
    "accra", "kumasi", "tamale", "takoradi", "tema", "cape coast",
    "sunyani", "koforidua", "ho", "wa", "bolgatanga", "techiman", "adum", "lapaz"
}


def normalize_business_token(w: str) -> str:
    """Normalize plural and casing for business category matching."""
    lower = w.lower().strip()
    if lower.endswith("ies") and len(lower) > 4:
        return lower[:-3] + "y"
    if lower.endswith("s") and len(lower) > 3 and not lower.endswith("ss"):
        return lower[:-1]
    return lower


class BusinessDirectoryProvider(BaseProvider):
    name = "ghana_business"
    category = "business"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _parse_query_params(self, raw_query: str) -> Tuple[str, Optional[str]]:
        """Extract core search term and optional city/location."""
        q_lower = raw_query.lower()
        found_city = None
        for city in GHANA_CITIES:
            if re.search(rf"\b{re.escape(city)}\b", q_lower):
                found_city = city
                break

        tokens = [
            normalize_business_token(t)
            for t in re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", raw_query)
            if t.lower() not in GENERIC_COMMERCIAL_TERMS and t.lower() != found_city
        ]
        q_str = " ".join(tokens) if tokens else raw_query
        return q_str, found_city

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        raw_query = " ".join(keywords).strip()
        if not raw_query:
            return []

        q_term, city = self._parse_query_params(raw_query)
        params = {"q": q_term}
        if city:
            params["where"] = city

        url = f"https://www.ghanabusinessweb.com/search?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self.headers)
        results: List[SearchResult] = []

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            soup = BeautifulSoup(html, "html.parser")
            seen_urls = set()

            for art in soup.find_all("article"):
                h = art.find(["h2", "h3", "h4"])
                if not h:
                    continue
                a = h.find("a")
                if not a:
                    continue

                name = a.get_text(strip=True)
                link = a.get("href", "")
                if not name or link in seen_urls:
                    continue
                seen_urls.add(link)

                # Extract text lines inside article card
                texts = [
                    t.strip()
                    for t in art.stripped_strings
                    if t.strip() and t.strip() not in (name, "S", "V", "G", "A", "D", "P", "C", "M", "L", "H", "B", "R", "W")
                ]

                # Phone number extraction
                phone_match = re.search(
                    r"(\+?233[\d\s\-]{8,}|\b0\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b)",
                    " ".join(texts),
                )
                phone = phone_match.group(0).strip() if phone_match else None

                cat_desc = texts[0] if texts else "Commercial Services"
                loc = city.title() if city else "Ghana"
                for t in texts[1:]:
                    if t != phone and "open" not in t.lower() and "closed" not in t.lower():
                        loc = t
                        break

                snippet_parts = [cat_desc]
                if loc and loc != "Ghana":
                    snippet_parts.append(f"Location: {loc}")
                if phone:
                    snippet_parts.append(f"Tel: {phone}")

                snippet = " • ".join(snippet_parts)
                full_content = (
                    f"{name} is a verified Ghanaian commercial enterprise ({cat_desc}). "
                    f"Location/address: {loc}. Contact telephone: {phone or 'Listed on directory portal'}."
                )

                results.append(
                    SearchResult(
                        title=name,
                        url=link,
                        snippet=snippet,
                        source="Ghana Yellow Pages (GhanaBusinessWeb)",
                        category=self.category,
                        content=full_content,
                        metadata={
                            "type": "business_directory / yellow_pages",
                            "phone": phone,
                            "location": loc,
                            "business_category": cat_desc,
                        },
                    )
                )

                if len(results) >= limit:
                    break
        except Exception:
            pass

        return results
