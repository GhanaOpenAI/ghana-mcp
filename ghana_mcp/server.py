"""Ghana-MCP Server: Model Context Protocol (MCP) and REST API Server.
A joint partnership between Ghana Open AI and Ghana NLP.
"""
import os
import sys
import json
import asyncio
from typing import List, Optional
from pydantic import BaseModel, Field
import uvicorn
from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from mcp.server.mcpserver import MCPServer

from ghana_mcp.providers.news import NewsProvider
from ghana_mcp.providers.wikipedia import WikipediaGhanaProvider
from ghana_mcp.providers.academic import AcademicProvider
from ghana_mcp.providers.public_services import PublicServicesProvider
from ghana_mcp.providers.base import SearchResult
from ghana_mcp.reranker import reranker
from ghana_mcp.nlp import extract_search_terms
from ghana_mcp.analytics import analytics
from ghana_mcp.config import SERVER_HOST, SERVER_PORT

# Initialize providers
news_provider = NewsProvider()
wiki_provider = WikipediaGhanaProvider()
academic_provider = AcademicProvider()
public_provider = PublicServicesProvider()

# Initialize MCP Server
mcp = MCPServer(
    name="ghana-mcp",
    title="Ghana Local Knowledge & Web Search MCP",
    description="Search Ghanaian local news, university thesis archives, government agencies, and Ghana Wikipedia using spaCy noun extraction and high-throughput reranking.",
    version="1.0.0",
)


def _execute_search(
    text: str,
    categories: Optional[List[str]] = None,
    top_k: int = 50,
    rerank: bool = True,
    client_type: str = "mcp_tool",
    user_agent: str = "",
) -> List[SearchResult]:
    """Execute search across verified Ghanaian websites using spaCy noun extraction."""
    if not text or not text.strip():
        return []

    t0 = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0.0
    import time
    start_time = time.perf_counter()

    # 1. Extract clean noun phrases and entity nouns via spaCy
    nlp_data = extract_search_terms(text)
    primary_query = nlp_data.get("primary_query") or text.strip()
    clean_chunks = nlp_data.get("clean_chunks", [])
    lemma_chunks = nlp_data.get("lemma_chunks", [])
    nouns = nlp_data.get("nouns", [])

    # Priority search terms: clean noun chunks first, followed by lemma chunks and individual nouns
    search_keywords = clean_chunks if clean_chunks else nouns
    if not search_keywords:
        search_keywords = [t for t in text.split() if len(t) > 1]

    cats = categories or ["news", "wikipedia", "academic", "public_services"]
    candidates: List[SearchResult] = []

    # Calculate provider limits to ensure we gather enough candidates for top_k (default 50)
    per_provider_limit = max(int(top_k * 0.4), 10)

    # 2. Gather candidates from verified sources
    if "news" in cats:
        candidates.extend(news_provider.search(search_keywords, limit=per_provider_limit))
    if "wikipedia" in cats:
        candidates.extend(wiki_provider.search(search_keywords, limit=min(per_provider_limit, 10)))
    if "academic" in cats:
        candidates.extend(academic_provider.search(search_keywords, limit=per_provider_limit))
    if "public_services" in cats:
        candidates.extend(public_provider.search(search_keywords, limit=per_provider_limit))

    # Deduplicate candidates by canonical URL
    seen_urls = set()
    unique_candidates: List[SearchResult] = []
    sources_count: Dict[str, int] = {}
    for c in candidates:
        norm_url = c.url.strip().rstrip("/")
        if norm_url and norm_url not in seen_urls:
            seen_urls.add(norm_url)
            unique_candidates.append(c)
            sources_count[c.source] = sources_count.get(c.source, 0) + 1
        elif not norm_url and c.title not in seen_urls:
            seen_urls.add(c.title)
            unique_candidates.append(c)
            sources_count[c.source] = sources_count.get(c.source, 0) + 1

    # The maximum returned is all retrieved candidates
    effective_k = min(top_k, len(unique_candidates)) if len(unique_candidates) > 0 else top_k

    # 3. High-throughput reranking (vLLM / BM25 fallback)
    if rerank and unique_candidates:
        ranked = reranker.rerank(
            query=text,
            keywords=search_keywords,
            candidates=unique_candidates,
            top_k=effective_k,
        )
    else:
        ranked = unique_candidates[:effective_k]

    # Record non-blocking analytics
    latency_ms = (time.perf_counter() - start_time) * 1000.0
    analytics.record_query_sync(
        query_text=text,
        clean_chunks=clean_chunks,
        num_results=len(ranked),
        latency_ms=latency_ms,
        client_type=client_type,
        user_agent=user_agent,
        categories=cats,
        sources=sources_count,
    )

    return ranked


