"""GhaLII (Ghana Legal Information Institute) search provider.
Directly queries GhaLII search API for Supreme Court, Court of Appeal, High Court judgments,
Acts of Parliament, Decrees, and legal documents with direct download links.
"""
import json
import urllib.request
import urllib.parse
import ssl
from typing import List
from bs4 import BeautifulSoup

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

GHALII_SEARCH_API = "https://ghalii.org/search/api/documents/"


class GhaLIIProvider(BaseProvider):
    name = "ghalii_legal"
    category = "public_services"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": "https://ghalii.org/search/",
        }

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        if not keywords:
            return []

        query = " ".join(keywords).strip()
        params = {"search": query, "page": 1}
        url = f"{GHALII_SEARCH_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self.headers)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))

            results_html = data.get("results_html", "")
            if not results_html:
                return []

            soup = BeautifulSoup(results_html, "html.parser")
            cards = soup.find_all("li", class_="hit")

            results: List[SearchResult] = []
            for card in cards[:limit]:
                title_link = card.find("a", class_="card-title") or card.find("h5")
                a_tag = card.find("h5").find("a") if card.find("h5") else card.find("a", href=True)
                if not a_tag:
                    continue

                title = a_tag.get_text(strip=True)
                rel_url = a_tag.get("href", "")
                doc_url = f"https://ghalii.org{rel_url}" if rel_url.startswith("/") else rel_url

                # Direct source / PDF download link
                download_btn = card.find("a", href=lambda h: h and h.endswith("/source"))
                pdf_url = f"https://ghalii.org{download_btn['href']}" if download_btn else None

                # Summary or flynotes
                summary_div = card.find("div", class_="my-2")
                snippet = summary_div.get_text(strip=True) if summary_div else f"Official legal document from GhaLII: {title}"

                # Date
                date_span = card.find("span", class_="me-3")
                date_str = date_span.get_text(strip=True) if date_span else None

                # Direct URL is the download link if available, otherwise document view
                primary_url = pdf_url if pdf_url else doc_url

                results.append(
                    SearchResult(
                        title=title,
                        url=primary_url,
                        snippet=snippet,
                        source="GhaLII (Ghana Legal Information Institute)",
                        category=self.category,
                        content=snippet,
                        published_date=date_str,
                        metadata={
                            "document_url": doc_url,
                            "download_url": pdf_url,
                            "type": "court judgment / legislation",
                        },
                    )
                )

            return results
        except Exception:
            return []
