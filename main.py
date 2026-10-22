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

def clean_query(q: str) -> str:
    q = re.sub(r'(?i)^(Amazon Brand\s*-\s*|Flipkart SmartBuy\s*-\s*)', '', q)
    q = q.split('|')[0].split('(')[0].split('[')[0].strip()
    q = re.sub(r'[!?,]', '', q)
    q = re.sub(r'(?i)\b(deal of the day|with led light|non-sticky|glowing skin|enriched with)\b', '', q)
    return re.sub(r'\s+', ' ', q).strip()

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    q_clean = clean_query(query)
    q_encoded = urllib.parse.quote_plus(q_clean)

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean, q_encoded)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

async def scrape_amazon(client: httpx.AsyncClient, query_encoded: str):
    url = f"https://www.amazon.in/s?k={query_encoded}"
    try:
        resp = await client.get(url, headers=HEADERS)
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
    # Method 1: Google Web Cache Gateway (Never Blocked by Flipkart Firewall)
    try:
        gw_url = f"https://html.duckduckgo.com/html/?q={query_encoded}+site:flipkart.com/p/"
        resp = await client.get(gw_url, headers=HEADERS)
        if resp.status_code == 200:
            text = resp.text
            # Extract real decoded Flipkart PDP url
            matches = re.findall(r'uddg=(https[^&"]+)', text)
            for m in matches:
                decoded = urllib.parse.unquote(m)
                if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                    clean_pdp = decoded.split("?")[0]
                    # Format as direct deep link
                    full_pdp = clean_pdp.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")

                    # Extract price from snippet
                    p_match = re.search(r'(?:₹|Rs\.?|&#8377;|INR)\s*([0-9,]+)', text)
                    price_str = f"₹{p_match.group(1).replace(',', '')}" if p_match else "Best Price"

                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_str,
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Method 2: Public JSON Discover Suggestion
    try:
        rome_url = f"https://1.rome.api.flipkart.com/api/4/discover/autosuggest?prefix={query_encoded}&vertical=all"
        resp = await client.get(rome_url, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            suggestions = data.get("RESPONSE", {}).get("suggestions", [])
            for s in suggestions:
                u = s.get("url", "")
                if "/p/" in u or "itm" in u:
                    clean_u = u.split("?")[0]
                    full_pdp = f"https://dl.flipkart.com/dl{clean_u}" if clean_u.startswith("/") else f"https://dl.flipkart.com/dl/{clean_u}"
                    return {
                        "available": True,
                        "title": s.get("title", clean_q),
                        "price": "Check on Flipkart",
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    # Fallback to direct app product search
    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
