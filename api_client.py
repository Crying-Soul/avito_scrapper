from __future__ import annotations

import logging
import time
import urllib.parse

from curl_cffi import requests as cffi_requests

import config

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Единственная сессия с TLS-fingerprint Chrome 131 для всего проекта
session = cffi_requests.Session(impersonate="chrome131")
user_agent: str = _USER_AGENT


def _nav_headers() -> dict:
    """Заголовки для навигационного (страничного) запроса."""
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;"
                  "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
                  "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


def _api_headers() -> dict:
    """Заголовки для XHR/API запроса."""
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": "https://www.avito.ru/",
        "Origin": "https://www.avito.ru",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
        "DNT": "1",
    }


def warm_up() -> bool:
    """
    Посещает главную страницу Avito, чтобы получить cookies и
    выглядеть как живой пользователь перед первым API-запросом.
    """
    logger.info("Warming up session (main page)...")
    try:
        resp = session.get(config.BASE_URL, headers=_nav_headers(), timeout=30)
        logger.info("Main page: HTTP %d", resp.status_code)
        return resp.status_code == 200
    except Exception as exc:
        logger.error("Warm-up failed: %s", exc)
        return False


def fetch_all_items() -> list[dict]:
    """Запрашивает список объявлений через API (одна попытка)."""
    params = {
        **config.API_PARAMS,
        "limit": config.LIMIT,
        "offset": config.OFFSET_START,
    }
    url = config.API_URL + "?" + urllib.parse.urlencode(params)
    logger.info("API request: %s", url)

    try:
        resp = session.get(url, headers=_api_headers(), timeout=30)
        logger.info("API response: HTTP %d", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            items: list[dict] = data.get("items") or []
            logger.info("Received %d items", len(items))
            return items
        logger.error("Unexpected API status: %d", resp.status_code)
        return []
    except Exception as exc:
        logger.error("Request error: %s", exc)
        return []


def extract_item_meta(raw: dict) -> dict:
    images = raw.get("images") or []
    first_image: dict = images[0] if images else {}
    thumbnail = (
        first_image.get("864x864")
        or first_image.get("472x472")
        or first_image.get("240x240")
        or ""
    )
    location = raw.get("location") or {}
    price = raw.get("priceDetailed") or {}
    category = raw.get("category") or {}
    url_path: str = raw.get("urlPath", "")
    return {
        "id": raw.get("id"),
        "title": raw.get("title", ""),
        "urlPath": url_path,
        "url": config.BASE_URL + url_path,
        "price_value": price.get("value"),
        "price_string": price.get("string", ""),
        "price_was_lowered": price.get("wasLowered", False),
        "images_count": raw.get("imagesCount", 0),
        "thumbnail": thumbnail,
        "location_id": raw.get("locationId"),
        "location_name": location.get("name", ""),
        "category_id": category.get("id"),
        "category_slug": category.get("slug", ""),
        "params": {},
        "description": "",
    }
