---
title: Ghana-MCP Explorer
emoji: 🌍
colorFrom: yellow
colorTo: green
sdk: static
pinned: false
license: mit
short_description: Local search & knowledge MCP demo for Ghana
---

# Ghana-MCP Explorer

Interactive demo space for **Ghana-MCP**, an open-source Model Context Protocol (MCP) server developed in partnership between **Ghana Open AI** and **Ghana NLP**.

This space allows testing queries across:
- **Local Ghanaian News Outlets**: B&FT Online, 3News, Yen.com.gh, Citi Newsroom, Ghana News Agency, The Chronicle, Ghana Business News, Starr FM.
- **Academic Research & Theses**: Kwame Nkrumah University of Science & Technology (KNUST), University of Ghana (UGSpace), and University of Cape Coast (UCC).
- **Public Services Directory**: 1,862 verified Ghanaian ministries, agencies, assemblies, and official public portals.
- **Wikipedia (Ghana)**: Location-tailored encyclopedic articles and summaries.
- **Hybrid Reranker (EmbeddingGemma + BGE-Reranker)**: High-throughput semantic relevance scoring to surface the top-k most accurate results.

### Connected Server
- Deployed MCP Server: Cloudflare Tunnel on H200 (`http://localhost:8800` / `mcp.ghanaopenai.org`)
- GitHub Repository: [GhanaOpenAI/ghana-mcp](https://github.com/GhanaOpenAI/ghana-mcp)
