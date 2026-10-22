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
    q = re.sub(r"\]\s*\(https?://[^\)]+\)", "", q)
    q = re.sub(r"https?://\S+", "", q)
    q = re.sub(r"\(.*?\)", "", q)
    q = re.sub(r"\[.*?\]", "", q)
    q = re.sub(r"(?i)\b\d+\s*(?:gb|ram|rom|tb|storage|inch|cm|display)\b", "", q)
    q = re.sub(r"(?i)\b(black|blue|white|green|grey|red|silver|gold)\b", "", q)
    q = re.sub(r"\s+[-–|]\s+.*", "", q)
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
    try:
        url = f"https://www.amazon.in/s?k={query_encoded}"
        resp = await client.get(url, headers=DESKTOP_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            cards = re.findall(r'data-asin="([A-Z0-9]{10})"(.*?)(?=data-asin=|$)', html, re.DOTALL)
            for asin, inner in cards:
                price_m = re.search(r'class="a-price-whole">([0-9,]+)', inner)
                title_m = re.search(r'<h2[^>]*>.*?<span[^>]*>([^<]+)</span>', inner, re.DOTALL)
                if price_m and title_m:
                    p = price_m.group(1).replace(",", "").rstrip(".")
                    return {
                        "available": True,
                        "title": title_m.group(1).strip(),
                        "price": f"₹{p}",
                        "pdp_url": f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                    }
    except Exception:
        pass

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
            html = resp.text
            matches = re.findall(r'<a[^>]*href="(/[^"]*?/p/[^"]*?)"[^>]*>(.*?)</a>', html, re.DOTALL)
            for href, inner in matches:
                title_m = re.search(r'class="[^"]*(?:KzDlHZ|_4rR01T|wByoh7)[^"]*">([^<]+)</div>', inner)
                price_m = re.search(r'class="[^"]*(?:Nx9bqj|_30jeq3|_16Jk6d)[^"]*">([₹&#8377;0-9, ]+)</div>', inner)
                if title_m and price_m:
                    digits = re.search(r'([0-9,]+)', price_m.group(1))
                    if digits:
                        clean_link = href.split("?")[0]
                        return {
                            "available": True,
                            "title": title_m.group(1).strip(),
                            "price": f"₹{digits.group(1).replace(',', '')}",
                            "pdp_url": f"https://www.flipkart.com{clean_link}"
                        }
    except Exception:
        pass

    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://www.flipkart.com/search?q={query_encoded}"
    }

