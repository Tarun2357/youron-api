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
    "Accept-Language": "en-IN,en;q=0.9",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron API Running"}

def clean_title_for_search(q: str) -> str:
    # Amazon Brand ya Flipkart SmartBuy prefix hatayein
    q = re.sub(r'(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)', '', q)
    # Delimiters par cut karein
    q = re.split(r'[|\[(]', q)[0].strip()
    q = re.sub(r'[!?,]', '', q)
    q = re.sub(r'(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b', '', q)
    return re.sub(r'\s+', ' ', q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    clean_q = clean_title_for_search(query)
    clean_encoded = urllib.parse.quote_plus(clean_q)

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, clean_encoded)
        flipkart_data = await scrape_flipkart(client, clean_q, clean_encoded)

    return {
        "query": query,
        "clean_query": clean_q,
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

async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Method 1: Bing Search Engine Index (Never Blocks Datacenters)
    try:
        bing_url = f"https://www.bing.com/search?q=site:flipkart.com/p/+{query_encoded}"
        resp = await client.get(bing_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            text = resp.text
            matches = re.findall(r'href="(https://www\.flipkart\.com/[^"]+/p/[^"]+)"', text)
            if matches:
                clean_url = matches[0].split("&")[0].split("?")[0]
                full_pdp = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")

                p_match = re.search(r'(?:₹|Rs\.?|&#8377;|INR)\s*([0-9,]+)', text)
                price = f"₹{p_match.group(1).replace(',', '')}" if p_match else ""

                return {
                    "available": True,
                    "title": clean_q,
                    "price": price if price else "Best Deal",
                    "pdp_url": full_pdp
                }
    except Exception:
        pass

    # Method 2: DuckDuckGo HTML Search Index
    try:
        ddg_url = f"https://html.duckduckgo.com/html/?q=site:flipkart.com/p/+{query_encoded}"
        resp = await client.get(ddg_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            text = resp.text
            matches = re.findall(r'uddg=(https[^&"]+)', text)
            for m in matches:
                decoded_url = urllib.parse.unquote(m)
                if "flipkart.com" in decoded_url and ("/p/" in decoded_url or "itm" in decoded_url):
                    clean_url = decoded_url.split("&")[0].split("?")[0]
                    full_pdp = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")

                    p_match = re.search(r'(?:₹|Rs\.?|&#8377;|INR)\s*([0-9,]+)', text)
                    price = f"₹{p_match.group(1).replace(',', '')}" if p_match else ""

                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price if price else "Best Deal",
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Method 3: Yahoo Search Index
    try:
        yahoo_url = f"https://search.yahoo.com/search?p=site:flipkart.com/p/+{query_encoded}"
        resp = await client.get(yahoo_url, headers=SEARCH_HEADERS)
        if resp.status_code == 200:
            text = resp.text
            matches = re.findall(r'RU=([^/&"]+)', text)
            for m in matches:
                decoded_url = urllib.parse.unquote(m)
                if "flipkart.com" in decoded_url and ("/p/" in decoded_url or "itm" in decoded_url):
                    clean_url = decoded_url.split("&")[0].split("?")[0]
                    full_pdp = clean_url.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")

                    p_match = re.search(r'(?:₹|Rs\.?|&#8377;|INR)\s*([0-9,]+)', text)
                    price = f"₹{p_match.group(1).replace(',', '')}" if p_match else ""

                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price if price else "Best Deal",
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Direct Deep-Link Search Fallback
    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
