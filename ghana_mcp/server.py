"""Ghana Search Server: Ghana's Information Retrieval Engine & Model Context Protocol (MCP) Server.
Developed by Ghana Open AI.
"""
import os
import sys
import json
import asyncio
from typing import List, Optional, Dict
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
import uvicorn
from fastapi import FastAPI, Query, Body, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, PlainTextResponse, FileResponse
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ghana_mcp.providers.news import NewsProvider
from ghana_mcp.providers.wikipedia import WikipediaGhanaProvider
from ghana_mcp.providers.academic import AcademicProvider
from ghana_mcp.providers.public_services import PublicServicesProvider
from ghana_mcp.providers.ghalii import GhaLIIProvider
from ghana_mcp.providers.base import SearchResult
from ghana_mcp.reranker import reranker
from ghana_mcp.nlp import extract_search_terms
from ghana_mcp.analytics import analytics
from ghana_mcp.cache import search_cache
from ghana_mcp.hf_sync import hf_sync
from ghana_mcp.config import SERVER_HOST, SERVER_PORT

# Initialize providers
news_provider = NewsProvider()
wiki_provider = WikipediaGhanaProvider()
academic_provider = AcademicProvider()
public_provider = PublicServicesProvider()
ghalii_provider = GhaLIIProvider()

# Initialize MCP Server
mcp = MCPServer(
    name="ghana-search",
    title="Ghana Search Engine",
    description="Search Ghanaian local news, university thesis archives, government agencies, and Ghana Wikipedia with 24-hour caching and hybrid reranking.",
    version="1.0.0",
)


