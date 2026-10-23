"""100% CPU Terminology Density & Recency Reranking Engine for Ghana Search.
Zero GPU or VRAM required.
Ranks candidates based on:
  1. Exact noun chunk and key terminology frequency in title and body.
  2. Noun chunk coverage across the document.
  3. Publication recency and freshness weighting.
"""
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from ghana_mcp.providers.base import SearchResult


def parse_date_timestamp(date_str: Optional[str]) -> float:
    """Parse various Ghanaian date formats into an epoch timestamp."""
    if not date_str:
        return 0.0

    ds = str(date_str).strip()

    # 1. Relative dates: "2 hours ago", "3 days ago"
    rel_match = re.search(r"(\d+)\s+(day|hour|minute|min|week|month|year)s?\s+ago", ds, re.I)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if "day" in unit:
            delta = timedelta(days=val)
        elif "hour" in unit:
            delta = timedelta(hours=val)
        elif "min" in unit:
            delta = timedelta(minutes=val)
        elif "week" in unit:
            delta = timedelta(weeks=val)
        elif "month" in unit:
            delta = timedelta(days=val * 30)
        elif "year" in unit:
            delta = timedelta(days=val * 365)
        else:
            delta = timedelta(days=1)
        return (datetime.now(timezone.utc) - delta).timestamp()

    # 2. ISO format
    try:
        clean_iso = ds.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_iso).timestamp()
    except Exception:
        pass

    # 3. String formats
    formats = [
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y-%m-%d",
        "%Y-%m",
        "%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ds, fmt).replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue

    # 4. 4-digit year fallback
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", ds)
    if year_match:
        try:
            return datetime(int(year_match.group(1)), 1, 1, tzinfo=timezone.utc).timestamp()
        except Exception:
            pass

    return 0.0


class TerminologyRecencyReranker:
    """100% CPU-based terminology density and recency reranker.
    Zero GPU or VRAM required.
    """

    def rerank(
        self,
        query: str,
        keywords: List[str],
        candidates: List[SearchResult],
        top_k: int = 50,
    ) -> List[SearchResult]:
        if not candidates:
            return []

        # Extract normalized query chunks and tokens
        query_lower = query.lower()
        chunks = [k.lower().strip() for k in keywords if len(k.strip()) > 1]
        all_terms = set(re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", query_lower))

        now_ts = datetime.now(timezone.utc).timestamp()
        scored_candidates = []

        for item in candidates:
            title_lower = (item.title or "").lower()
            snippet_lower = (item.snippet or "").lower()
            combined_text = f"{title_lower} {snippet_lower} {(item.source or '').lower()}"

            # 1. Exact noun chunk occurrences (highest signal)
            chunk_title_matches = sum(1 for c in chunks if c in title_lower)
            chunk_body_matches = sum(1 for c in chunks if c in snippet_lower)

            # 2. Noun chunk coverage ratio (how many distinct chunks appear in the document)
            chunks_covered = sum(1 for c in chunks if c in combined_text)
            coverage_ratio = (chunks_covered / len(chunks)) if chunks else 0.0

            # 3. Individual term matches
            term_matches = sum(1 for t in all_terms if t in combined_text)

            # Terminology subscore
            term_score = (
                (chunk_title_matches * 14.0)
                + (chunk_body_matches * 6.0)
                + (coverage_ratio * 10.0)
                + (term_matches * 1.2)
            )

            # 4. Recency boost (fresher publications get a clean boost)
            ts = parse_date_timestamp(item.published_date)
            freshness_boost = 0.0
            if ts > 0:
                age_days = max(0.0, (now_ts - ts) / 86400.0)
                # Documents published within the past 2 years (730 days) receive scaled freshness
                freshness_boost = max(0.0, 1.0 - (age_days / 730.0)) * 6.0

            composite_score = round(term_score + freshness_boost, 2)

            item.score = composite_score
            item.metadata["ranking_engine"] = "cpu_terminology_recency"
            item.metadata["term_matches"] = term_matches
            item.metadata["chunks_covered"] = chunks_covered

            scored_candidates.append((composite_score, item))

        # Rank strictly by descending composite score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored_candidates[:top_k]]


# Global 100% CPU Reranker (Zero GPU requirement)
reranker = TerminologyRecencyReranker()
