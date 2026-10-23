<p align="center">
  <img src="logo/Ghana%20Search%20logo@1x.png" width="360" alt="Ghana Search Logo">
</p>

# Ghana Search: National Information Retrieval Engine

A high-performance Model Context Protocol (MCP) server and national information retrieval engine that connects Large Language Model (LLM) agents (Claude, Cursor, LangChain, custom applications) directly to verified local Ghanaian digital sources: real-time news outlets, academic research repositories, 164 verified government portals, Supreme Court judgments (GhaLII), parliamentary records, and location-tailored Wikipedia background.

---

## Organization

Developed and maintained by **[Ghana Open AI](https://github.com/GhanaOpenAI)** ([https://ghanaopenai.org](https://ghanaopenai.org)).

---

## Key Architecture and Capabilities

1. **Free-Form Text Input (No Rigid Keywords Required)**:
   - LLMs provide natural language text or user questions.
   - Powered by spaCy (`en_core_web_sm`), the server extracts and cleans core noun chunks by removing determiners, articles, pronouns, adverbs, and possessives.
   - Handles singular and plural inflection variants (e.g. `tax`/`taxes`, `battery`/`batteries`, `service`/`services`, `minister`/`ministers`) to guarantee high search recall across local databases.

2. **Default 50 Most Relevant Results (Scalable to Full Retrieved Pool)**:
   - Defaults to returning the top 50 most relevant items.
   - Users can specify any custom `top_k` (up to 500), with the upper bound being the full volume of candidates retrieved for those phrases.

3. **Hybrid Neural Reranking Pipeline**:
   - Stage 1 (EmbeddingGemma-2): High-throughput dense vector embeddings narrow candidates down by cosine similarity.
   - Stage 2 (BGE-Reranker-v2-M3): Full cross-encoder attention computes exact pairwise relevance scores.
   - Sub-Millisecond Fallback: BM25 and noun-overlap lexical scoring ensures zero downtime and sub-millisecond response even during model reboots.

4. **Embedded SQLite WAL Analytics Engine**:
   - Uses SQLite in WAL (Write-Ahead Logging) mode with background asynchronous queues.
   - Zero-overhead tracking of query volume, latency distribution, trending Ghanaian search terms, and client types.
   - Accessible via `/api/analytics/stats` and downloadable as continuous evaluation dataset (`.jsonl`).

5. **Cloudflare Tunnel Security**:
   - Deployed on our NVIDIA H200 GPU instance and routed via Cloudflare Tunnel (`search.ghanaopenai.org`).
   - Enterprise-grade DDoS protection, WAF rate-limiting, and Bot Management to prevent scraper abuse on public endpoints.

---

## Supported Ghanaian Sources and Verified APIs

All included websites have been individually probed and verified for public programmatic search API access:

### 1. Online News Portals (Live JSON / REST Endpoints)

| Outlet | Platform / Architecture | API Endpoint | Avg Latency |
| :--- | :--- | :--- | :---: |
| B&FT Online | Next.js + Payload CMS | `GET https://thebftonline.com/api/search?query={q}` | ~0.52s |
| Ghana Business News | WordPress REST API | `GET https://www.ghanabusinessnews.com/wp-json/wp/v2/posts?search={q}` | ~0.31s |
| 3News (TV3) | Next.js App Router | `GET https://3news.com/api/search?q={q}` | ~1.17s |
| Yen.com.gh | AJAX Search Engine | `POST/GET https://yen.com.gh/ajax/search/?query={q}` | ~1.52s |
| The Chronicle Ghana | WordPress REST API | `GET https://thechronicle.com.gh/wp-json/wp/v2/posts?search={q}` | ~1.80s |
| Citi Newsroom | WordPress REST API | `GET https://citinewsroom.com/wp-json/wp/v2/posts?search={q}` | ~2.80s |
| Ghana News Agency (GNA) | WordPress REST API | `GET https://gna.org.gh/wp-json/wp/v2/posts?search={q}` | ~4.00s |
| Starr FM Online | WordPress REST API | `GET https://starrfm.com.gh/wp-json/wp/v2/posts?search={q}` | ~3.80s |

> Note: Portals protected by Cloudflare Managed Challenges or crypto anti-bot verification (GhanaWeb, Graphic Online, Modern Ghana, Asaase Radio) are omitted from direct automated queries.

### 2. University Academic Research and Theses (DSpace 7 REST APIs)

Queries official institutional repositories for full thesis abstracts, academic departments, author lists, and direct downloadable PDF URLs:
- Kwame Nkrumah University of Science and Technology (KNUST): `https://ir.knust.edu.gh/server/api/discover/search/objects`
- University of Ghana (UGSpace / Balme Library): `https://ugspace.ug.edu.gh/server/api/discover/search/objects`
- University of Cape Coast (UCC ERL): `https://erl.ucc.edu.gh/server/api/discover/search/objects`
- Parliament of Ghana Repository: `https://repository.parliament.gh/server/api/discover/search/objects`
- Local indexed corpus fallback from the Ghana Research Corpus (KNUST, UCC, UEW, Ashesi).

### 3. Public Services, Courts, and Government Institutions

- 164 verified Ghanaian public sector portals with active WordPress REST content search endpoints (GRA, GSA, FDA, MLNR, MIIF, Lands Commission, assemblies).
- Ghana Legal Information Institute (GhaLII): Search API for Supreme Court, Court of Appeal, High Court judgments, Acts of Parliament, and Decrees with direct download links.
- GhanaDistricts: Assembly news, projects, and reports across all 261 Ghanaian district assemblies.

### 4. Wikipedia (Ghana Context)

- Uses MediaWiki CirrusSearch scoped to Ghana and MediaWiki Geosearch centered on Accra (5.6037 N, 0.1870 W) for background context, constitutional records, and landmark locations.

---

## Quick Start

### Installation

```bash
git clone https://github.com/GhanaOpenAI/ghana-search.git
cd ghana-search

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and spaCy language model
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### Run Locally

```bash
# Start the HTTP / SSE / REST Web Server
python3 -m ghana_mcp.server

# Or start directly in standard MCP stdio mode (for Claude Desktop / Cursor)
python3 -m ghana_mcp.server --stdio
```

Server endpoints:
- Web Demo UI: `http://localhost:8000/`
- REST Search API: `http://localhost:8000/api/search`
- MCP SSE Endpoint: `http://localhost:8000/mcp/sse`
- Analytics Stats: `http://localhost:8000/api/analytics/stats`
- Dataset Export: `http://localhost:8000/api/analytics/dataset?format=jsonl`
- Health Check: `http://localhost:8000/api/health`

---

## Connecting to LLM Clients (MCP Configuration)

### 1. Claude Desktop (Local Subprocess / stdio)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ghana-search": {
      "command": "/path/to/ghana-search/.venv/bin/python3",
      "args": ["-m", "ghana_mcp.server", "--stdio"]
    }
  }
}
```

### 2. Remote Cloudflare Endpoint (Production)

When querying via remote SSE:
- URL: `https://search.ghanaopenai.org/mcp/sse`
- Transport: `sse`

