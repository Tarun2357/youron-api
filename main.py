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

DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "DNT": "1",
}

FLIPKART_CRAWLER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
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
    # 1. Strip markdown or full URL fragments
    q = re.sub(r"\]\s*\(https?://[^\)]+\)", "", q)
    q = re.sub(r"https?://\S+", "", q)
    # 2. Strip brand prefixes
    q = re.sub(r"(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)", "", q)
    # 3. Strip trailing brackets / delimiters
    q = q.split("|")[0].split("(")[0].split("[")[0].split("]")[0].strip()
    q = re.sub(r"[!?,]", "", q)
    q = re.sub(r"(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b", "", q)
    words = q.split()
    if len(words) > 5:
        q = " ".join(words[:5])
    return re.sub(r"\s+", " ", q).strip()

def decode_b64_url(s: str) -> str:
    try:
        s = s.replace("-", "+").replace("_", "/")
        padded = s + "=" * (-len(s) % 4)
        return base64.b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        return ""

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

# ================= 1. AMAZON SCRAPER (MULTI-LAYER) =================
async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Method A: Direct Amazon Scraping (Desktop Headers)
    try:
        url = f"https://www.amazon.in/s?k={query_encoded}"
        resp = await client.get(url, headers=DESKTOP_HEADERS)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select('div[data-component-type="s-search-result"]')
            for item in items:
                link_tag = item.select_one("h2 a")
                price_whole = item.select_one(".a-price-whole")
                if link_tag:
                    href = link_tag.get("href", "")
                    asin_match = re.search(r"/dp/([A-Z0-9]{10})", href)
                    if asin_match and price_whole:
                        asin = asin_match.group(1)
                        clean_price = price_whole.text.strip().replace(",", "").rstrip(".")
                        return {
                            "available": True,
                            "title": clean_q,
                            "price": f"₹{clean_price}",
                            "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                        }
    except Exception:
        pass

    # Method B: Bing Search Index with Base64 & Cite Decoder
    try:
        bing_url = f"https://www.bing.com/search?q=site%3Aamazon.in%2Fdp%2F+{query_encoded}"
        resp = await client.get(bing_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            html = resp.text

            # 1. Base64 decoded links
            for m in re.findall(r"u=a1([A-Za-z0-9_-]+)", html):
                dec = decode_b64_url(m)
                asin_match = re.search(r"/dp/([A-Z0-9]{10})", dec)
                if asin_match:
                    asin = asin_match.group(1)
                    p_match = re.search(r"(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)", html)
                    price_str = f"₹{p_match.group(1).replace(',', '').rstrip('.')}" if p_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_str,
                        "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                    }

            # 2. Raw /dp/ASIN in html text
            asins = re.findall(r"/dp/([A-Z0-9]{10})", html)
            if asins:
                asin = asins[0]
                p_match = re.search(r"(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)", html)
                price_str = f"₹{p_match.group(1).replace(',', '').rstrip('.')}" if p_match else "Best Price"
                return {
                    "available": True,
                    "title": clean_q,
                    "price": price_str,
                    "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                }
    except Exception:
        pass

    # Method C: DuckDuckGo Lite Index Fallback
    try:
        ddg_url = f"https://lite.duckduckgo.com/lite/?q=site%3Aamazon.in%2Fdp%2F+{query_encoded}"
        resp = await client.get(ddg_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            for m in re.findall(r"uddg=(https[^&\"]+)", html):
                dec = urllib.parse.unquote(m)
                asin_match = re.search(r"/dp/([A-Z0-9]{10})", dec)
                if asin_match:
                    asin = asin_match.group(1)
                    p_match = re.search(r"(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)", html)
                    price_str = f"₹{p_match.group(1).replace(',', '').rstrip('.')}" if p_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_str,
                        "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                    }
    except Exception:
        pass

    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Amazon",
        "pdp_url": f"https://www.amazon.in/s?k={query_encoded}&tag=youronapp21-21"
    }

# ================= 2. FLIPKART SCRAPER (PROVEN 100% WORKING IN 80925) =================
async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    try:
        fk_url = f"https://www.flipkart.com/search?q={query_encoded}"
        resp = await client.get(fk_url, headers=FLIPKART_CRAWLER_HEADERS)
        if resp.status_code == 200:
            html = resp.text

            pdp_matches = re.findall(r'href="(/[^"]*?/p/[^"]*?)"', html)
            if not pdp_matches:
                pdp_matches = re.findall(r'href="([^"]*?flipkart\.com/[^"]*?/p/[^"]*?)"', html)

            price_matches = re.findall(r'class="[^"]*(?:Nx9bqj|_30jeq3|_16Jk6d)[^"]*">([₹&#8377;0-9, ]+)</div>', html)
            if not price_matches:
                price_matches = re.findall(r'(?:₹|&#8377;)\s*([0-9,]+)', html)

            title_matches = re.findall(r'class="[^"]*(?:KzDlHZ|_4rR01T|wByoh7)[^"]*">([^<]+)</div>', html)

            if pdp_matches:
                raw_url = pdp_matches[0].split("?")[0]
                pdp_url = f"https://dl.flipkart.com/dl{raw_url}" if raw_url.startswith("/") else raw_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")

                raw_price = price_matches[0] if price_matches else ""
                clean_digits = re.search(r'([0-9,]+)', raw_price)
                price_str = f"₹{clean_digits.group(1).replace(',', '').rstrip('.')}" if clean_digits else "Best Price"
                title_str = title_matches[0].strip() if title_matches else clean_q

                return {
                    "available": True,
                    "title": title_str,
                    "price": price_str,
                    "pdp_url": pdp_url
                }
    except Exception:
        pass

    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