def _execute_search(
    text: str,
    categories: Optional[List[str]] = None,
    top_k: int = 50,
    rerank: bool = True,
    max_wait_seconds: float = 5.0,
    client_type: str = "mcp_tool",
    user_agent: str = "",
) -> List[SearchResult]:
    """Execute search across verified Ghanaian websites with 24-hour caching and evaluation logging."""
    if not text or not text.strip():
        return []

    import time
    start_time = time.perf_counter()

    # 1. Extract clean noun phrases and entity nouns via spaCy
    nlp_data = extract_search_terms(text)
    primary_query = nlp_data.get("primary_query") or text.strip()
    clean_chunks = nlp_data.get("clean_chunks", [])
    lemma_chunks = nlp_data.get("lemma_chunks", [])
    nouns = nlp_data.get("nouns", [])

    cats = categories or ["news", "wikipedia", "academic", "public_services"]

    # 2. Check 24-hour cache first (instant response for repeated queries)
    cached_results = search_cache.get(text, cats, top_k)
    if cached_results is not None:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        analytics.record_query_sync(
            query_text=text,
            clean_chunks=clean_chunks,
            num_results=len(cached_results),
            latency_ms=latency_ms,
            cached=True,
            client_type=client_type,
            user_agent=user_agent,
            categories=cats,
            sources={r.source: 1 for r in cached_results},
            top_results_summary=[
                {"title": r.title, "url": r.url, "source": r.source}
                for r in cached_results[:5]
            ],
        )
        return cached_results

    # Priority search terms: clean noun chunks first, followed by lemma chunks and individual nouns
    search_keywords = clean_chunks if clean_chunks else nouns
    if not search_keywords:
        search_keywords = [t for t in text.split() if len(t) > 1]

    candidates: List[SearchResult] = []
    per_provider_limit = min(max(int(top_k * 0.15), 6), 10)

    # 3. Parallel asynchronous dispatch across all selected providers
    tasks = []
    if "news" in cats:
        tasks.append(("news", lambda: news_provider.search(search_keywords, limit=per_provider_limit)))
    if "wikipedia" in cats:
        tasks.append(("wiki", lambda: wiki_provider.search(search_keywords, limit=min(per_provider_limit, 6))))
    if "academic" in cats:
        tasks.append(("academic", lambda: academic_provider.search(search_keywords, limit=per_provider_limit)))
    if "public_services" in cats:
        tasks.append(("public_services", lambda: public_provider.search(search_keywords, limit=per_provider_limit)))
        tasks.append(("ghalii", lambda: ghalii_provider.search(search_keywords, limit=min(per_provider_limit, 6))))

    from concurrent.futures import ThreadPoolExecutor, wait
    executor = ThreadPoolExecutor(max_workers=len(tasks) or 1)
    future_to_task = {executor.submit(fn): name for name, fn in tasks}
    # Wait strictly up to max_wait_seconds budget (default: 3.0s)
    done, not_done = wait(future_to_task.keys(), timeout=max_wait_seconds)
    for future in done:
        try:
            res = future.result()
            if res:
                candidates.extend(res)
        except Exception:
            pass
    # Shutdown without blocking for straggler workers
    executor.shutdown(wait=False, cancel_futures=True)

    # Deduplicate candidates by canonical URL and hydrate from permanent URL content cache
    seen_urls = set()
    unique_candidates: List[SearchResult] = []
    sources_count: Dict[str, int] = {}
    candidate_urls = [c.url for c in candidates if c.url]

    # Tier 2: Batch check permanent URL content cache (0ms SQLite lookup)
    permanent_cached_docs = search_cache.get_urls_batch(candidate_urls)

    for c in candidates:
        norm_url = c.url.strip().rstrip("/")
        if norm_url and norm_url not in seen_urls:
            seen_urls.add(norm_url)
            # If this URL was permanently cached previously, hydrate full body content & metadata
            if c.url in permanent_cached_docs:
                cached_doc = permanent_cached_docs[c.url]
                if not c.content and cached_doc.content:
                    c.content = cached_doc.content
                if not c.published_date and cached_doc.published_date:
                    c.published_date = cached_doc.published_date
                if cached_doc.metadata.get("pdf_url") and not c.metadata.get("pdf_url"):
                    c.metadata["pdf_url"] = cached_doc.metadata["pdf_url"]
            unique_candidates.append(c)
            sources_count[c.source] = sources_count.get(c.source, 0) + 1
        elif not norm_url and c.title not in seen_urls:
            seen_urls.add(c.title)
            unique_candidates.append(c)
            sources_count[c.source] = sources_count.get(c.source, 0) + 1

    effective_k = min(top_k, len(unique_candidates)) if len(unique_candidates) > 0 else top_k

    # 4. 100% CPU Terminology Density & Recency Reranking
    if rerank and unique_candidates:
        ranked = reranker.rerank(
            query=text,
            keywords=search_keywords,
            candidates=unique_candidates,
            top_k=effective_k,
        )
    else:
        ranked = unique_candidates[:effective_k]

    # Tier 2: Permanently store all unique documents per URL (title, content, date saved forever)
    search_cache.set_urls_batch(unique_candidates)

    # Tier 1: Store ranked query results in 24-hour cache
    search_cache.set(text, cats, top_k, ranked)

    # Record evaluation dataset & analytics non-blockingly
    latency_ms = (time.perf_counter() - start_time) * 1000.0
    analytics.record_query_sync(
        query_text=text,
        clean_chunks=clean_chunks,
        num_results=len(ranked),
        latency_ms=latency_ms,
        cached=False,
        client_type=client_type,
        user_agent=user_agent,
        categories=cats,
        sources=sources_count,
        top_results_summary=[
            {"title": r.title, "url": r.url, "source": r.source}
            for r in ranked[:5]
        ],
    )

    return ranked


# --- MCP Tool Registrations ---


@mcp.tool()
def ghana_search(
    text: str,
    top_k: int = 50,
    categories: Optional[List[str]] = None,
    rerank: bool = True,
    max_wait_seconds: float = 5.0,
) -> str:
    """Search Ghanaian local news, university thesis archives, government agencies, and Ghana Wikipedia.
    Takes free-form text input, extracts nouns using spaCy, queries local APIs, and ranks results by relevance.

    Args:
        text: Free-form text input or query from the LLM (e.g. "Who is the current president of Ghana?", "Research on solar energy from KNUST and UCC", "Ghana Revenue Authority tax requirements")
        top_k: Number of most relevant results to return (default: 50, maximum: total retrieved candidates)
        categories: Optional list of data sources to query: ["news", "wikipedia", "academic", "public_services"]
        rerank: Whether to rerank candidates by terminology and recency (default: True)
        max_wait_seconds: Maximum seconds to wait for external providers before returning results (default: 5.0s)
    """
    results = _execute_search(text, categories, top_k, rerank, max_wait_seconds=max_wait_seconds)
    return json.dumps([r.to_dict() for r in results], indent=2)


