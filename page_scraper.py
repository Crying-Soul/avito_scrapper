from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

import api_client
import config

logger = logging.getLogger(__name__)

_RE_PARAMS_UL = re.compile(
    r'<ul\s[^>]*class="params__paramsList___[^"]*"[^>]*>(.+?)</ul>',
    re.DOTALL,
)
_RE_DESC_BLOCK = re.compile(
    r'<div\s[^>]*data-marker="item-view/item-description"[^>]*>(.*?)</div>\s*</div>',
    re.DOTALL,
)
_RE_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _page_nav_headers(referer: str = "https://www.avito.ru/") -> dict:
    return {
        "User-Agent": api_client.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;"
                  "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": referer,
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


def _parse_params(html: str) -> dict[str, str]:
    m = _RE_PARAMS_UL.search(html)
    if not m:
        return {}
    soup = BeautifulSoup(m.group(0), "html.parser")
    ul = soup.find("ul")
    if not ul:
        return {}
    params: dict[str, str] = {}
    for li in ul.find_all("li"):
        key_span = li.find("span")
        if not key_span:
            continue
        sep = key_span.find("span")
        if sep:
            sep.decompose()
        key = key_span.get_text(strip=True).rstrip(":")
        key_span.decompose()
        value = _WHITESPACE.sub(" ", li.get_text(separator=" ", strip=True))
        if key and value:
            params[key] = value
    return params


def _parse_description(html: str) -> str:
    m = _RE_DESC_BLOCK.search(html)
    if not m:
        return ""
    return _WHITESPACE.sub(" ", _RE_TAGS.sub(" ", m.group(1))).strip()


def scrape_listing(url: str) -> dict:
    """
    Загружает HTML страницы объявления через curl_cffi и извлекает
    params и description (одна попытка).
    """
    logger.info("Scraping: %s", url)
    try:
        resp = api_client.session.get(
            url,
            headers=_page_nav_headers(),
            timeout=config.PAGE_LOAD_TIMEOUT,
        )
        if resp.status_code == 200:
            html = resp.text
            params = _parse_params(html)
            description = _parse_description(html)
            if not params:
                logger.warning("No params found on %s", url)
            return {"params": params, "description": description}
        logger.error("Unexpected status %d on %s", resp.status_code, url)
        return {"params": {}, "description": ""}
    except Exception as exc:
        logger.error("Error fetching %s: %s", url, exc)
        return {"params": {}, "description": ""}
