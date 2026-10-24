"""Classifieds ads product search and price aggregation provider for Ghana.
Integrates live Ghanaian marketplaces (Jumia Ghana, Ghana Classifieds) and attempts
classifieds networks (Tonaton) to extract real-time market asking prices in Ghana Cedis (GH₵).
"""
import re
import json
import urllib.request
import urllib.parse
import ssl
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup

from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

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

    def _fetch_jumia_ghana(self, product_query: str, limit: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Fetch live product retail & vendor prices from Jumia Ghana Marketplace."""
        listings: List[Dict[str, Any]] = []
        url = f"https://www.jumia.com.gh/catalog/?q={urllib.parse.quote(product_query)}"
        err_msg = None

        try:
            html = ""
            if cffi_requests is not None:
                resp = cffi_requests.get(url, impersonate="chrome124", timeout=min(self.timeout, 3.8))
                if resp.status_code == 200:
                    html = resp.text
                else:
                    err_msg = f"cffi HTTP {resp.status_code}"
            else:
                err_msg = "cffi_requests is None (not installed)"
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CTX) as r:
                    html = r.read().decode("utf-8", errors="ignore")

            if not html:
                return listings, err_msg

            soup = BeautifulSoup(html, "html.parser")
            seen_jumia_urls = set()

            for prc in soup.find_all("div", class_=lambda c: c and "prc" in c):
                a = prc.find_parent("a", href=True)
                if not a:
                    continue

                item_href = a.get("href", "")
                link = (
                    f"https://www.jumia.com.gh{item_href}"
                    if item_href.startswith("/")
                    else item_href
                )
                if link in seen_jumia_urls:
                    continue

                name_el = a.find(class_=lambda c: c and "name" in c) or a.find("h3") or a.find("h2")
                if not name_el:
                    continue

                name = name_el.get_text(strip=True)
                name_lower = name.lower()

                # Filter out accessories (e.g. cables, cases) if they don't match core query term
                query_words = [w for w in product_query.lower().split() if len(w) > 2]
                if query_words and query_words[0] not in name_lower:
                    continue

                seen_jumia_urls.add(link)
                raw_price = prc.get_text(strip=True)

                # Extract digits and clean Ghana Cedi value
                digits = re.sub(r"[^\d]", "", raw_price)
                try:
                    price_val = float(digits) if digits else 0.0
                except ValueError:
                    price_val = 0.0

                if price_val > 0:
                    listings.append({
                        "title": name,
                        "price_ghs": price_val,
                        "source": "Jumia Ghana Marketplace",
                        "location": "Ghana",
                        "url": link,
                    })

                if len(listings) >= limit:
                    break
        except Exception as e:
            err_msg = str(e)

        return listings, err_msg

    def _fetch_tonaton_or_classifieds(self, product_query: str, limit: int) -> List[Dict[str, Any]]:
        """Attempt Tonaton classifieds or Ghana Classifieds directory."""
        listings: List[Dict[str, Any]] = []

        # 1. Attempt Tonaton via browser impersonation
        if cffi_requests is not None:
            try:
                tonaton_url = f"https://tonaton.com/en/ads/ghana?query={urllib.parse.quote(product_query)}"
                r = cffi_requests.get(tonaton_url, impersonate="chrome124", timeout=2.0)
                if r.status_code == 200 and "Human Verification" not in r.text:
                    soup = BeautifulSoup(r.text, "html.parser")
                    for a in soup.find_all("a", href=lambda h: h and "/en/ad/" in h):
                        title = a.get_text(strip=True)
                        if title and len(title) > 3:
                            price_m = re.search(r"GH[₵¢S]?\s*([\d,]+)", a.get_text())
                            if price_m:
                                price_val = float(price_m.group(1).replace(",", ""))
                                link = (
                                    f"https://tonaton.com{a['href']}"
                                    if a["href"].startswith("/")
                                    else a["href"]
                                )
                                listings.append({
                                    "title": title,
                                    "price_ghs": price_val,
                                    "source": "Tonaton Ghana Classifieds",
                                    "location": "Ghana",
                                    "url": link,
                                })
            except Exception:
                pass

        # 2. Fetch from Ghana Classifieds
        try:
            url = f"https://www.ghanabusinessweb.com/classifieds?q={urllib.parse.quote(product_query)}"
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=min(self.timeout, 2.5), context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            soup = BeautifulSoup(html, "html.parser")

            # JSON-LD product offers
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
                                "source": "Ghana Classifieds",
                                "location": "Ghana",
                                "url": item_url,
                            })
                except Exception:
                    pass

            # HTML cards
            for a in soup.find_all("a", href=lambda h: h and "/classifieds/" in h and any(c.isdigit() for c in h)):
                title = a.get_text(strip=True)
                href = a["href"]
                if not title or len(title) < 3 or "Post" in title or "category" in href:
                    continue
                if any(it["url"] == href for it in listings):
                    continue

                parent = a.find_parent("div")
                card_text = parent.get_text(" | ", strip=True) if parent else ""

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
                            "source": "Ghana Classifieds",
                            "location": loc,
                            "url": href,
                        })

                if len(listings) >= limit:
                    break
        except Exception:
            pass

        return listings

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

        # 1. Primary: Live market retail and vendor prices (Jumia Ghana)
        jumia_items, err_msg = self._fetch_jumia_ghana(clean_query, limit=limit)

        # 2. Secondary: Classifieds ads (Tonaton / Ghana Classifieds)
        classified_items = self._fetch_tonaton_or_classifieds(clean_query, limit=limit)

        # Combine and deduplicate by URL
        seen_urls = set()
        all_listings: List[Dict[str, Any]] = []

        for it in jumia_items + classified_items:
            u = it.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                all_listings.append(it)
            if len(all_listings) >= limit:
                break

        prices = [it["price_ghs"] for it in all_listings if it.get("price_ghs")]
        avg_price = round(sum(prices) / len(prices), 2) if prices else None
        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None

        return {
            "query": clean_query,
            "sample_size": len(all_listings),
            "average_price_ghs": avg_price,
            "min_price_ghs": min_price,
            "max_price_ghs": max_price,
            "currency": "GHS (Ghana Cedi)",
            "debug_info": {"cffi_available": cffi_requests is not None, "jumia_err": err_msg},
            "listings": all_listings,
        }