@mcp.tool()
def ghana_news_search(
    text: str,
    top_k: int = 50,
) -> str:
    """Search live Ghanaian online news outlets with verified public APIs (B&FT Online, 3News, Yen.com.gh, Citi Newsroom, GNA, Chronicle, GBN, Starr FM).
    Extracts nouns via spaCy and returns articles ordered by relevance.

    Args:
        text: News search query or phrase (e.g. "Ghana cedi exchange rate and Bank of Ghana inflation update")
        top_k: Number of relevant articles to return (default: 50)
    """
    results = _execute_search(text, categories=["news"], top_k=top_k, rerank=True)
    return json.dumps([r.to_dict() for r in results], indent=2)


@mcp.tool()
def ghana_academic_search(
    text: str,
    top_k: int = 50,
) -> str:
    """Search Ghanaian university institutional repositories (KNUST, University of Ghana, UCC) for academic thesis abstracts.
    Extracts key research terms via spaCy and returns abstracts with official handle links.

    Args:
        text: Academic research topic (e.g. "renewable solar energy storage and battery technology")
        top_k: Number of thesis abstracts to return (default: 50)
    """
    results = _execute_search(text, categories=["academic"], top_k=top_k, rerank=True)
    return json.dumps([r.to_dict() for r in results], indent=2)


@mcp.tool()
def ghana_public_services_search(
    text: str,
    top_k: int = 50,
) -> str:
    """Search 1,862 Ghanaian public sector institutions, ministries, departments, assemblies, and official service portals.

    Args:
        text: Government department or citizen service (e.g. "business registration, passport office, GRA tax filing")
        top_k: Number of public entities to return (default: 50)
    """
    results = _execute_search(text, categories=["public_services"], top_k=top_k, rerank=True)
    return json.dumps([r.to_dict() for r in results], indent=2)


