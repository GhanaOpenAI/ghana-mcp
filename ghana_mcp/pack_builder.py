"""Offline Knowledge Pack Builder for Ghana Search.
Allows anyone to create domain-specific offline knowledge cache databases from
a list of queries, a local file, or a Hugging Face dataset (e.g. ghana-farmer-qa).
These packs can be distributed and deployed completely offline for air-gapped LLMs.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from ghana_mcp.providers.base import SearchResult
from ghana_mcp.cache import QueryCache
from ghana_mcp.server import _execute_search


def fetch_queries_from_hf(
    dataset_name: str,
    column: str = "question",
    split: str = "train",
    limit: int = 500,
) -> List[str]:
    """Fetch query questions from a Hugging Face dataset."""
    print(f"[*] Fetching queries from Hugging Face dataset: '{dataset_name}' (column: '{column}', limit: {limit})...")

    # 1. Try Hugging Face datasets library if available
    try:
        from datasets import load_dataset
        ds = load_dataset(dataset_name, split=split, streaming=True)
        queries = []
        for row in ds:
            q = row.get(column)
            if q and str(q).strip():
                queries.append(str(q).strip())
            if len(queries) >= limit:
                break
        if queries:
            print(f"[+] Loaded {len(queries)} queries via datasets library.")
            return queries
    except Exception as e:
        print(f"[-] Datasets library fetch failed ({e}). Falling back to Hugging Face Datasets API...")

    # 2. Fallback to HF Datasets Server HTTP API
    queries = []
    offset = 0
    batch_size = 100
    while len(queries) < limit:
        url = (
            f"https://datasets-server.huggingface.co/rows?"
            f"dataset={urllib.parse.quote(dataset_name)}&config=default&split={split}"
            f"&offset={offset}&limit={min(batch_size, limit - len(queries))}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "GhanaSearchPackBuilder/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                rows = data.get("rows", [])
                if not rows:
                    break
                for item in rows:
                    row_data = item.get("row", {})
                    q = row_data.get(column)
                    if q and str(q).strip():
                        queries.append(str(q).strip())
                offset += len(rows)
                if len(rows) < batch_size:
                    break
        except Exception as e:
            print(f"[-] HF API error at offset {offset}: {e}")
            break

    print(f"[+] Retrieved {len(queries)} queries from Hugging Face.")
    return queries


def load_queries_from_file(file_path: str, column: Optional[str] = None) -> List[str]:
    """Load query strings from a TXT, CSV, JSON, or JSONL file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Queries file not found: {file_path}")

    queries = []
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".jsonl":
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    q = item.get(column or "question") or item.get("text") or item.get("query")
                    if q:
                        queries.append(str(q).strip())
    elif ext == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        queries.append(item.strip())
                    elif isinstance(item, dict):
                        q = item.get(column or "question") or item.get("text") or item.get("query")
                        if q:
                            queries.append(str(q).strip())
    elif ext == ".csv":
        import csv
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            col_name = column or reader.fieldnames[0]
            for row in reader:
                q = row.get(col_name)
                if q:
                    queries.append(str(q).strip())
    else:
        # Plain text: one query per line
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                cleaned = line.strip()
                if cleaned and not cleaned.startswith("#"):
                    queries.append(cleaned)

    print(f"[+] Loaded {len(queries)} queries from {file_path}.")
    return queries