# --- MCP Tool Registrations ---


@mcp.tool()
def ghana_search(
    text: str,
    top_k: int = 50,
    categories: Optional[List[str]] = None,
    rerank: bool = True,
) -> str:
    """Search Ghanaian local news, university thesis archives, government agencies, and Ghana Wikipedia.
    Takes free-form text input, extracts nouns using spaCy, queries local APIs, and ranks results by relevance.

    Args:
        text: Free-form text input or query from the LLM (e.g. "Who is the current president of Ghana?", "Research on solar energy from KNUST and UCC", "Ghana Revenue Authority tax requirements")
        top_k: Number of most relevant results to return (default: 50, maximum: total retrieved candidates)
        categories: Optional list of data sources to query: ["news", "wikipedia", "academic", "public_services"]
        rerank: Whether to use Gemini 2.5 Flash to rerank candidates by relevance (default: True)
    """
    results = _execute_search(text, categories, top_k, rerank)
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


# --- FastAPI REST App & Web Interface ---

app = FastAPI(
    title="Ghana-MCP API",
    description="Ghanaian Local Search & Knowledge MCP Server. Joint partnership between Ghana Open AI and Ghana NLP.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/mcp", mcp.sse_app())


class SearchRequest(BaseModel):
    text: str = Field(..., description="Free-form query text input")
    categories: Optional[List[str]] = Field(
        default=["news", "wikipedia", "academic", "public_services"],
        description="Categories to search",
    )
    top_k: int = Field(default=50, ge=1, le=100, description="Number of results to return (default: 50)")
    rerank: bool = Field(default=True, description="Enable Gemini AI semantic reranking")


@app.post("/api/search")
async def api_search_post(req: SearchRequest = Body(...)):
    """REST API endpoint taking raw text input."""
    nlp_data = extract_search_terms(req.text)
    results = _execute_search(
        text=req.text,
        categories=req.categories,
        top_k=req.top_k,
        rerank=req.rerank,
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
    top_k: int = Query(50, ge=1, le=100),
    rerank: bool = Query(True),
):
    """GET REST endpoint for quick URL queries."""
    input_str = text or query or ""
    cat_list = [c.strip() for c in categories.split(",")] if categories else None
    results = _execute_search(
        text=input_str,
        categories=cat_list,
        top_k=top_k,
        rerank=rerank,
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


@app.on_event("startup")
async def startup_event():
    """Start background analytics worker."""
    await analytics.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop background analytics worker."""
    await analytics.stop()


@app.get("/api/analytics/stats")
async def api_analytics_stats():
    """Return live usage statistics, query latency, and trending Ghanaian topics."""
    return analytics.get_stats()


@app.get("/api/health")
async def api_health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "ghana-mcp",
        "version": "1.0.0",
        "nlp_engine": "spaCy (en_core_web_sm)",
        "reranker": "EmbeddingGemma (vLLM / BM25 fallback)",
        "partnership": "Ghana Open AI x Ghana NLP",
        "endpoints": {
            "mcp_sse": "/mcp/sse",
            "rest_search": "/api/search",
            "analytics_stats": "/api/analytics/stats",
            "web_ui": "/",
        },
    }


static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse("<h1>Ghana-MCP Server</h1>")


def run():
    """CLI Entrypoint to start the server."""
    if "--stdio" in sys.argv:
        asyncio.run(mcp.run_stdio_async())
    else:
        port = int(os.environ.get("PORT", SERVER_PORT))
        host = os.environ.get("HOST", SERVER_HOST)
        print(f"🚀 Starting Ghana-MCP Server on http://{host}:{port}")
        print(f"   MCP SSE Endpoint: http://{host}:{port}/mcp/sse")
        print(f"   REST Search API:  http://{host}:{port}/api/search")
        print(f"   Interactive UI:   http://{host}:{port}/")
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
