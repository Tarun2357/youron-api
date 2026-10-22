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

    async with httpx.AsyncClient(headers=SEARCH_HEADERS, timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_clean, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean, q_encoded)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

# ================= 1. AMAZON (EXACT 80904 PROVEN CODE) =================
async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    try:
        bing_url = f"https://www.bing.com/search?q=site%3Aamazon.in%2Fdp%2F+{query_encoded}"
        resp = await client.get(bing_url)
        if resp.status_code == 200:
            html = resp.text
            links = re.findall(r'href="(https://www\.amazon\.in/[^"]*?/dp/([A-Z0-9]{10})[^"]*?)"', html)
            if not links:
                links = re.findall(r'(https://www\.amazon\.in/[^"\'\s<>]+?/dp/([A-Z0-9]{10}))', html)

            if links:
                full_match, asin = links[0]
                clean_pdp = f"https://www.amazon.in/dp/{asin}?tag=youronapp21-21"
                price_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                price_str = f"₹{price_match.group(1).replace(',', '')}" if price_match else "Best Price"

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

# ================= 2. FLIPKART (MULTI-INDEX WITH FIXED REGEX) =================
async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Method A: Bing Search with clean base64 extractor
    try:
        bing_url = f"https://www.bing.com/search?q=site%3Aflipkart.com+{query_encoded}"
        resp = await client.get(bing_url)
        if resp.status_code == 200:
            html = resp.text

            # 1. Decode all Bing redirect links (handles &amp;u=a1 and &u=a1)
            b64_matches = re.findall(r'u=a1([A-Za-z0-9_-]+)', html)
            for m in b64_matches:
                try:
                    padded = m + '=' * (-len(m) % 4)
                    decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
                    if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                        clean_url = decoded.split("?")[0]
                        pdp_url = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                        price_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                        price_str = f"₹{price_match.group(1).replace(',', '')}" if price_match else "Best Price"
                        return {
                            "available": True,
                            "title": clean_q,
                            "price": price_str,
                            "pdp_url": pdp_url
                        }
                except Exception:
                    pass

            # 2. Check plain flipkart product links in html
            direct_matches = re.findall(r'(https://[a-zA-Z0-9.-]*flipkart\.com/[^"\'\s<>&]+/p/[^"\'\s<>&]+)', html)
            if direct_matches:
                clean_url = direct_matches[0].split("?")[0]
                pdp_url = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                price_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                price_str = f"₹{price_match.group(1).replace(',', '')}" if price_match else "Best Price"
                return {
                    "available": True,
                    "title": clean_q,
                    "price": price_str,
                    "pdp_url": pdp_url
                }
    except Exception:
        pass

    # Method B: DuckDuckGo Lite Search
    try:
        ddg_url = f"https://lite.duckduckgo.com/lite/?q=site%3Aflipkart.com+{query_encoded}"
        resp = await client.get(ddg_url)
        if resp.status_code == 200:
            html = resp.text
            matches = re.findall(r'uddg=(https[^&"]+)', html)
            for m in matches:
                decoded = urllib.parse.unquote(m)
                if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                    clean_url = decoded.split("&")[0].split("?")[0]
                    pdp_url = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                    price_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                    price_str = f"₹{price_match.group(1).replace(',', '')}" if price_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_str,
                        "pdp_url": pdp_url
                    }
    except Exception:
        pass

    # Method C: Yahoo Search Engine
    try:
        yahoo_url = f"https://search.yahoo.com/search?p=flipkart+{query_encoded}"
        resp = await client.get(yahoo_url)
        if resp.status_code == 200:
            html = resp.text
            ru_matches = re.findall(r'RU=(https%3a%2f%2fwww\.flipkart\.com%2f[^/&"]+)', html, re.IGNORECASE)
            for ru in ru_matches:
                decoded = urllib.parse.unquote(ru)
                if "/p/" in decoded or "itm" in decoded:
                    clean_url = decoded.split("?")[0]
                    pdp_url = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                    price_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                    price_str = f"₹{price_match.group(1).replace(',', '')}" if price_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
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
