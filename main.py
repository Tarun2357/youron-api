import re
import urllib.parse
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from bs4 import BeautifulSoup

app = FastAPI(title="Youron Price Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AMAZON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "DNT": "1",
}

FLIPKART_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron API Running"}

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    clean_q = urllib.parse.quote_plus(query)

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, clean_q)
        flipkart_data = await scrape_flipkart(client, query, clean_q)

    return {
        "query": query,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

async def scrape_amazon(client: httpx.AsyncClient, query_encoded: str):
    url = f"https://www.amazon.in/s?k={query_encoded}"
    try:
        resp = await client.get(url, headers=AMAZON_HEADERS)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select('div[data-component-type="s-search-result"]')

            for item in items:
                title_tag = item.select_one("h2 a span")
                link_tag = item.select_one("h2 a")
                price_whole = item.select_one(".a-price-whole")

                if title_tag and link_tag:
                    title = title_tag.text.strip()
                    href = link_tag.get("href", "")
                    asin_match = re.search(r"/dp/([A-Z0-9]{10})", href)

                    asin = asin_match.group(1) if asin_match else ""
                    clean_pdp = f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21" if asin else f"https://www.amazon.in{href}"
                    price = f"₹{price_whole.text.strip().replace(',', '')}" if price_whole else ""

                    return {
                        "available": True,
                        "title": title,
                        "price": price,
                        "pdp_url": clean_pdp
                    }
    except Exception:
        pass
    return {"available": False, "price": "", "pdp_url": f"https://www.amazon.in/s?k={query_encoded}&tag=youronapp21-21"}

async def scrape_flipkart(client: httpx.AsyncClient, raw_query: str, query_encoded: str):
    # Method 1: Mobile Web Search
    url = f"https://www.flipkart.com/search?q={query_encoded}"
    try:
        resp = await client.get(url, headers=FLIPKART_HEADERS)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            cards = soup.select("a[href*='/p/']")
            for card in cards:
                href = card.get("href", "")
                if "/p/" not in href:
                    continue

                price_elem = card.select_one("div.Nx9bqj, div._30jeq3, div._16Jk6d")
                if not price_elem:
                    parent = card.parent
                    if parent:
                        price_elem = parent.select_one("div.Nx9bqj, div._30jeq3")

                title_elem = card.select_one("div.KzDlHZ, div._4rR01T, span.B_NuCI, div.wByoh7")

                if price_elem:
                    price_text = price_elem.text.strip()
                    clean_path = href.split("?")[0]
                    full_pdp = f"https://dl.flipkart.com/dl{clean_path}" if clean_path.startswith("/") else f"https://dl.flipkart.com/dl/{clean_path}"

                    return {
                        "available": True,
                        "title": title_elem.text.strip() if title_elem else raw_query,
                        "price": price_text,
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Method 2: Public Auto-Suggest Endpoint
    try:
        suggest_url = f"https://1.rome.api.flipkart.com/api/4/discover/autosuggest?prefix={query_encoded}&vertical=all"
        resp = await client.get(suggest_url, headers=FLIPKART_HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            suggestions = data.get("RESPONSE", {}).get("suggestions", [])
            for s in suggestions:
                url_path = s.get("url", "")
                if "/p/" in url_path:
                    clean_path = url_path.split("?")[0]
                    full_pdp = f"https://dl.flipkart.com/dl{clean_path}" if clean_path.startswith("/") else f"https://dl.flipkart.com/dl/{clean_path}"
                    return {
                        "available": True,
                        "title": s.get("title", raw_query),
                        "price": "Check on Flipkart",
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Fallback to direct app search intent
    return {
        "available": True,
        "title": raw_query,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
