"""Asynchronous SQLite WAL Analytics Engine for Ghana-MCP.
Tracks query volume, latency, client types, and trending Ghanaian search topics
in the background with zero impact on search response latency.
"""
import os
import sqlite3
import json
import time
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

ANALYTICS_DIR = os.path.expanduser("~/.cache/ghana_mcp")
DB_PATH = os.path.join(ANALYTICS_DIR, "analytics.db")


class AnalyticsEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # Configure WAL mode for maximum concurrent read/write throughput
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    query_text TEXT,
                    clean_chunks TEXT,
                    num_results INTEGER,
                    latency_ms REAL,
                    client_type TEXT,
                    user_agent TEXT,
                    categories TEXT,
                    sources TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON query_logs(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_client ON query_logs(client_type);")

    async def start(self):
        """Start the background logging worker."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        """Stop worker and flush remaining logs."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def _worker(self):
        """Background worker that flushes query logs in batches to SQLite."""
        while True:
            try:
                item = await self._queue.get()
                items = [item]
                # Grab any additional queued items for batch insert
                while not self._queue.empty() and len(items) < 50:
                    items.append(self._queue.get_nowait())

                await asyncio.to_thread(self._batch_insert, items)
                for _ in items:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)

    def _batch_insert(self, items: List[Dict[str, Any]]):
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO query_logs (
                    query_text, clean_chunks, num_results, latency_ms,
                    client_type, user_agent, categories, sources
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("query_text", ""),
                        json.dumps(item.get("clean_chunks", [])),
                        item.get("num_results", 0),
                        item.get("latency_ms", 0.0),
                        item.get("client_type", "mcp"),
                        item.get("user_agent", ""),
                        json.dumps(item.get("categories", [])),
                        json.dumps(item.get("sources", {})),
                    )
                    for item in items
                ],
            )

    def record_query_sync(
        self,
        query_text: str,
        clean_chunks: List[str],
        num_results: int,
        latency_ms: float,
        client_type: str = "mcp",
        user_agent: str = "",
        categories: Optional[List[str]] = None,
        sources: Optional[Dict[str, int]] = None,
    ):
        """Synchronous non-blocking enqueue or direct insert."""
        item = {
            "query_text": query_text,
            "clean_chunks": clean_chunks,
            "num_results": num_results,
            "latency_ms": latency_ms,
            "client_type": client_type,
            "user_agent": user_agent,
            "categories": categories or [],
            "sources": sources or {},
        }
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            # If no running loop, do a quick direct insert
            self._batch_insert([item])

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate usage metrics, latency, and trending search topics."""
        with self._get_connection() as conn:
            # 1. Total and recent query counts
            total_queries = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
            today_queries = conn.execute(
                "SELECT COUNT(*) FROM query_logs WHERE timestamp >= date('now', 'start of day')"
            ).fetchone()[0]
            avg_latency = conn.execute(
                "SELECT AVG(latency_ms) FROM query_logs"
            ).fetchone()[0] or 0.0

            # 2. Client type distribution (MCP vs REST vs Web UI)
            clients = dict(
                conn.execute(
                    "SELECT client_type, COUNT(*) FROM query_logs GROUP BY client_type"
                ).fetchall()
            )

            # 3. Recent 15 queries (with chunks and latency)
            recent_rows = conn.execute(
                """
                SELECT id, timestamp, query_text, clean_chunks, num_results, latency_ms, client_type
                FROM query_logs ORDER BY id DESC LIMIT 15
                """
            ).fetchall()

            recent_queries = []
            noun_frequency: Dict[str, int] = {}
            for row in recent_rows:
                recent_queries.append({
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "query": row["query_text"],
                    "num_results": row["num_results"],
                    "latency_ms": round(row["latency_ms"], 1),
                    "client": row["client_type"],
                })

            # 4. Extract top trending noun chunks across all queries
            all_chunks_rows = conn.execute(
                "SELECT clean_chunks FROM query_logs ORDER BY id DESC LIMIT 500"
            ).fetchall()
            for r in all_chunks_rows:
                try:
                    chunks = json.loads(r["clean_chunks"] or "[]")
                    for c in chunks:
                        c_norm = c.lower().strip()
                        if len(c_norm) > 2:
                            noun_frequency[c_norm] = noun_frequency.get(c_norm, 0) + 1
                except Exception:
                    continue

            trending_topics = sorted(noun_frequency.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "total_queries": total_queries,
                "queries_today": today_queries,
                "avg_latency_ms": round(avg_latency, 1),
                "client_breakdown": clients,
                "trending_topics": [{"topic": t[0], "count": t[1]} for t in trending_topics],
                "recent_queries": recent_queries,
            }


# Global singleton analytics engine
analytics = AnalyticsEngine()
