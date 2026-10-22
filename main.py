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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
}

@app.get("/")
def home():
    return {"status": "ok", "service": "Youron API Running"}

@app.get("/compare")
async def compare_prices(query: str = Query(..., min_length=2)):
    clean_q = urllib.parse.quote_plus(query)
    
    async with httpx.AsyncClient(headers=HEADERS, timeout=10.0, follow_redirects=True) as client:
        amazon_data = await scrape_amazon(client, clean_q)
        flipkart_data = await scrape_flipkart(client, clean_q)

    return {
        "query": query,
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

async def scrape_flipkart(client: httpx.AsyncClient, query_encoded: str):
    url = f"https://www.flipkart.com/search?q={query_encoded}"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            product = soup.select_one("div._75nlfW, div._1sdMkc, div[data-id]")
            if product:
                link_tag = product.select_one("a[href*='/p/']")
                title_tag = product.select_one("div.KzDlHZ, a.wByoh7, div._4rR01T")
                price_tag = product.select_one("div.Nx9bqj, div._30jeq3")

                if link_tag and price_tag:
                    rel_url = link_tag.get("href", "")
                    clean_path = rel_url.split("?")[0]
                    full_pdp = f"https://dl.flipkart.com/dl{clean_path}" if clean_path.startswith("/") else f"https://dl.flipkart.com/dl/{clean_path}"
                    
                    return {
                        "available": True,
                        "title": title_tag.text.strip() if title_tag else "",
                        "price": price_tag.text.strip(),
                        "pdp_url": full_pdp
                    }
    except Exception:
        pass
    return {"available": False, "price": "", "pdp_url": f"https://dl.flipkart.com/dl/search?q={query_encoded}"}
