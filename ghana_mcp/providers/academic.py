"""Academic research and thesis abstracts provider for Ghanaian universities.
Directly queries official DSpace 7 REST APIs for KNUST, University of Ghana, and UCC.
"""
import json
import urllib.request
import urllib.parse
import ssl
import os
import csv
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from ghana_mcp.providers.base import BaseProvider, SearchResult
from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Verified live institutional repository DSpace 7 REST endpoints
DSPACE_ENDPOINTS = [
    {
        "name": "KNUST Institutional Repository",
        "base_url": "https://ir.knust.edu.gh/server/api/discover/search/objects",
        "handle_prefix": "https://ir.knust.edu.gh/handle/",
    },
    {
        "name": "University of Ghana (UGSpace)",
        "base_url": "https://ugspace.ug.edu.gh/server/api/discover/search/objects",
        "handle_prefix": "https://ugspace.ug.edu.gh/handle/",
    },
    {
        "name": "University of Cape Coast (UCC ERL)",
        "base_url": "https://erl.ucc.edu.gh/server/api/discover/search/objects",
        "handle_prefix": "https://erl.ucc.edu.gh/handle/",
    },
]

# Local corpus path if available on server
LOCAL_CORPUS_DIR = "/media/owusus/Godstestimo/NLP-Projects/Ghana-Research-Corpus"


class AcademicProvider(BaseProvider):
    name = "ghana_academic"
    category = "academic"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

    def _query_dspace(self, repo: Dict[str, str], query: str, limit: int) -> List[SearchResult]:
        """Query a DSpace 7 REST API discover/search/objects endpoint."""
        params = {"query": query, "page": 0, "size": limit}
        url = f"{repo['base_url']}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self.headers)

        with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        objects = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
        results = []

        for obj in objects[:limit]:
            item = obj.get("_embedded", {}).get("indexableObject", {})
            metadata = item.get("metadata", {})

            # Extract Title
            title_entries = metadata.get("dc.title", [])
            title = title_entries[0].get("value", "").strip() if title_entries else ""
            if not title:
                continue

            # Extract Abstract
            abstract_entries = (
                metadata.get("dc.description.abstract", [])
                or metadata.get("dc.description", [])
            )
            abstract = abstract_entries[0].get("value", "").strip() if abstract_entries else "No abstract provided."

            # Extract Canonical URI / Handle
            handle_entries = metadata.get("dc.identifier.uri", [])
            if handle_entries:
                item_url = handle_entries[0].get("value", "").strip()
            else:
                handle = item.get("handle")
                item_url = f"{repo['handle_prefix']}{handle}" if handle else repo["base_url"]

            # Extract Author & Date
            authors = [a.get("value") for a in metadata.get("dc.contributor.author", []) if a.get("value")]
            date_entries = metadata.get("dc.date.issued", []) or metadata.get("dc.date.accessioned", [])
            date_str = date_entries[0].get("value", "")[:10] if date_entries else None

            results.append(
                SearchResult(
                    title=title,
                    url=item_url,
                    snippet=abstract,
                    source=repo["name"],
                    category=self.category,
                    published_date=date_str,
                    metadata={
                        "authors": authors,
                        "type": "thesis / academic research",
                        "institution": repo["name"],
                    },
                )
            )

        return results

    def _search_local_corpus(self, query: str, limit: int) -> List[SearchResult]:
        """Fallback keyword search over local corpus CSVs if available on host."""
        if not os.path.isdir(LOCAL_CORPUS_DIR):
            return []

        results = []
        tokens = [t.lower() for t in query.split() if len(t) > 2]
        if not tokens:
            return []

        candidates = [
            (os.path.join(LOCAL_CORPUS_DIR, "KNUST", "knust_repository_data.csv"), "KNUST Local Corpus"),
            (os.path.join(LOCAL_CORPUS_DIR, "UCC", "ucc_repository_data.csv"), "UCC Local Corpus"),
            (os.path.join(LOCAL_CORPUS_DIR, "combined", "UEW.csv"), "UEW Local Corpus"),
            (os.path.join(LOCAL_CORPUS_DIR, "combined", "Ashesi.csv"), "Ashesi Local Corpus"),
        ]

        for file_path, source_name in candidates:
            if not os.path.exists(file_path):
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        title = row.get("title", "")
                        abstract = row.get("abstract", "") or row.get("description", "")
                        combined = f"{title} {abstract}".lower()
                        if all(t in combined for t in tokens):
                            link = row.get("item_url") or row.get("document_url") or row.get("handle") or file_path
                            results.append(
                                SearchResult(
                                    title=title.strip(),
                                    url=link,
                                    snippet=abstract.strip() or f"Academic paper: {title.strip()}",
                                    source=source_name,
                                    category=self.category,
                                )
                            )
                            if len(results) >= limit:
                                return results
            except Exception:
                continue

        return results

    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        query = " ".join(keywords).strip()
        if not query:
            return []

        all_results = []
        tasks = []
        for repo in DSPACE_ENDPOINTS:
            tasks.append((repo["name"], lambda r=repo: self._query_dspace(r, query, limit)))

        with ThreadPoolExecutor(max_workers=len(DSPACE_ENDPOINTS)) as executor:
            future_to_repo = {executor.submit(fn): name for name, fn in tasks}
            for future in as_completed(future_to_repo):
                try:
                    res = future.result()
                    if res:
                        all_results.extend(res)
                except Exception:
                    pass

        # If live DSpace returned few results and local corpus exists, supplement
        if len(all_results) < limit:
            local_res = self._search_local_corpus(query, limit=limit - len(all_results))
            all_results.extend(local_res)

        return all_results
