"""Asynchronous SQLite WAL Analytics & Evaluation Dataset Engine for Ghana-MCP.
Tracks query volume, latency, client types, and trending Ghanaian search topics.
Builds a persistent query-evaluation dataset in JSONL format for continuous offline
evaluation, fine-tuning, and model improvement.
"""
import os
import sqlite3
import json
import time
import asyncio
from typing import List, Dict, Any, Optional

ANALYTICS_DIR = os.path.expanduser("~/.cache/ghana_mcp")
DB_PATH = os.path.join(ANALYTICS_DIR, "analytics.db")
DATASET_JSONL_PATH = os.path.join(ANALYTICS_DIR, "query_evaluation_dataset.jsonl")


class AnalyticsEngine:
    def __init__(self, db_path: str = DB_PATH, dataset_path: str = DATASET_JSONL_PATH):
        self.db_path = db_path
        self.dataset_path = dataset_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
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
                    cached INTEGER DEFAULT 0,
                    client_type TEXT,
                    user_agent TEXT,
                    categories TEXT,
                    sources TEXT,
                    top_results_summary TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON query_logs(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_client ON query_logs(client_type);")

            # Schema migration for existing databases
            cols = [col[1] for col in conn.execute("PRAGMA table_info(query_logs)").fetchall()]
            if "cached" not in cols:
                conn.execute("ALTER TABLE query_logs ADD COLUMN cached INTEGER DEFAULT 0;")
            if "top_results_summary" not in cols:
                conn.execute("ALTER TABLE query_logs ADD COLUMN top_results_summary TEXT;")

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
        """Background worker that flushes query logs in batches to SQLite and JSONL."""
        while True:
            try:
                item = await self._queue.get()
                items = [item]
                while not self._queue.empty() and len(items) < 50:
                    items.append(self._queue.get_nowait())

                await asyncio.to_thread(self._batch_insert, items)
                await asyncio.to_thread(self._append_to_dataset_file, items)
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
                    cached, client_type, user_agent, categories, sources,
                    top_results_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("query_text", ""),
                        json.dumps(item.get("clean_chunks", [])),
                        item.get("num_results", 0),
                        item.get("latency_ms", 0.0),
                        1 if item.get("cached") else 0,
                        item.get("client_type", "mcp"),
                        item.get("user_agent", ""),
                        json.dumps(item.get("categories", [])),
                        json.dumps(item.get("sources", {})),
                        json.dumps(item.get("top_results_summary", [])),
                    )
                    for item in items
                ],
            )

    def _append_to_dataset_file(self, items: List[Dict[str, Any]]):
        """Persist items in JSONL format for dataset evaluation."""
        try:
            with open(self.dataset_path, "a", encoding="utf-8") as f:
                for item in items:
                    record = {
                        "timestamp": time.time(),
                        "query": item.get("query_text", ""),
                        "noun_chunks": item.get("clean_chunks", []),
                        "num_results": item.get("num_results", 0),
                        "latency_ms": item.get("latency_ms", 0.0),
                        "cached": bool(item.get("cached")),
                        "client": item.get("client_type", "mcp"),
                        "top_results": item.get("top_results_summary", []),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def record_query_sync(
        self,
        query_text: str,
        clean_chunks: List[str],
        num_results: int,
        latency_ms: float,
        cached: bool = False,
        client_type: str = "mcp",
        user_agent: str = "",
        categories: Optional[List[str]] = None,
        sources: Optional[Dict[str, int]] = None,
        top_results_summary: Optional[List[Dict[str, Any]]] = None,
    ):
        """Synchronous non-blocking enqueue or direct insert."""
        item = {
            "query_text": query_text,
            "clean_chunks": clean_chunks,
            "num_results": num_results,
            "latency_ms": latency_ms,
            "cached": cached,
            "client_type": client_type,
            "user_agent": user_agent,
            "categories": categories or [],
            "sources": sources or {},
            "top_results_summary": top_results_summary or [],
        }
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            self._batch_insert([item])
            self._append_to_dataset_file([item])

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate usage metrics, cache hit rate, latency, and trending Ghanaian topics."""
        with self._get_connection() as conn:
            total_queries = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
            today_queries = conn.execute(
                "SELECT COUNT(*) FROM query_logs WHERE timestamp >= date('now', 'start of day')"
            ).fetchone()[0]
            cached_queries = conn.execute(
                "SELECT COUNT(*) FROM query_logs WHERE cached = 1"
            ).fetchone()[0]
            avg_latency = conn.execute(
                "SELECT AVG(latency_ms) FROM query_logs"
            ).fetchone()[0] or 0.0

            cache_hit_rate = round((cached_queries / total_queries * 100), 1) if total_queries > 0 else 0.0

            clients = dict(
                conn.execute(
                    "SELECT client_type, COUNT(*) FROM query_logs GROUP BY client_type"
                ).fetchall()
            )

            recent_rows = conn.execute(
                """
                SELECT id, timestamp, query_text, clean_chunks, num_results, latency_ms, cached, client_type
                FROM query_logs ORDER BY id DESC LIMIT 20
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
                    "cached": bool(row["cached"]),
                    "client": row["client_type"],
                })

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

            dataset_size_kb = 0
            if os.path.exists(self.dataset_path):
                dataset_size_kb = round(os.path.getsize(self.dataset_path) / 1024, 1)

            return {
                "total_queries": total_queries,
                "queries_today": today_queries,
                "cached_queries": cached_queries,
                "cache_hit_rate_pct": cache_hit_rate,
                "avg_latency_ms": round(avg_latency, 1),
                "client_breakdown": clients,
                "trending_topics": [{"topic": t[0], "count": t[1]} for t in trending_topics],
                "recent_queries": recent_queries,
                "dataset_file": self.dataset_path,
                "dataset_size_kb": dataset_size_kb,
            }

    def export_dataset(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Export logged queries with evaluation metadata."""
        records = []
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, query_text, clean_chunks, num_results, latency_ms,
                       cached, client_type, categories, top_results_summary
                FROM query_logs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for r in rows:
                records.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "query": r["query_text"],
                    "noun_chunks": json.loads(r["clean_chunks"] or "[]"),
                    "num_results": r["num_results"],
                    "latency_ms": r["latency_ms"],
                    "cached": bool(r["cached"]),
                    "client": r["client_type"],
                    "categories": json.loads(r["categories"] or "[]"),
                    "top_results": json.loads(r["top_results_summary"] or "[]"),
                })
        return records


# Global analytics engine singleton
analytics = AnalyticsEngine()
