import re
import urllib.parse
import json
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
}

FLIPKART_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.google.com/",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron API Running"}

def clean_title(title: str) -> str:
    if not title:
        return ""
    q = re.sub(r'(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)', '', title)
    q = re.split(r'[|\[(]', q)[0].strip()
    q = re.sub(r'[!?,]', '', q)
    q = re.sub(r'(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b', '', q)
    return re.sub(r'\s+', ' ', q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    clean_q = clean_title(query)
    clean_encoded = urllib.parse.quote_plus(clean_q)

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
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
    # Strategy 1: Direct Flipkart Search Parsing (HTML + Initial State JSON)
    try:
        fk_url = f"https://www.flipkart.com/search?q={query_encoded}"
        resp = await client.get(fk_url, headers=FLIPKART_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            
            # Check for JSON state embedded in script
            json_matches = re.findall(r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});</script>', html)
            if json_matches:
                try:
                    data = json.loads(json_matches[0])
                    # Parse slots / product page
                    slots = data.get("pageDataV4", {}).get("page", {}).get("data", {}).get("10002", [])
                    for slot in slots:
                        widget = slot.get("widget", {}).get("data", {})
                        products = widget.get("products", [])
                        if products:
                            p = products[0].get("productInfo", {}).get("value", {})
                            title = p.get("titles", {}).get("title", clean_q)
                            price_val = p.get("pricing", {}).get("finalPrice", {}).get("value")
                            base_url = p.get("smartUrl", "") or p.get("baseUrl", "")
                            
                            pdp = f"https://dl.flipkart.com/dl{base_url}" if base_url.startswith("/") else f"https://dl.flipkart.com/dl/{base_url}"
                            return {
                                "available": True,
                                "title": title,
                                "price": f"₹{price_val}" if price_val else "",
                                "pdp_url": pdp
                            }
                except Exception:
                    pass

            # Fallback to direct DOM regex matching
            p_match = re.search(r'₹([0-9,]+)', html)
            url_match = re.search(r'href="(/[^"]+/p/itm[a-zA-Z0-9]+[^"]*)"', html)
            if url_match:
                clean_path = url_match.group(1).split("?")[0]
                price = f"₹{p_match.group(1).replace(',', '')}" if p_match else ""
                return {
                    "available": True,
                    "title": clean_q,
                    "price": price,
                    "pdp_url": f"https://dl.flipkart.com/dl{clean_path}"
                }
    except Exception:
        pass

    # Strategy 2: Web Search Index (Bing Mirror)
    try:
        search_url = f"https://www.bing.com/search?q=site:flipkart.com/p/+{query_encoded}"
        resp = await client.get(search_url, headers=AMAZON_HEADERS)
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
                    "price": price,
                    "pdp_url": full_pdp
                }
    except Exception:
        pass

    # Strategy 3: Guaranteed Direct App Link Fallback
    return {
        "available": True,
        "title": clean_q,
        "price": "",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