# ================= 3. BALANCED CATALOG WITH REAL PRODUCT IMAGES =================
@app.get("/home-deals")
async def get_home_deals(page: int = 1):
    CATALOG = [
        # Page 1
        [
            {"title": "Apple iPhone 15 (128 GB) - Black", "price": "₹58,999", "source": "Flipkart", "link": "https://www.flipkart.com/apple-iphone-15-black-128-gb/p/itm6ac6485515ae4", "thumb": "https://m.media-amazon.com/images/I/71d7rfSl0wL._SL1500_.jpg"},
            {"title": "OnePlus Nord CE4 (8GB RAM, 128GB)", "price": "₹24,999", "source": "Amazon", "link": "https://www.amazon.in/dp/B0CX58535Z?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/61amb0CfMGL._SL1500_.jpg"},
            {"title": "Noise ColorFit Pulse 2 Max Smartwatch", "price": "₹1,199", "source": "Flipkart", "link": "https://www.flipkart.com/noise-colorfit-pulse-2-max-1-85-display-bluetooth-calling-smartwatch/p/itme35fc3528b8cf", "thumb": "https://m.media-amazon.com/images/I/61TapeOXotL._SL1500_.jpg"},
            {"title": "boAt Airdopes 141 Bluetooth TWS Earbuds", "price": "₹999", "source": "Amazon", "link": "https://www.amazon.in/dp/B09N3ZNHTY?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/51HBom8xz7L._SL1500_.jpg"},
            {"title": "Puma Smashic Casual Sneakers for Men", "price": "₹1,749", "source": "Flipkart", "link": "https://www.flipkart.com/puma-smashic-sneakers-men/p/itm58f50c0c66a4f", "thumb": "https://m.media-amazon.com/images/I/71Vb3c37WCL._UL1500_.jpg"},
            {"title": "Asian Men's Thar-04 Casual Sneaker Shoes", "price": "₹699", "source": "Amazon", "link": "https://www.amazon.in/dp/B08V8W3W7D?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/61utX8BQRI._UL1500_.jpg"}
        ],
        # Page 2
        [
            {"title": "Realme 12 Pro+ 5G (Submarine Blue)", "price": "₹23,999", "source": "Flipkart", "link": "https://www.flipkart.com/realme-12-pro-plus-5g-submarine-blue-128-gb/p/itmdb2ebcb1e405e", "thumb": "https://m.media-amazon.com/images/I/71yEgDa4MOL._SL1500_.jpg"},
            {"title": "JBL Flip 6 Wireless Bluetooth Speaker", "price": "₹8,999", "source": "Amazon", "link": "https://www.amazon.in/dp/B09G37PNTG?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/61kWB+5RaoL._SL1500_.jpg"},
            {"title": "Nike Revolution 6 Running Shoes", "price": "₹2,695", "source": "Flipkart", "link": "https://www.flipkart.com/nike-revolution-6-next-nature-running-shoes/p/itmb444d31e9c70c", "thumb": "https://m.media-amazon.com/images/I/51Wp8r2N3IL._UL1500_.jpg"},
            {"title": "Campus Men's First Running Shoes", "price": "₹899", "source": "Amazon", "link": "https://www.amazon.in/dp/B07R451W32?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/61o4vB71WjL._UL1500_.jpg"},
            {"title": "Fire-Boltt Ninja Call Pro Plus Smartwatch", "price": "₹1,099", "source": "Flipkart", "link": "https://www.flipkart.com/fire-boltt-ninja-call-pro-plus-1-83-smartwatch/p/itm5b084e3e3b56a", "thumb": "https://m.media-amazon.com/images/I/61S9aVnRZDL._SL1500_.jpg"},
            {"title": "Sony WH-1000XM4 Noise Cancelling Headphones", "price": "₹19,990", "source": "Amazon", "link": "https://www.amazon.in/dp/B0863TXGM3?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/71o8QKljKEAL._SL1500_.jpg"}
        ],
        # Page 3
        [
            {"title": "Samsung Galaxy S23 5G (128GB)", "price": "₹44,999", "source": "Flipkart", "link": "https://www.flipkart.com/samsung-galaxy-s23-5g-phantom-black-128-gb/p/itme8f6f59b66bbd", "thumb": "https://m.media-amazon.com/images/I/61RZdb2m4HL._SL1500_.jpg"},
            {"title": "Redmi Note 13 Pro 5G (8GB, 128GB)", "price": "₹21,999", "source": "Amazon", "link": "https://www.amazon.in/dp/B0CQG3B8HQ?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/71XNeka-BRL._SL1500_.jpg"},
            {"title": "Fastrack Limitless FS1 Pro Smart Watch", "price": "₹1,499", "source": "Flipkart", "link": "https://www.flipkart.com/fastrack-limitless-fs1-pro-smartwatch/p/itm9149021e1a53e", "thumb": "https://m.media-amazon.com/images/I/61JtV6HGzpL._SL1500_.jpg"},
            {"title": "Sparx Men's Running Shoes SM-648", "price": "₹799", "source": "Amazon", "link": "https://www.amazon.in/dp/B082B4654S?tag=youronapp21-21", "thumb": "https://m.media-amazon.com/images/I/71D9ImsvEtL._UL1500_.jpg"}
        ]
    ]

    idx = (page - 1) % len(CATALOG)
    return {"page": page, "deals": CATALOG[idx]}
