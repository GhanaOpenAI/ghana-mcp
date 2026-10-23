# Ghana Search: National Information Retrieval Engine 🇬🇭

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Hugging Face Space](https://img.shields.io/badge/%F0%9F%A4%97%20Demo-Ghana%20Search-yellow)](https://huggingface.co/spaces/ghanaopenai/ghana-mcp-demo)
[![Organization](https://img.shields.io/badge/Developed%20by-Ghana%20Open%20AI-gold)](https://ghanaopenai.org)
[![Protocol: MCP](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%202.x-blue)](https://modelcontextprotocol.io/)

A high-performance **Model Context Protocol (MCP)** server and national information retrieval engine that connects Large Language Model (LLM) providers (Claude, Cursor, OpenAI, ChatGPT, custom agents) directly to verified **local Ghanaian digital sources**: real-time news outlets, academic research repositories, 164+ public service portals, court judgments (GhaLII), parliamentary records, and location-tailored Wikipedia background.

---

## 🏛️ Organization

Developed and maintained by **[Ghana Open AI](https://github.com/GhanaOpenAI)** (`https://ghanaopenai.org`).

---

## 🌟 Key Architecture & Capabilities

1. **Free-Form Text Input (No Rigid Keywords Required)**:
   - LLMs simply provide natural language text or user questions.
   - Powered by **spaCy (`en_core_web_sm`)**, the server automatically extracts and cleans **core noun chunks**, stripping extraneous adjectives, determiners/articles, pronouns, adverbs, and possessives.
   - Handles **singular and plural inflection variants** (e.g. `tax`/`taxes`, `battery`/`batteries`, `service`/`services`, `minister`/`ministers`) to guarantee high search recall across local databases.

2. **Default 50 Most Relevant Results (Scalable to Max Retrieved)**:
   - Defaults to returning the **top 50** most relevant items.
   - Users can specify any custom `top_k` (e.g. 10, 25, 75, 100), with the upper bound being the full volume of candidates retrieved for those phrases.

3. **Hybrid Neural Reranking Pipeline**:
   - **Stage 1 (EmbeddingGemma-2)**: High-throughput dense vector embeddings narrow candidates down by cosine similarity.
   - **Stage 2 (BGE-Reranker-v2-M3)**: Full cross-encoder attention computes exact pairwise relevance scores.
   - **Sub-Millisecond Fallback**: Instant BM25 + noun-overlap lexical scoring ensures zero downtime and sub-millisecond response even if neural inference engines reboot.

4. **Embedded SQLite WAL Analytics Engine**:
   - Uses SQLite in WAL (Write-Ahead Logging) mode with background asynchronous queues.
   - Zero-overhead tracking of query volume, latency distribution, trending Ghanaian search terms, and client types (MCP vs. REST vs. Web).
   - Viewable live via `/api/analytics/stats` or the built-in Web Analytics tab.

5. **Cloudflare Tunnel Security & Anti-Abuse**:
   - Deployed on our NVIDIA H200 GPU instance and routed via **Cloudflare Tunnel** (`mcp.ghanaopenai.org`).
   - Enterprise-grade DDoS protection, WAF rate-limiting, and Bot Management to prevent scraper abuse on public endpoints.

---

## 🌐 Supported Ghanaian Sources & Verified APIs

All included websites have been individually probed and verified for public programmatic search API access:

### 1. Online News Portals (Live JSON / REST Endpoints)

| Outlet | Platform / Architecture | API Endpoint | Avg Latency |
| :--- | :--- | :--- | :---: |
| **B&FT Online** | Next.js + Payload CMS | `GET https://thebftonline.com/api/search?query={q}` | **~0.52s** |
| **Ghana Business News** | WordPress REST API | `GET https://www.ghanabusinessnews.com/wp-json/wp/v2/posts?search={q}` | **~0.31s** |
| **3News (TV3)** | Next.js App Router | `GET https://3news.com/api/search?q={q}` | **~1.17s** |
| **Yen.com.gh** | AJAX Search Engine | `POST/GET https://yen.com.gh/ajax/search/?query={q}` | **~1.52s** |
| **The Chronicle Ghana** | WordPress REST API | `GET https://thechronicle.com.gh/wp-json/wp/v2/posts?search={q}` | **~1.80s** |
| **Citi Newsroom** | WordPress REST API | `GET https://citinewsroom.com/wp-json/wp/v2/posts?search={q}` | **~2.80s** |
| **Ghana News Agency (GNA)** | WordPress REST API | `GET https://gna.org.gh/wp-json/wp/v2/posts?search={q}` | **~4.00s** |
| **Starr FM Online** | WordPress REST API | `GET https://starrfm.com.gh/wp-json/wp/v2/posts?search={q}` | **~3.80s** |

> *Note on Gated Outlets*: Portals protected by Cloudflare Managed Challenges or crypto anti-bot verification (GhanaWeb, Graphic Online, Modern Ghana, Asaase Radio) have been intentionally omitted from direct automated queries.

### 2. University Academic Research & Theses (DSpace 7 REST APIs)

Queries official institutional repositories for full thesis abstracts, academic departments, author lists, and persistent handle URIs:
* **Kwame Nkrumah University of Science and Technology (KNUST)**: `https://ir.knust.edu.gh/server/api/discover/search/objects`
* **University of Ghana (UGSpace / Balme Library)**: `https://ugspace.ug.edu.gh/server/api/discover/search/objects`
* **University of Cape Coast (UCC ERL)**: `https://erl.ucc.edu.gh/server/api/discover/search/objects`
* Local indexed corpus fallback from the **Ghana Research Corpus** (KNUST, UCC, UEW, Ashesi).

### 3. Public Services & Government Institutions Directory

* Bundled directory of **1,862 verified Ghanaian public sector entities**: Ministries, Departments, Agencies (MDAs), and Metropolitan, Municipal, and District Assemblies (MMDAs).
* Provides agency aliases, parent ministries, official `.gov.gh` URLs, physical addresses, and GhanaPost GPS digital addresses.
* Live REST querying for active government service portals including the **Ghana Revenue Authority (GRA)** and **Ghana Standards Authority (GSA)**.

### 4. Wikipedia (Ghana Context)

* Uses MediaWiki CirrusSearch scoped to Ghana and MediaWiki Geosearch centered on Accra (`5.6037° N, 0.1870° W`) for background context, constitutional records, and landmark locations.

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/GhanaOpenAI/ghana-mcp.git
cd ghana-mcp

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
* **Web Demo UI**: `http://localhost:8080/`
* **REST Search API**: `http://localhost:8080/api/search`
* **MCP SSE Endpoint**: `http://localhost:8080/mcp/sse`
* **Analytics Stats**: `http://localhost:8080/api/analytics/stats`
* **Health Check**: `http://localhost:8080/api/health`

---

## 🔌 Connecting to LLM Clients (MCP Configuration)

### 1. Claude Desktop

Add to your `claude_desktop_config.json` (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "ghana-search": {
      "command": "/path/to/ghana-mcp/.venv/bin/python3",
      "args": ["-m", "ghana_mcp.server", "--stdio"]
    }
  }
}
```

### 2. Remote Cloudflare Tunnel Endpoint (No local install needed)

When querying via remote SSE:
* **URL**: `https://search.ghanaopenai.org/mcp/sse`
* **Transport**: `sse`

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

## 🛠️ MCP Tools Exposed

* `ghana_search(text, top_k=50, categories=None, rerank=True)`: Unified multi-source search across all verified Ghanaian domains with NLP noun extraction and hybrid reranking.
* `ghana_news_search(text, top_k=50)`: Scoped live search across top Ghanaian online news platforms.
* `ghana_academic_search(text, top_k=50)`: Scoped search for university thesis abstracts from KNUST, UG, and UCC.
* `ghana_public_services_search(text, top_k=50)`: Scoped search across 164 verified Ghanaian public sector institutions and portals.
* `ghana_wikipedia_search(text, top_k=50)`: Scoped search for Ghana-focused encyclopedic articles.

---

## 📊 Live Web Demo & Hugging Face Space

Experience the interactive web UI, test search phrases, and view live usage analytics:
👉 **[https://huggingface.co/spaces/ghanaopenai/ghana-mcp-demo](https://huggingface.co/spaces/ghanaopenai/ghana-mcp-demo)**

---

## 📜 License

Licensed under the [MIT License](LICENSE). Maintained by Ghana Open AI.