@mcp.tool()
def ghana_wikipedia_search(
    text: str,
    top_k: int = 50,
) -> str:
    """Search Wikipedia with location and context set to Ghana for background history, leaders, and landmarks.

    Args:
        text: Topic of interest (e.g. "Founding fathers of Ghana and 1992 constitution")
        top_k: Number of Wikipedia summaries to return (default: 50)
    """
    results = _execute_search(text, categories=["wikipedia"], top_k=top_k, rerank=True)
    return json.dumps([r.to_dict() for r in results], indent=2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle cleanly."""
    await analytics.start()
    await hf_sync.start()
    yield
    await hf_sync.stop()
    await analytics.stop()


# --- FastAPI REST App & Web Interface ---

app = FastAPI(
    title="Ghana Search API",
    description="Ghana Search: National Information Retrieval Engine. Developed by Ghana Open AI.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/mcp",
    mcp.sse_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    ),
)


class SearchRequest(BaseModel):
    text: str = Field(..., description="Free-form query text input")
    categories: Optional[List[str]] = Field(
        default=["news", "wikipedia", "academic", "public_services"],
        description="Categories to search",
    )
    top_k: int = Field(default=50, ge=1, le=500, description="Number of results to return (default: 50)")
    rerank: bool = Field(default=True, description="Enable hybrid semantic reranking")
    max_wait_seconds: float = Field(default=5.0, ge=0.5, le=30.0, description="Maximum seconds to wait for external providers (default: 5.0s)")


@app.post("/api/search")
async def api_search_post(req: SearchRequest = Body(...)):
    """REST API endpoint taking raw text input (non-blocking concurrent execution)."""
    nlp_data = extract_search_terms(req.text)
    results = await asyncio.to_thread(
        _execute_search,
        text=req.text,
        categories=req.categories,
        top_k=req.top_k,
        rerank=req.rerank,
        max_wait_seconds=req.max_wait_seconds,
    )
    return {
        "status": "success",
        "input_text": req.text,
        "extracted_terms": {
            "clean_noun_chunks": nlp_data.get("clean_chunks", []),
            "lemma_chunks": nlp_data.get("lemma_chunks", []),
            "nouns": nlp_data.get("nouns", []),
            "primary_query": nlp_data.get("primary_query", ""),
        },
        "count": len(results),
        "requested_top_k": req.top_k,
        "results": [r.to_dict() for r in results],
    }


@app.get("/api/search")
async def api_search_get(
    text: Optional[str] = Query(None, description="Free-form text input"),
    query: Optional[str] = Query(None, description="Alias for text"),
    categories: Optional[str] = Query(None, description="Comma-separated categories"),
    top_k: int = Query(50, ge=1, le=500),
    rerank: bool = Query(True),
    max_wait_seconds: float = Query(5.0, ge=0.5, le=30.0),
):
    """GET REST endpoint for quick URL queries (non-blocking concurrent execution)."""
    input_str = text or query or ""
    cat_list = [c.strip() for c in categories.split(",")] if categories else None
    results = await asyncio.to_thread(
        _execute_search,
        text=input_str,
        categories=cat_list,
        top_k=top_k,
        rerank=rerank,
        max_wait_seconds=max_wait_seconds,
    )
    nlp_data = extract_search_terms(input_str)
    return {
        "status": "success",
        "input_text": input_str,
        "extracted_terms": {
            "clean_noun_chunks": nlp_data.get("clean_chunks", []),
            "lemma_chunks": nlp_data.get("lemma_chunks", []),
            "nouns": nlp_data.get("nouns", []),
        },
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }


@app.get("/api/analytics/stats")
async def api_analytics_stats():
    """Return live usage statistics, query latency, cache hit rate, and trending topics."""
    return analytics.get_stats()


@app.get("/api/analytics/dataset")
async def api_analytics_dataset(
    format: str = Query("json", description="Export format: 'json' or 'jsonl'"),
    limit: int = Query(500, ge=1, le=5000),
):
    """Export logged evaluation dataset for offline testing and model improvement."""
    records = analytics.export_dataset(limit=limit)
    if format == "jsonl":
        lines = [json.dumps(r, ensure_ascii=False) for r in records]
        return PlainTextResponse(
            "\n".join(lines),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=query_evaluation_dataset.jsonl"},
        )
    return {
        "status": "success",
        "count": len(records),
        "records": records,
    }


@app.post("/api/analytics/backup-hf")
async def api_backup_hf():
    """Trigger an immediate background backup push of the permanent URL cache to Hugging Face."""
    result = await asyncio.to_thread(hf_sync.push_to_huggingface)
    return result


@app.get("/api/health")
async def api_health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "ghana-search",
        "version": "1.0.0",
        "nlp_engine": "spaCy (en_core_web_sm)",
        "reranker": "100% CPU Terminology Density & Recency (Zero GPU / 0MB VRAM)",
        "caching": "Two-Tier (24h Query Cache + Permanent URL Content Cache)",
        "default_max_wait_seconds": 5.0,
        "evaluation_dataset": "Enabled (JSONL export)",
        "hf_backup_repo": "ghanaopenai/ghana-search-corpus",
        "organization": "Ghana Open AI",
        "endpoints": {
            "mcp_sse": "/mcp/sse",
            "rest_search": "/api/search",
            "analytics_stats": "/api/analytics/stats",
            "analytics_dataset": "/api/analytics/dataset",
            "backup_hf": "/api/analytics/backup-hf",
            "web_ui": "/",
        },
    }


static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    @app.head("/")
    @app.get("/demo", response_class=HTMLResponse)
    @app.head("/demo")
    async def serve_index():
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse("<h1>Ghana Search Server</h1>")

    @app.get("/favicon.ico")
    async def serve_favicon():
        favicon_path = os.path.join(static_dir, "images", "favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path, media_type="image/x-icon")
        return Response(status_code=404)


def run():
    """CLI Entrypoint to start the server with automatic multi-core worker scaling."""
    if "--stdio" in sys.argv:
        asyncio.run(mcp.run_stdio_async())
    else:
        port = int(os.environ.get("PORT", SERVER_PORT))
        host = os.environ.get("HOST", SERVER_HOST)
        # Default to 4 workers on multi-core environments, or scale to available CPU cores
        default_workers = min(4, max(1, os.cpu_count() or 1))
        workers = int(os.environ.get("WEB_CONCURRENCY", default_workers))
        print(f"🚀 Starting Ghana Search Engine on http://{host}:{port} with {workers} worker processes")
        print(f"   MCP SSE Endpoint: http://{host}:{port}/mcp/sse")
        print(f"   REST Search API:  http://{host}:{port}/api/search")
        print(f"   Interactive UI:   http://{host}:{port}/")
        uvicorn.run("ghana_mcp.server:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    run()
