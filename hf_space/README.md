---
title: Ghana Search Explorer
emoji: 🌍
colorFrom: yellow
colorTo: green
sdk: static
pinned: false
license: mit
short_description: National Information Retrieval Engine for Ghana
---

# Ghana Search Explorer

Interactive demo space for **Ghana Search**, an open-source National Information Retrieval Engine & Model Context Protocol (MCP) server developed by **Ghana Open AI**.

This space allows testing queries across:
- **Local Ghanaian News Outlets**: B&FT Online, 3News, Yen.com.gh, Citi Newsroom, Ghana News Agency, The Chronicle, Ghana Business News, Starr FM.
- **Academic Research & Theses**: Kwame Nkrumah University of Science & Technology (KNUST), University of Ghana (UGSpace), and University of Cape Coast (UCC).
- **Public Services & Law**: 164 verified Ghanaian ministries, agencies, assemblies, court judgments (GhaLII), and parliamentary records.
- **Wikipedia (Ghana)**: Location-tailored encyclopedic articles and summaries.
- **Hybrid Reranker (EmbeddingGemma + BGE-Reranker)**: High-throughput semantic relevance scoring to surface the top-k most accurate results.

### Connected Server
- Deployed MCP Server: Cloudflare Tunnel on H200 (`https://search.ghanaopenai.org`)
- GitHub Repository: [GhanaOpenAI/ghana-mcp](https://github.com/GhanaOpenAI/ghana-mcp)