### 3. REST API Example (cURL / Python / Node)

```bash
curl -X POST https://search.ghanaopenai.org/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Who is the current president of Ghana and what are his recent policies?",
    "top_k": 50
  }'
```

---

## MCP Tools Exposed

- `ghana_search(text, top_k=50, categories=None, rerank=True)`: Unified multi-source search across all verified Ghanaian domains with NLP noun extraction and hybrid reranking.
- `ghana_news_search(text, top_k=50)`: Scoped live search across top Ghanaian online news platforms.
- `ghana_academic_search(text, top_k=50)`: Scoped search for university thesis abstracts from KNUST, UG, UCC, and Parliament with direct PDF resolution.
- `ghana_public_services_search(text, top_k=50)`: Scoped search across 164 verified Ghanaian public sector institutions and legal portals (GhaLII, GhanaDistricts).
- `ghana_wikipedia_search(text, top_k=50)`: Scoped search for Ghana-focused encyclopedic articles.

---

## Live Web Portal and Hugging Face Space

- Production Web Engine: [https://search.ghanaopenai.org](https://search.ghanaopenai.org)
- Hugging Face Space: [https://huggingface.co/spaces/ghanaopenai/ghana-search](https://huggingface.co/spaces/ghanaopenai/ghana-search)

---

## License

Licensed under the [MIT License](LICENSE). Maintained by Ghana Open AI.
