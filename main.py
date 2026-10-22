import base64
import re
import urllib.parse
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="Youron Price Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_clean, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean, q_encoded)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

# ================= 1. AMAZON SCRAPER (WITH BASE64 DECODER) =================
async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    try:
        bing_url = f"https://www.bing.com/search?q=amazon+in+dp+{query_encoded}"
        resp = await client.get(bing_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            html = resp.text

            # 1. Base64 decoded u=a1... (Decodes Bing protected links)
            for m in re.findall(r"u=a1([A-Za-z0-9_-]+)", html):
                try:
                    padded = m + "=" * (-len(m) % 4)
                    decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
                    asin_match = re.search(r"/dp/([A-Z0-9]{10})", decoded)
                    if asin_match:
                        asin = asin_match.group(1)
                        clean_pdp = f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                        p_match = re.search(r"(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)", html)
                        price_str = f"₹{p_match.group(1).replace(',', '')}" if p_match else "Best Price"
                        return {
                            "available": True,
                            "title": clean_q,
                            "price": price_str,
                            "pdp_url": clean_pdp
                        }
                except Exception:
                    pass

            # 2. Direct ASIN in cite or plain text
            asins = re.findall(r"/dp/([A-Z0-9]{10})", html)
            if asins:
                asin = asins[0]
                clean_pdp = f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                p_match = re.search(r"(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)", html)
                price_str = f"₹{p_match.group(1).replace(',', '')}" if p_match else "Best Price"
                return {
                    "available": True,
                    "title": clean_q,
                    "price": price_str,
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

# ================= 2. FLIPKART SCRAPER (PROVEN WORKING IN 80922) =================
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
                price_str = f"₹{clean_digits.group(1).replace(',', '')}" if clean_digits else "Best Price"
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
