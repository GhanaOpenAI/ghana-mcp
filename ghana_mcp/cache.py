"""24-Hour Query and Result Caching Engine for Ghana-MCP.
Uses an in-memory LRU buffer backed by persistent SQLite WAL storage with a 24-hour TTL.
"""
import os
import json
import time
import hashlib
import sqlite3
from typing import List, Dict, Any, Optional

from ghana_mcp.providers.base import SearchResult

CACHE_DIR = os.path.expanduser("~/.cache/ghana_mcp")
DB_PATH = os.path.join(CACHE_DIR, "search_cache.db")
DEFAULT_TTL = 86400  # 24 hours in seconds


class QueryCache:
    def __init__(self, db_path: str = DB_PATH, ttl_seconds: int = DEFAULT_TTL):
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._max_memory_items = 1000

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    cache_key TEXT PRIMARY KEY,
                    normalized_query TEXT,
                    categories TEXT,
                    top_k INTEGER,
                    results_json TEXT,
                    created_at REAL,
                    expires_at REAL,
                    hit_count INTEGER DEFAULT 0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON search_cache(expires_at);")

    def _make_key(self, text: str, categories: Optional[List[str]], top_k: int) -> str:
        """Create a deterministic cache key based on query tokens and parameters."""
        norm_tokens = sorted(list(set(text.lower().strip().split())))
        cats = sorted(categories) if categories else ["all"]
        key_raw = f"{' '.join(norm_tokens)}|{','.join(cats)}|{top_k}"
        return hashlib.sha256(key_raw.encode("utf-8")).hexdigest()

    def get(
        self, text: str, categories: Optional[List[str]], top_k: int
    ) -> Optional[List[SearchResult]]:
        """Retrieve cached results if available and unexpired (within 24 hours)."""
        cache_key = self._make_key(text, categories, top_k)
        now = time.time()

        # 1. Check in-memory fast LRU cache
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            if entry["expires_at"] > now:
                entry["hit_count"] += 1
                return self._deserialize_results(entry["results"], age=now - entry["created_at"])
            else:
                del self._memory_cache[cache_key]

        # 2. Check persistent SQLite cache
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT results_json, created_at, expires_at, hit_count
                    FROM search_cache
                    WHERE cache_key = ? AND expires_at > ?
                    """,
                    (cache_key, now),
                ).fetchone()

                if row:
                    # Update hit count
                    conn.execute(
                        "UPDATE search_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                        (cache_key,),
                    )
                    results_data = json.loads(row["results_json"])
                    created_at = row["created_at"]

                    # Populate memory cache
                    if len(self._memory_cache) >= self._max_memory_items:
                        self._memory_cache.clear()
                    self._memory_cache[cache_key] = {
                        "results": results_data,
                        "created_at": created_at,
                        "expires_at": row["expires_at"],
                        "hit_count": row["hit_count"] + 1,
                    }

                    return self._deserialize_results(results_data, age=now - created_at)
        except Exception:
            pass

        return None

    def set(
        self,
        text: str,
        categories: Optional[List[str]],
        top_k: int,
        results: List[SearchResult],
    ):
        """Store search results in cache for 24 hours."""
        if not results:
            return

        cache_key = self._make_key(text, categories, top_k)
        now = time.time()
        expires_at = now + self.ttl_seconds
        results_data = [r.to_dict() for r in results]
        results_json = json.dumps(results_data)

        # Store in memory
        if len(self._memory_cache) >= self._max_memory_items:
            self._memory_cache.clear()
        self._memory_cache[cache_key] = {
            "results": results_data,
            "created_at": now,
            "expires_at": expires_at,
            "hit_count": 0,
        }

        # Store in SQLite WAL database
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO search_cache (
                        cache_key, normalized_query, categories, top_k,
                        results_json, created_at, expires_at, hit_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        results_json = excluded.results_json,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at
                    """,
                    (
                        cache_key,
                        text.lower().strip(),
                        json.dumps(categories or []),
                        top_k,
                        results_json,
                        now,
                        expires_at,
                    ),
                )
        except Exception:
            pass

    def _deserialize_results(self, items: List[Dict[str, Any]], age: float) -> List[SearchResult]:
        results = []
        for it in items:
            meta = dict(it.get("metadata", {}))
            meta["cached"] = True
            meta["cache_age_seconds"] = round(age, 1)
            results.append(
                SearchResult(
                    title=it["title"],
                    url=it["url"],
                    snippet=it["snippet"],
                    source=it["source"],
                    category=it["category"],
                    published_date=it.get("published_date"),
                    score=it.get("score"),
                    metadata=meta,
                )
            )
        return results

    def clear_expired(self):
        """Remove entries older than 24 hours."""
        now = time.time()
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM search_cache WHERE expires_at <= ?", (now,))
        except Exception:
            pass


# Global cache instance
search_cache = QueryCache()
