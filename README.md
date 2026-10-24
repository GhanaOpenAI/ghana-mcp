<p align="center">
  <img src="logo/Ghana%20Search%20logo@1x.png" width="340" alt="Ghana Search Logo">
</p>

# Ghana Search: Ghana's Information Retrieval Engine

Ghana Search is an information retrieval engine and Model Context Protocol (MCP) server that allows users, developers, and AI agents to search verified Ghanaian digital sources in real time.

Live search portal: [https://search.ghanaopenai.org](https://search.ghanaopenai.org)

---

## Supported Sources

Ghana Search queries the public search APIs of over 430 Ghanaian institutions and repositories, returning direct content URLs and downloadable PDFs rather than generic homepages:

- **Government Portals (164 websites)**: Direct search across ministries, departments, and agencies including the Ghana Revenue Authority (GRA), Food and Drugs Authority (FDA), Ghana Standards Authority (GSA), Ministry of Lands and Natural Resources, Lands Commission, and local assemblies.
- **District Assemblies (GhanaDistricts)**: News, development projects, and assembly reports across all 261 Ghanaian district assemblies.
- **Court Judgments and Legislation (GhaLII)**: Supreme Court, Court of Appeal, High Court rulings, Acts of Parliament, and Decrees with direct document and source download links.
- **Parliament of Ghana**: Official parliamentary Bills, Hansard records, and committee reports with direct PDF downloads.
- **University Theses and Research**: Academic research abstracts and direct PDF thesis download links from KNUST, University of Ghana (UGSpace), and University of Cape Coast (UCC).
- **National News Outlets**: Real-time articles from B&FT Online, 3News, Citi Newsroom, Ghana News Agency (GNA), Yen.com.gh, The Chronicle, Ghana Business News, and Starr FM.
- **Ghanaian Reference**: Scoped reference and historical background from Wikipedia (Ghana).

---

## Web Search Interface

Visit [https://search.ghanaopenai.org](https://search.ghanaopenai.org) to search directly from your browser.

- Enter any natural language question or topic.
- Automatic entity extraction and singular/plural inflection matching powered by spaCy NLP.
- 24-hour query caching for fast repeat searches.
- Direct "Download PDF" links for academic theses, court rulings, and parliamentary bills.
- Paginated results (10 per page) ordered by relevance.

---

## Querying the Search API

You can query Ghana Search programmatically via HTTP POST:

### Example Request (cURL)

```bash
curl -X POST https://search.ghanaopenai.org/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Ghana Revenue Authority VAT and electronic invoicing requirements",
    "top_k": 10
  }'
```

### Example Request (Python)

```python
import requests

response = requests.post(
    "https://search.ghanaopenai.org/api/search",
    json={
        "text": "renewable solar energy battery research KNUST",
        "top_k": 5
    }
)

for item in response.json().get("results", []):
    print(f"- {item['title']} ({item['source']})")
    print(f"  URL: {item['url']}\n")
```

### Request Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `text` | string | Required | Your question or search topic |
| `top_k` | integer | `50` | Number of ranked results to return (max 500) |
| `categories` | list | `all` | Optional filter: `["news", "academic", "public_services", "wikipedia"]` |
| `max_wait_seconds` | float | `3.0` | Maximum seconds to wait for providers before returning gathered results (supports up to 30.0s) |

---

## Connecting to AI Assistants (Claude Desktop / Cursor)

Ghana Search implements the Model Context Protocol (MCP) to allow AI assistants to query Ghanaian sources autonomously.

### Claude Desktop Configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ghana-search": {
      "command": "python3",
      "args": ["-m", "ghana_mcp.server", "--stdio"]
    }
  }
}
```

### Remote SSE Endpoint

For clients connecting over Server-Sent Events (SSE):
- URL: `https://search.ghanaopenai.org/mcp/sse`

---

## Offline Corpus and Backup

All permanently cached documents (titles, body text, publication dates, direct PDF URLs, and source metadata) are continuously backed up to the Hugging Face dataset repository:
- Dataset: [https://huggingface.co/datasets/ghanaopenai/ghana-search-corpus](https://huggingface.co/datasets/ghanaopenai/ghana-search-corpus)

This dataset can be downloaded to power fully local, offline MCP search servers without requiring internet access.

---

## Organization

Ghana Search is developed and maintained by **[Ghana Open AI](https://github.com/GhanaOpenAI)** ([https://ghanaopenai.org](https://ghanaopenai.org)).

## License

MIT License. See [LICENSE](LICENSE) for details.
