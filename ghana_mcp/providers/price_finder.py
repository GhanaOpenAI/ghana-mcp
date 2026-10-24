"""Classifieds ads product search and price aggregation provider for Ghana.
Queries Tonaton.com's official API to extract live classified ads, calculate
average asking prices, price ranges (min/max), and provide direct listing URLs in Ghana Cedis (GH₵).
"""
import re
import json
import urllib.request
import urllib.parse
import ssl
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup

from ghana_mcp.config import USER_AGENT, DEFAULT_TIMEOUT, TONATON_COOKIE

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
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0",
            "Accept": "application/json",
            "Referer": "https://tonaton.com/",
            "Cookie": TONATON_COOKIE,
        }

    def _fetch_tonaton_api(self, product_query: str, limit: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Fetch live classified ads directly from Tonaton.com's internal API."""
        listings: List[Dict[str, Any]] = []
        url = f"https://tonaton.com/api_web/v1/listing?query={urllib.parse.quote(product_query)}"
        err_msg = None

        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=min(self.timeout, 3.2), context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            adverts = data.get("adverts_list", {}).get("adverts", [])
            for ad in adverts:
                title = ad.get("title") or ""
                price_title = ad.get("price_title") or ""
                digits = re.sub(r"[^\d]", "", price_title)
                try:
                    price_val = float(digits) if digits else 0.0
                except ValueError:
                    price_val = 0.0

                slug = ad.get("slug") or ""
                guid = ad.get("guid") or ""
                link = (
                    f"https://tonaton.com/a-{guid}-{slug}.html"
                    if guid and slug
                    else f"https://tonaton.com/en/ad/{ad.get('id')}"
                )
                loc = ad.get("region_item_text") or ad.get("region_name") or "Ghana"

                if price_val > 0 and title:
                    listings.append({
                        "title": title,
                        "price_ghs": price_val,
                        "source": "Tonaton.com",
                        "location": loc,
                        "url": link,
                    })

                if len(listings) >= limit:
                    break
        except Exception as e:
            err_msg = str(e)

        return listings, err_msg

    def _fetch_jumia_ghana(self, product_query: str, limit: int) -> List[Dict[str, Any]]:
        """Fallback: Fetch live product retail & vendor prices from Jumia Ghana Marketplace."""
        listings: List[Dict[str, Any]] = []
        url = f"https://www.jumia.com.gh/catalog/?q={urllib.parse.quote(product_query)}"

        try:
            html = ""
            if cffi_requests is not None:
                resp = cffi_requests.get(url, impersonate="chrome124", timeout=min(self.timeout, 3.2))
                if resp.status_code == 200:
                    html = resp.text
            else:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=min(self.timeout, 2.5), context=SSL_CTX) as r:
                    html = r.read().decode("utf-8", errors="ignore")

            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            seen_urls = set()

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
                if link in seen_urls:
                    continue

                name_el = a.find(class_=lambda c: c and "name" in c) or a.find("h3") or a.find("h2")
                if not name_el:
                    continue

                name = name_el.get_text(strip=True)
                raw_price = prc.get_text(strip=True)
                digits = re.sub(r"[^\d]", "", raw_price)
                try:
                    price_val = float(digits) if digits else 0.0
                except ValueError:
                    price_val = 0.0

                if price_val > 0:
                    seen_urls.add(link)
                    listings.append({
                        "title": name,
                        "price_ghs": price_val,
                        "source": "Jumia Ghana Marketplace",
                        "location": "Ghana",
                        "url": link,
                    })

                if len(listings) >= limit:
                    break
        except Exception:
            pass

        return listings

    def _fetch_ghana_classifieds(self, product_query: str, limit: int) -> List[Dict[str, Any]]:
        """Fallback: Secondary classifieds ads from Ghana Classifieds."""
        listings: List[Dict[str, Any]] = []
        try:
            url = f"https://www.ghanabusinessweb.com/classifieds?q={urllib.parse.quote(product_query)}"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=min(self.timeout, 2.0), context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=lambda h: h and "/classifieds/" in h and any(c.isdigit() for c in h)):
                title = a.get_text(strip=True)
                href = a["href"]
                if not title or len(title) < 3 or "Post" in title or "category" in href:
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

        # 1. Primary Source: Tonaton.com live classifieds API
        tonaton_items, err_msg = self._fetch_tonaton_api(clean_query, limit=limit)

        all_listings = list(tonaton_items)

        # 2. Secondary Fallback: If Tonaton had 0 items or errored, fetch Jumia & Ghana Classifieds
        if len(all_listings) < limit:
            fallback_items = self._fetch_jumia_ghana(clean_query, limit=limit - len(all_listings))
            all_listings.extend(fallback_items)

        if len(all_listings) < limit:
            classified_items = self._fetch_ghana_classifieds(clean_query, limit=limit - len(all_listings))
            all_listings.extend(classified_items)

        # Deduplicate by URL
        seen_urls = set()
        unique_listings = []
        for it in all_listings:
            u = it.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique_listings.append(it)
            if len(unique_listings) >= limit:
                break

        prices = [it["price_ghs"] for it in unique_listings if it.get("price_ghs")]
        avg_price = round(sum(prices) / len(prices), 2) if prices else None
        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None

        return {
            "query": clean_query,
            "sample_size": len(unique_listings),
            "average_price_ghs": avg_price,
            "min_price_ghs": min_price,
            "max_price_ghs": max_price,
            "currency": "GHS (Ghana Cedi)",
            "primary_source": "Tonaton.com",
            "listings": unique_listings,
        }
