import base64
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

SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron API Running"}

def clean_query_text(q: str) -> str:
    q = re.sub(r'(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)', '', q)
    q = q.split('|')[0].split('(')[0].split('[')[0].strip()
    q = re.sub(r'[!?,]', '', q)
    q = re.sub(r'(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b', '', q)
    words = q.split()
    if len(words) > 5:
        q = " ".join(words[:5])
    return re.sub(r'\s+', ' ', q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    q_clean = clean_query_text(query)
    q_encoded = urllib.parse.quote_plus(q_clean)

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_clean, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean, q_encoded)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

# ================= 1. AMAZON (PROVEN WORKING DIRECT SCRAPER) =================
async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
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

                    if asin and price:
                        return {
                            "available": True,
                            "title": title if title else clean_q,
                            "price": price,
                            "pdp_url": clean_pdp
                        }
    except Exception:
        pass

    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Amazon",
        "pdp_url": f"https://www.amazon.in/s?k={query_encoded}&tag=youronapp21-21"
    }

# ================= 2. FLIPKART (MULTI-SOURCE INDEX ENGINE) =================
async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Strategy A: Yahoo Search (Never blocks cloud IPs & shows real PDP)
    try:
        y_url = f"https://search.yahoo.com/search?p=flipkart+{query_encoded}"
        resp = await client.get(y_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            # Decode redirect URL RU=https%3a%2f%2fwww.flipkart.com...
            ru_match = re.search(r'RU=(https%3a%2f%2fwww\.flipkart\.com%2f[^/&"]+)', html, re.IGNORECASE)
            if ru_match:
                decoded_url = urllib.parse.unquote(ru_match.group(1))
                if "/p/" in decoded_url or "itm" in decoded_url:
                    clean_url = decoded_url.split("?")[0]
                    pdp = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                    p_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                    price = f"₹{p_match.group(1).replace(',', '')}" if p_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price,
                        "pdp_url": pdp
                    }
    except Exception:
        pass

    # Strategy B: Bing Search (Plain keywords + Base64 Decoder)
    try:
        bing_url = f"https://www.bing.com/search?q=flipkart+{query_encoded}"
        resp = await client.get(bing_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            b64_matches = re.findall(r'u=a1([A-Za-z0-9_-]+)', html)
            for m in b64_matches:
                try:
                    padded = m + '=' * (-len(m) % 4)
                    decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
                    if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                        clean_url = decoded.split("?")[0]
                        pdp_url = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                        p_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                        price_str = f"₹{p_match.group(1).replace(',', '')}" if p_match else "Best Price"
                        return {
                            "available": True,
                            "title": clean_q,
                            "price": price_str,
                            "pdp_url": pdp_url
                        }
                except Exception:
                    pass
    except Exception:
        pass

    # Strategy C: DuckDuckGo POST Search Engine
    try:
        ddg_resp = await client.post("https://html.duckduckgo.com/html/", data={"q": f"flipkart {clean_q}"})
        if ddg_resp.status_code == 200:
            html = ddg_resp.text
            matches = re.findall(r'uddg=(https[^&"]+)', html)
            for m in matches:
                decoded = urllib.parse.unquote(m)
                if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                    clean_url = decoded.split("&")[0].split("?")[0]
                    pdp_url = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                    p_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                    price_str = f"₹{p_match.group(1).replace(',', '')}" if p_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_str,
                        "pdp_url": pdp_url
                    }
    except Exception:
        pass

    # Fallback to direct app search intent
    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
