import random
from typing import Any

import aiohttp


async def wikimedia_photo() -> dict[str, str] | None:
    """Return a freely licensed Wikimedia Commons image related to Odesa/Black Sea."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": "Odesa Black Sea Fontanka Ukraine beach",
        "gsrnamespace": "6",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1200",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://commons.wikimedia.org/w/api.php", params=params) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

        pages = list(data.get("query", {}).get("pages", {}).values())
        candidates = []
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            meta = info.get("extmetadata", {})
            title = page.get("title", "Фото дня")
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            if url:
                candidates.append({"url": url, "title": title.replace("File:", "").strip(), "license": license_name})
        return random.choice(candidates) if candidates else None
    except Exception:
        return None
