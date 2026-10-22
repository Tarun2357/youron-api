import asyncio
import base64
import re
import time
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

PRICE_CACHE = {}

DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

FLIPKART_CRAWLER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron Ultra-Fast Price Engine"}

def clean_query_text(q: str) -> str:
    # 1. Remove markdown links / brackets
    q = re.sub(r"\]\s*\(https?://[^\)]+\)", "", q)
    q = re.sub(r"https?://\S+", "", q)
    # 2. Remove specifications that break search (RAM, GB, Colors, Delimiters)
    q = re.sub(r"\(.*?\)", "", q)
    q = re.sub(r"\[.*?\]", "", q)
    q = re.sub(r"(?i)\b\d+\s*(?:gb|ram|rom|tb|storage|inch|cm|display)\b", "", q)
    q = re.sub(r"(?i)\b(black|blue|white|green|grey|red|silver|gold)\b", "", q)
    q = re.sub(r"[-–|,].*", "", q)
    q = re.sub(r"(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)", "", q)
    q = re.sub(r"[!?,]", "", q)
    words = q.split()
    if len(words) > 4:
        q = " ".join(words[:4])
    return re.sub(r"\s+", " ", q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    q_clean = clean_query_text(query)
    cache_key = q_clean.lower()
    
    if cache_key in PRICE_CACHE:
        cached_data, timestamp = PRICE_CACHE[cache_key]
        if time.time() - timestamp < 3600:
            return cached_data

    q_encoded = urllib.parse.quote_plus(q_clean)

    # Parallel Fetching (Under 3 seconds)
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        amz_task = scrape_amazon(client, q_clean, q_encoded)
        fk_task = scrape_flipkart(client, q_clean, q_encoded)
        amazon_data, flipkart_data = await asyncio.gather(amz_task, fk_task)

    response_payload = {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

    PRICE_CACHE[cache_key] = (response_payload, time.time())
    return response_payload

# ================= 1. AMAZON SCRAPER =================
async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Method A: Direct Amazon Scraping
    try:
        url = f"https://www.amazon.in/s?k={query_encoded}"
        resp = await client.get(url, headers=DESKTOP_HEADERS)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select('div[data-component-type="s-search-result"], div[data-asin]')
            for card in cards:
                asin = card.get("data-asin", "")
                price_elem = card.select_one(".a-price-whole")
                if asin and len(asin) == 10 and price_elem:
                    p = price_elem.text.strip().replace(",", "").rstrip(".")
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": f"₹{p}",
                        "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                    }
    except Exception:
        pass

    # Method B: Bing Fallback
    try:
        bing_url = f"https://www.bing.com/search?q=site%3Aamazon.in%2Fdp%2F+{query_encoded}"
        resp = await client.get(bing_url, headers=DESKTOP_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            asins = re.findall(r"\b(B0[A-Z0-9]{8})\b", html)
            if asins:
                asin = asins[0]
                p_match = re.search(r'(?:₹|Rs\.?|&#8377;)\s*([0-9,]+)', html)
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

# ================= 2. FLIPKART SCRAPER =================
async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    try:
        fk_url = f"https://www.flipkart.com/search?q={query_encoded}"
        resp = await client.get(fk_url, headers=FLIPKART_CRAWLER_HEADERS)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            pdp_link = None
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/p/itm" in href or ("/p/" in href and "pid=" in href):
                    clean_path = href.split("?")[0]
                    pdp_link = f"https://www.flipkart.com{clean_path}" if clean_path.startswith("/") else clean_path
                    break

            price_str = None
            price_tag = soup.select_one("div.Nx9bqj, div._30jeq3, div._16Jk6d")
            if price_tag:
                clean_digits = re.search(r'([0-9,]+)', price_tag.text)
                if clean_digits:
                    price_str = f"₹{clean_digits.group(1).replace(',', '')}"

            if pdp_link:
                return {
                    "available": True,
                    "title": clean_q,
                    "price": price_str if price_str else "Best Price",
                    "pdp_url": pdp_link
                }
    except Exception:
        pass

    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://www.flipkart.com/search?q={query_encoded}"
    }

# ================= 3. BALANCED HOME DEALS FEED =================
@app.get("/home-deals")
async def get_home_deals(page: int = 1):
    categories = ["smartphones", "laptops", "headphones", "smart watches", "shoes"]
    cat = categories[(page - 1) % len(categories)]
    
    fk_deals = []
    amz_deals = []
    
    async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
        try:
            fk_url = f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(cat)}"
            resp = await client.get(fk_url, headers=FLIPKART_CRAWLER_HEADERS)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/p/itm" in href:
                        title_el = a.select_one(".KzDlHZ, ._4rR01T, .wByoh7")
                        price_el = a.select_one(".Nx9bqj, ._30jeq3")
                        img_el = a.select_one("img")
                        if title_el and price_el:
                            digits = re.search(r'([0-9,]+)', price_el.text)
                            img_src = img_el.get("src", "") if img_el else ""
                            if not img_src or "data:image" in img_src:
                                img_src = "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=400&q=80"
                            fk_deals.append({
                                "title": title_el.text.strip(),
                                "price": f"₹{digits.group(1).replace(',', '')}" if digits else "₹499",
                                "source": "Flipkart",
                                "link": f"https://www.flipkart.com{href.split('?')[0]}",
                                "thumb": img_src
                            })
                            if len(fk_deals) >= 6:
                                break
        except Exception:
            pass

        try:
            amz_url = f"https://www.amazon.in/s?k={urllib.parse.quote_plus(cat)}"
            resp = await client.get(amz_url, headers=DESKTOP_HEADERS)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select('div[data-component-type="s-search-result"], div[data-asin]')
                for card in cards:
                    asin = card.get("data-asin", "")
                    title_elem = card.select_one("h2 a span")
                    price_elem = card.select_one(".a-price-whole")
                    img_elem = card.select_one("img.s-image")
                    if asin and len(asin) == 10 and price_elem:
                        img_src = img_elem.get("src", "") if img_elem else "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400&q=80"
                        amz_deals.append({
                            "title": title_elem.text.strip() if title_elem else cat.title(),
                            "price": f"₹{price_elem.text.strip().replace(',', '')}",
                            "source": "Amazon",
                            "link": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21",
                            "thumb": img_src
                        })
                        if len(amz_deals) >= 6:
                            break
        except Exception:
            pass

    balanced = []
    max_len = max(len(fk_deals), len(amz_deals))
    for i in range(max_len):
        if i < len(fk_deals):
            balanced.append(fk_deals[i])
        if i < len(amz_deals):
            balanced.append(amz_deals[i])

    return {"page": page, "deals": balanced}
