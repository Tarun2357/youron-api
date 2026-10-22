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

BING_HEADERS = {
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
    return {"status": "ok", "service": "Youron API Running"}

def clean_query_text(q: str) -> str:
    q = re.sub(r"\]\s*\(https?://[^\)]+\)", "", q)
    q = re.sub(r"https?://\S+", "", q)
    q = re.sub(r"(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)", "", q)
    q = q.split("|")[0].split("(")[0].split("[")[0].split("]")[0].strip()
    q = re.sub(r"[!?,]", "", q)
    q = re.sub(r"(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b", "", q)
    words = q.split()
    if len(words) > 5:
        q = " ".join(words[:5])
    return re.sub(r"\s+", " ", q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    q_clean = clean_query_text(query)
    q_encoded = urllib.parse.quote_plus(q_clean)

    async with httpx.AsyncClient(headers=BING_HEADERS, timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_clean, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean, q_encoded)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

# ================= 1. AMAZON SCRAPER =================
async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    try:
        url = f"https://www.amazon.in/s?k={query_encoded}"
        resp = await client.get(url)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select('div[data-component-type="s-search-result"], div[data-asin]')
            for item in items:
                asin = item.get("data-asin", "")
                price_elem = item.select_one(".a-price-whole")
                if asin and len(asin) == 10 and price_elem:
                    clean_price = price_elem.text.strip().replace(",", "").rstrip(".")
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": f"₹{clean_price}",
                        "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                    }
    except Exception:
        pass

    try:
        bing_url = f"https://www.bing.com/search?q=site%3Aamazon.in%2Fdp%2F+{query_encoded}"
        resp = await client.get(bing_url)
        if resp.status_code == 200:
            html = resp.text
            asins = re.findall(r"/dp/([A-Z0-9]{10})", html)
            if not asins:
                asins = re.findall(r"\b(B0[A-Z0-9]{8})\b", html)
            if asins:
                asin = asins[0]
                price_match = re.search(r"(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)", html)
                price_str = f"₹{price_match.group(1).replace(',', '').rstrip('.')}" if price_match else "Best Price"
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

# ================= 3. BALANCED 50-50 HOME FEED =================
@app.get("/home-deals")
async def get_home_deals(page: int = 1):
    categories = ["smartphones", "laptops", "wireless headphones", "smart watches", "shoes", "tshirts", "home appliances"]
    cat = categories[(page - 1) % len(categories)]
    
    fk_deals = []
    amz_deals = []
    
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        # Flipkart Scrape
        try:
            fk_url = f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(cat)}"
            resp = await client.get(fk_url, headers=FLIPKART_CRAWLER_HEADERS)
            if resp.status_code == 200:
                html = resp.text
                blocks = re.findall(r'<a[^>]*href="(/[^"]*?/p/[^"]*?)"[^>]*>(.*?)</a>', html, re.DOTALL)
                for href, inner in blocks:
                    title_m = re.search(r'class="[^"]*(?:KzDlHZ|_4rR01T|wByoh7)[^"]*">([^<]+)</div>', inner)
                    if not title_m:
                        title_m = re.search(r'alt="([^"]+)"', inner)
                    price_m = re.search(r'class="[^"]*(?:Nx9bqj|_30jeq3|_16Jk6d)[^"]*">([₹&#8377;0-9, ]+)</div>', inner)
                    img_m = re.search(r'<img[^>]*src="([^"]+)"', inner)
                    if title_m and price_m:
                        digits = re.search(r'([0-9,]+)', price_m.group(1))
                        price_val = f"₹{digits.group(1).replace(',', '')}" if digits else "₹499"
                        fk_deals.append({
                            "title": title_m.group(1).strip(),
                            "price": price_val,
                            "source": "Flipkart",
                            "link": f"https://dl.flipkart.com/dl{href.split('?')[0]}",
                            "thumb": img_m.group(1) if img_m else "https://rukminim2.flixcart.com/image/312/312/xif0q/mobile/default.jpeg"
                        })
                        if len(fk_deals) >= 6:
                            break
        except Exception:
            pass

        # Amazon Scrape
        try:
            amz_url = f"https://www.amazon.in/s?k={urllib.parse.quote_plus(cat)}"
            resp = await client.get(amz_url, headers=BING_HEADERS)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select('div[data-component-type="s-search-result"], div[data-asin]')
                for card in cards:
                    asin = card.get("data-asin", "")
                    title_elem = card.select_one("h2 a span")
                    price_elem = card.select_one(".a-price-whole")
                    img_elem = card.select_one("img.s-image")
                    if asin and len(asin) == 10 and price_elem:
                        amz_deals.append({
                            "title": title_elem.text.strip() if title_elem else cat.title(),
                            "price": f"₹{price_elem.text.strip().replace(',', '')}",
                            "source": "Amazon",
                            "link": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21",
                            "thumb": img_elem.get("src", "") if img_elem else "https://m.media-amazon.com/images/I/default.jpg"
                        })
                        if len(amz_deals) >= 6:
                            break
        except Exception:
            pass

    # 50-50 Balanced Interleave (1 Flipkart, 1 Amazon)
    balanced = []
    max_len = max(len(fk_deals), len(amz_deals))
    for i in range(max_len):
        if i < len(fk_deals):
            balanced.append(fk_deals[i])
        if i < len(amz_deals):
            balanced.append(amz_deals[i])

    return {"page": page, "deals": balanced}
