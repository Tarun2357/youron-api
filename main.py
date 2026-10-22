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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron API Running"}

def clean_query_text(q: str) -> str:
    # Brand prefix hatayein
    q = re.sub(r'(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)', '', q)
    # Delimiters par cut karein
    q = re.split(r'[|\[(]', q)[0].strip()
    q = re.sub(r'[!?,]', '', q)
    q = re.sub(r'(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b', '', q)
    # Pehle 4-5 words rakhein taaki search accurate ho
    words = q.split()
    if len(words) > 5:
        q = " ".join(words[:5])
    return re.sub(r'\s+', ' ', q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    q_clean = clean_query_text(query)
    q_encoded = urllib.parse.quote_plus(q_clean)

    async with httpx.AsyncClient(headers=HEADERS, timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

async def scrape_amazon(client: httpx.AsyncClient, query_encoded: str):
    url = f"https://www.amazon.in/s?k={query_encoded}"
    try:
        resp = await client.get(url)
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

async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str):
    # Method 1: DuckDuckGo Lite Index (Never Blocks Cloud IPs & Returns Real Flipkart PDP)
    try:
        ddg_search = urllib.parse.quote_plus(f"{clean_q} site:flipkart.com/p/")
        ddg_url = f"https://lite.duckduckgo.com/lite/?q={ddg_search}"
        
        resp = await client.get(ddg_url)
        if resp.status_code == 200:
            html = resp.text
            # Extract redirected links
            matches = re.findall(r'uddg=(https[^&"]+)', html)
            for m in matches:
                decoded = urllib.parse.unquote(m)
                if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                    clean_pdp = decoded.split("?")[0]
                    # Direct Deep-Link Scheme
                    full_pdp = clean_pdp.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")

                    # Search price in html snippet
                    p_match = re.search(r'(?:₹|Rs\.?|&#8377;|INR)\s*([0-9,]+)', html)
                    price_val = f"₹{p_match.group(1).replace(',', '')}" if p_match else ""

                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_val if price_val else "Best Deal",
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Method 2: Yahoo Web Search Index Fallback
    try:
        y_search = urllib.parse.quote_plus(f"{clean_q} site:flipkart.com/p/")
        y_url = f"https://search.yahoo.com/search?p={y_search}"
        resp = await client.get(y_url)
        if resp.status_code == 200:
            text = resp.text
            matches = re.findall(r'RU=([^/&"]+)', text)
            for m in matches:
                decoded = urllib.parse.unquote(m)
                if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                    clean_pdp = decoded.split("?")[0]
                    full_pdp = clean_pdp.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                    p_match = re.search(r'(?:₹|Rs\.?|&#8377;|INR)\s*([0-9,]+)', text)
                    price_val = f"₹{p_match.group(1).replace(',', '')}" if p_match else ""
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_val if price_val else "Best Deal",
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Fallback to direct app search intent
    q_enc = urllib.parse.quote_plus(clean_q)
    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={q_enc}"
    }
