"""Configuration and constants for Ghana-MCP."""
import os

# Optional Gemini API key (defaults to empty since we use self-hosted EmbeddingGemma + BGE-Reranker)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SERVER_HOST = os.environ.get("HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("PORT", "8080"))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "Ghana-MCP/1.0 (+https://github.com/GhanaOpenAI/ghana-mcp)"
)

DEFAULT_TIMEOUT = 8.0  # seconds per external API query
