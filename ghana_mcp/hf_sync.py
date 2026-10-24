"""Automated Hugging Face Dataset Backup Engine for Ghana Search.
Asynchronously pushes the permanent URL content cache to 'ghanaopenai/ghana-search-corpus'
to maintain a sovereign cloud backup and build an offline-ready Ghanaian knowledge base.
"""
import os
import json
import time
import sqlite3
import asyncio
from typing import Dict, Any, Optional

try:
    from huggingface_hub import HfApi
except ImportError:
    HfApi = None

from ghana_mcp.cache import DB_PATH

HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "ghanaopenai/ghana-search-corpus")
CACHE_DIR = os.path.expanduser("~/.cache/ghana_mcp")
JSONL_EXPORT_PATH = os.path.join(CACHE_DIR, "ghana_search_corpus.jsonl")


class HuggingFaceCorpusSync:
    def __init__(
        self,
        repo_id: str = HF_DATASET_REPO,
        db_path: str = DB_PATH,
        sync_interval_seconds: int = 3600,  # 1 hour default
    ):
        self.repo_id = repo_id
        self.db_path = db_path
        self.sync_interval = sync_interval_seconds
        self.last_synced_count = 0
        self.last_sync_time = 0.0
        self._worker_task: Optional[asyncio.Task] = None

    def _get_token(self) -> Optional[str]:
        """Retrieve Hugging Face token from environment or local cache."""
        env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if env_token:
            return env_token.strip()

        token_path = os.path.expanduser("~/.cache/huggingface/token")
        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    def export_corpus_jsonl(self) -> int:
        """Export all permanently cached URLs and their full content to JSONL format."""
        if not os.path.exists(self.db_path):
            return 0

        os.makedirs(os.path.dirname(JSONL_EXPORT_PATH), exist_ok=True)
        count = 0

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM url_content_cache ORDER BY first_seen DESC"
            ).fetchall()

            with open(JSONL_EXPORT_PATH, "w", encoding="utf-8") as f:
                for r in rows:
                    meta = json.loads(r["metadata_json"] or "{}")
                    item = {
                        "url": r["url"],
                        "title": r["title"],
                        "snippet": r["snippet"],
                        "content": r["content"],
                        "source": r["source"],
                        "category": r["category"],
                        "published_date": r["published_date"],
                        "first_seen": r["first_seen"],
                        "last_accessed": r["last_accessed"],
                        "access_count": r["access_count"],
                        "pdf_url": meta.get("pdf_url"),
                    }
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    count += 1

        return count

    def push_to_huggingface(self) -> Dict[str, Any]:
        """Perform a synchronous push of the exported corpus to Hugging Face."""
        if HfApi is None:
            return {"status": "error", "message": "huggingface_hub package not installed"}

        token = self._get_token()
        if not token:
            return {"status": "skipped", "message": "No Hugging Face token found"}

        exported_count = self.export_corpus_jsonl()
        if exported_count == 0:
            return {"status": "skipped", "message": "No documents in cache to export"}

        try:
            api = HfApi(token=token)
            api.create_repo(repo_id=self.repo_id, repo_type="dataset", exist_ok=True)

            api.upload_file(
                path_or_fileobj=JSONL_EXPORT_PATH,
                path_in_repo="ghana_search_corpus.jsonl",
                repo_id=self.repo_id,
                repo_type="dataset",
                commit_message=f"Sync offline corpus backup ({exported_count} documents)",
            )

            self.last_synced_count = exported_count
            self.last_sync_time = time.time()

            return {
                "status": "success",
                "repo_id": self.repo_id,
                "exported_documents": exported_count,
                "file_size_kb": round(os.path.getsize(JSONL_EXPORT_PATH) / 1024, 1),
                "timestamp": self.last_sync_time,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def start(self):
        """Start the background sync worker."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._periodic_worker())

    async def stop(self):
        """Stop background worker."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def _periodic_worker(self):
        """Background task checking for new cached documents and syncing periodically."""
        # Initial delayed check (wait 30s after server boot)
        await asyncio.sleep(30)
        while True:
            try:
                # Check current count in SQLite
                with sqlite3.connect(self.db_path) as conn:
                    current_count = conn.execute("SELECT COUNT(*) FROM url_content_cache").fetchone()[0]

                # If new documents were cached since last push, sync to Hugging Face
                if current_count > self.last_synced_count:
                    await asyncio.to_thread(self.push_to_huggingface)

                await asyncio.sleep(self.sync_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(300)


# Global HF sync singleton
hf_sync = HuggingFaceCorpusSync()
