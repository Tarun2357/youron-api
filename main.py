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

    async with httpx.AsyncClient(headers=BING_HEADERS, timeout=12.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, q_clean, q_encoded)
        flipkart_data = await scrape_flipkart(client, q_clean, q_encoded)

    return {
        "query": query,
        "clean_query": q_clean,
        "amazon": amazon_data,
        "flipkart": flipkart_data
    }

async def scrape_amazon(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Method 1: Bing Index for Amazon PDP & Price (Bypasses Datacenter Captcha)
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
                
                # Extract price from snippet
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

    # Method 2: Direct Amazon search
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
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": f"₹{price_elem.text.strip().replace(',', '')}",
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

async def scrape_flipkart(client: httpx.AsyncClient, clean_q: str, query_encoded: str):
    # Method 1: Bing Index for Flipkart PDP & Price (100% No Datacenter Block)
    try:
        bing_url = f"https://www.bing.com/search?q=site%3Aflipkart.com%2Fp%2F+{query_encoded}"
        resp = await client.get(bing_url)
        if resp.status_code == 200:
            html = resp.text
            links = re.findall(r'href="(https://www\.flipkart\.com/[^"]*?/p/[^"]*?)"', html)
            if not links:
                links = re.findall(r'(https://www\.flipkart\.com/[^"\'\s<>]+?/p/[^"\'\s<>]+)', html)
            
            if links:
                target = links[0].split("&")[0].split("?")[0]
                pdp_url = target.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                
                # Extract price from snippet
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

    # Method 2: DuckDuckGo POST Search Engine Fallback
    try:
        ddg_resp = await client.post("https://html.duckduckgo.com/html/", data={"q": f"{clean_q} site:flipkart.com/p/"})
        if ddg_resp.status_code == 200:
            html = ddg_resp.text
            matches = re.findall(r'uddg=(https[^&"]+)', html)
            for m in matches:
                decoded = urllib.parse.unquote(m)
                if "flipkart.com" in decoded and ("/p/" in decoded or "itm" in decoded):
                    clean_pdp = decoded.split("&")[0].split("?")[0]
                    full_pdp = clean_pdp.replace("https://www.flipkart.com/", "https://dl.flipkart.com/dl/")
                    price_match = re.search(r'(?:₹|Rs\.?|INR|&#8377;)\s*([0-9,]+)', html)
                    price_str = f"₹{price_match.group(1).replace(',', '')}" if price_match else "Best Price"
                    return {
                        "available": True,
                        "title": clean_q,
                        "price": price_str,
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass

    return {
        "available": True,
        "title": clean_q,
        "price": "Check on Flipkart",
        "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"
    }
