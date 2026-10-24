"""Classifieds ads product search and price aggregation provider for Ghana."""
import re
import json
import urllib.request
import urllib.parse
import ssl
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


class PriceFinderProvider:
    name = "ghana_price_finder"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def search_prices(self, product_query: str, limit: int = 15) -> Dict[str, Any]:
        """Search active classifieds listings in Ghana and calculate price metrics."""
        clean_query = product_query.strip()
        if not clean_query:
            return {
                "query": "",
                "sample_size": 0,
                "average_price_ghs": None,
                "min_price_ghs": None,
                "max_price_ghs": None,
                "currency": "GHS (Ghana Cedi)",
                "listings": [],
            }

        url = f"https://www.ghanabusinessweb.com/classifieds?q={urllib.parse.quote(clean_query)}"
        req = urllib.request.Request(url, headers=self.headers)
        listings: List[Dict[str, Any]] = []

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            soup = BeautifulSoup(html, "html.parser")

            # 1. Parse JSON-LD structured product offerings
            for script_tag in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script_tag.string)
                    if data.get("@type") == "Product" and "offers" in data:
                        name = data.get("name")
                        p_val = float(data["offers"].get("price", 0))
                        item_url = data["offers"].get("url")
                        if p_val > 0 and item_url:
                            listings.append({
                                "title": name,
                                "price_ghs": p_val,
                                "location": "Ghana",
                                "url": item_url,
                            })
                except Exception:
                    pass

            # 2. Parse HTML classifieds ad cards
            for a in soup.find_all("a", href=lambda h: h and "/classifieds/" in h and any(c.isdigit() for c in h)):
                title = a.get_text(strip=True)
                href = a["href"]
                if not title or len(title) < 3 or "Post" in title or "category" in href:
                    continue
                if any(it["url"] == href for it in listings):
                    continue

                parent = a.find_parent("div")
                card_text = parent.get_text(" | ", strip=True) if parent else ""

                # Extract price in GHS (e.g. GH₵8,500, GH¢ 2400)
                price_match = re.search(r"GH[₵¢S]?\s*([\d,]+)", card_text)
                if price_match:
                    num_str = price_match.group(1).replace(",", "")
                    try:
                        price_val = float(num_str)
                    except ValueError:
                        price_val = 0.0

                    if price_val > 0:
                        loc_match = re.search(r"\|\s*([A-Za-z\s]+)\s*·\s*\d+", card_text)
                        loc = loc_match.group(1).strip() if loc_match else "Ghana"
                        listings.append({
                            "title": title,
                            "price_ghs": price_val,
                            "location": loc,
                            "url": href,
                        })

                if len(listings) >= limit:
                    break
        except Exception:
            pass

        prices = [it["price_ghs"] for it in listings if it.get("price_ghs")]
        avg_price = round(sum(prices) / len(prices), 2) if prices else None
        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None

        return {
            "query": clean_query,
            "sample_size": len(listings),
            "average_price_ghs": avg_price,
            "min_price_ghs": min_price,
            "max_price_ghs": max_price,
            "currency": "GHS (Ghana Cedi)",
            "listings": listings[:limit],
        }
