"""Configuration and constants for Ghana-MCP."""
import os
import socket

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

# Strict 4.0s hard cap across all operations and sockets
MAX_SEARCH_SECONDS = 4.0
PROVIDER_TIMEOUT = 3.2  # maximum time to wait for external parallel providers
DEFAULT_TIMEOUT = 3.0   # seconds per individual external API socket query
socket.setdefaulttimeout(DEFAULT_TIMEOUT)

# Verified Tonaton Session & Security Token
DEFAULT_TONATON_COOKIE = (
    "cf_clearance=8Fhv01Quy1HbheuCHY17bDQxc7LRSD9qJGIi3EZQvmI-1785149340-1.2.1.1-iEuGwv3AhgXEP2z4VYMW2a3u98T4E8oKUv6NVlZ0aJG_WWL_ZdBMd3HMe1drZJswanMro6aPBfuKcrGawjhC41nHNKh0WwHyyf1rGfOGZtY73x5sx.bNUwxcL0WwfbOC1txKUKfK2gGLODtYz.uyYgTiKLGzYxLbVj0TefBrN9G.lOeE2x.sqxJVb3NnxP1NA5wTcjr2kFCCuReaZkq877tiFUvz8RkNxEMynV8HJnV49LTdICtyJgZ.bTN3VquT2MGAzUg.yRoXrONhxbKj9W242gLoIzo92xqb2mDLbKkKugkzg_jwuu1xRkAmZOOf9469W3txllJLR7n1_mBx_P9rBmzXjF9sXZFKTkChJmbx86YgykX4Uu9nuZjjryph6fgTFd5yv8AiYiZLXVFqLpEsW2xFTm7NITYLol2UTiuWoRiPDY23CfKkNE6B24V1QdG8ZDgtuAvTvASq6cakQAwIg8Kl6VW_qIoq8ipJbHo9dn8u6oH32DeRCGeqlveZ5h6Aw0IW_PhhNy5aNCCENxj7653hB.ZXaTz5CCirFVG_vk6Od_niXHdsMBbE4yuLTi96f4mhS9qV4zKl.q8i.A; "
    "aws-waf-token=b54b3114-2f5b-439c-9378-073b1fcf1990:DAoAujxtbMh/DwAA:aLKQFX4STaddV2lu8wUtRThz7Do3p6iDlx5Xybjw5TE1GcBzPnSYsRJbLrfiSHQz/50jd7EG9O0E/pa/OkCYrDY3oNHFEqhAmWVYE/UM/NdMA7Fd4ydvZN2PZoaaxjsQFBcvXTwrnEb+BERNOvKL8CODa9As8uvhEzsBrTv/NVDhQhxGMUccB431rZ8RhwNBb05kCtVCZCRlnNncgdcIf9VKZhykDs7CQOi7w40ir3ryQ+kMlNAxusd1KiUIUEMzojtOTDQz0agEqj5ELdh2O2aT4rxqTvEmNIjsSfQ=; "
    "app=3bebe8e3933646a1b5ea99cca733ab7f; uid=69fc97b484f6cf5489b89fd578576581fc379bb1; rid=tonaton.com;"
)
TONATON_COOKIE = os.environ.get("TONATON_COOKIE", DEFAULT_TONATON_COOKIE)
