import httpx
import os

SEARLO_API_KEY = os.getenv("SEARLO_API_KEY")
SEARLO_URL = "https://api.searlo.com/search"

async def search_web(query: str):
    headers = {
        "X-API-KEY": SEARLO_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "query": query,
        "num": 10
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            SEARLO_URL,
            headers=headers,
            json=payload
        )

        response.raise_for_status()

        data = response.json()

        results = []

        for item in data.get("organic", []):
            results.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet")
            })

        return results