def build_offline_pack(
    queries: List[str],
    output_db_path: str,
    categories: Optional[List[str]] = None,
    export_jsonl_path: Optional[str] = None,
    top_k_per_query: int = 10,
    max_workers: int = 4,
) -> Dict[str, Any]:
    """Execute queries through the engine and bundle an offline SQLite knowledge pack."""
    os.makedirs(os.path.dirname(os.path.abspath(output_db_path)), exist_ok=True)
    target_cache = QueryCache(db_path=output_db_path)

    cats = categories or ["news", "academic", "public_services", "wikipedia"]
    total = len(queries)
    print(f"[*] Starting offline pack build with {total} queries...")
    print(f"[*] Output Database: {output_db_path}")
    print(f"[*] Categories: {cats}")

    processed = 0
    t0 = time.time()

    def process_query(q: str):
        # Execute search across active providers
        try:
            results = _execute_search(
                text=q,
                categories=cats,
                top_k=top_k_per_query,
                rerank=True,
                client_type="offline_pack_builder",
            )
            # Save into the pack's SQLite DB
            target_cache.set_urls_batch(results)
            target_cache.set(q, cats, top_k_per_query, results)
            return len(results)
        except Exception as e:
            return 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_query, q): q for q in queries}
        for future in as_completed(futures):
            processed += 1
            if processed % 10 == 0 or processed == total:
                elapsed = time.time() - t0
                qps = processed / max(elapsed, 0.1)
                stats = target_cache.get_url_cache_stats()
                print(
                    f"[{processed}/{total}] {qps:.1f} q/s | "
                    f"Unique URLs Cached: {stats['total_permanent_urls']} | "
                    f"Elapsed: {elapsed:.1f}s"
                )

    # Compile final stats
    stats = target_cache.get_url_cache_stats()
    print("\n" + "=" * 60)
    print("OFFLINE KNOWLEDGE PACK BUILD COMPLETE")
    print("=" * 60)
    print(f"Total Queries Executed:  {total}")
    print(f"Total Unique URLs Cached: {stats['total_permanent_urls']}")
    print("Breakdown by Source Institution:")
    for source, count in stats.get("sources_stored", {}).items():
        print(f"  • {source}: {count} records")

    # Optional JSONL Export
    if export_jsonl_path:
        os.makedirs(os.path.dirname(os.path.abspath(export_jsonl_path)), exist_ok=True)
        print(f"\n[*] Exporting offline records to JSONL: {export_jsonl_path}...")
        with target_cache._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT url, title, snippet, content, source, category, published_date, metadata_json
                FROM url_content_cache
                ORDER BY access_count DESC
                """
            ).fetchall()

        with open(export_jsonl_path, "w", encoding="utf-8") as f:
            for r in rows:
                record = {
                    "url": r["url"],
                    "title": r["title"],
                    "snippet": r["snippet"],
                    "content": r["content"],
                    "source": r["source"],
                    "category": r["category"],
                    "published_date": r["published_date"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[+] Exported {len(rows)} JSONL records to {export_jsonl_path}")

    print("\nHow to deploy this pack in 100% Offline Mode:")
    print(f"  GHANA_SEARCH_OFFLINE=1 GHANA_SEARCH_DB=\"{output_db_path}\" python3 -m ghana_mcp.server")
    print("=" * 60 + "\n")

    return {
        "total_queries": total,
        "total_urls": stats["total_permanent_urls"],
        "db_path": output_db_path,
        "sources": stats.get("sources_stored", {}),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Ghana Search: Offline Knowledge Pack Builder for air-gapped LLMs."
    )
    parser.add_argument(
        "--hf-dataset",
        type=str,
        default=None,
        help="Hugging Face dataset ID (e.g. ghananlpcommunity/ghana-farmer-qa)",
    )
    parser.add_argument(
        "--column",
        type=str,
        default="question",
        help="Column name in the dataset to use as queries (default: 'question')",
    )
    parser.add_argument(
        "--queries-file",
        type=str,
        default=None,
        help="Local file containing queries (.txt, .csv, .json, .jsonl)",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=None,
        help="Direct search query strings passed via command line",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=250,
        help="Maximum number of queries to process (default: 250)",
    )
    parser.add_argument(
        "--output-db",
        type=str,
        default="data/ghana_offline_pack.db",
        help="Output SQLite database path (default: data/ghana_offline_pack.db)",
    )
    parser.add_argument(
        "--export-jsonl",
        type=str,
        default=None,
        help="Optional path to export a JSONL dataset file",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default="news,academic,public_services,wikipedia",
        help="Comma-separated category filters (default: news,academic,public_services,wikipedia)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent query workers (default: 4)",
    )

    args = parser.parse_args()

    queries = []
    if args.queries:
        queries = args.queries
    elif args.hf_dataset:
        queries = fetch_queries_from_hf(
            dataset_name=args.hf_dataset,
            column=args.column,
            limit=args.limit,
        )
    elif args.queries_file:
        queries = load_queries_from_file(args.queries_file, column=args.column)[:args.limit]
    else:
        parser.print_help()
        sys.exit(1)

    if not queries:
        print("[-] No queries found to process.")
        sys.exit(1)

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    build_offline_pack(
        queries=queries,
        output_db_path=args.output_db,
        categories=cats,
        export_jsonl_path=args.export_jsonl,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()
