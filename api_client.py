"""
Avito API client — аккуратный парсинг с имитацией человека.

Анти-бан стратегия:
  - curl_cffi impersonation (Chrome TLS fingerprint)
  - Заголовки строго соответствуют активному профилю сессии
  - Адаптивный throttle: замедляется при 403, ускоряется при стабильности
  - Экспоненциальный backoff (15s → 30s → 60s → 120s → 300s)
  - Circuit breaker: 5 подряд 403 → кулдаун 5 мин
  - Случайные «человеческие» паузы (10% шанс длинной задержки)
  - Ротация сессий каждые ~35 запросов (свежие куки + TLS)
  - «Разогрев» новой сессии — первый запрос к HTML-странице
"""
from __future__ import annotations

import logging
import math
import random
import time
import urllib.parse

from curl_cffi import requests as cffi_requests

import config

logger = logging.getLogger(__name__)

# ── Browser profiles ─────────────────────────────────────────────────────────
# (impersonate_name, sec-ch-ua header, user-agent)
_PROFILES = [
    (
        "chrome131",
        '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ),
    (
        "chrome133a",
        '"Google Chrome";v="133", "Chromium";v="133", "Not(A:Brand";v="99"',
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    ),
    (
        "chrome136",
        '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    ),
]

_ACCEPT_LANGS = [
    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "ru,en-US;q=0.9,en;q=0.8",
    "ru-RU,ru;q=0.9",
]

_TIMEOUT = 15


# ── Adaptive throttle ────────────────────────────────────────────────────────

class AdaptiveThrottle:
    """
    Адаптивно управляет задержками между запросами.
    При 403 — увеличивает множитель; при серии ОК — плавно снижает.
    """

    def __init__(self):
        self._penalty: float = 1.0       # множитель задержки
        self._consecutive_ok: int = 0
        self._consecutive_fail: int = 0
        self._total_ok: int = 0
        self._total_fail: int = 0

    def wait_between_requests(self) -> None:
        """Пауза между обычными запросами внутри шарда."""
        lo = config.REQUEST_DELAY_MIN * self._penalty
        hi = config.REQUEST_DELAY_MAX * self._penalty
        delay = random.uniform(lo, hi)
        # 10% шанс «человеческой» длинной паузы
        if random.random() < 0.10:
            delay += random.uniform(5, 15)
            logger.debug("Extra human pause +%.1fs", delay - lo)
        time.sleep(delay)

    def wait_between_shards(self) -> None:
        """Пауза между шардами — «переключение фильтра»."""
        lo = config.SHARD_PAUSE_MIN * self._penalty
        hi = config.SHARD_PAUSE_MAX * self._penalty
        delay = random.uniform(lo, hi)
        logger.debug("Shard pause: %.1fs", delay)
        time.sleep(delay)

    def wait_backoff(self, attempt: int) -> None:
        """Экспоненциальный backoff при 403: base * 2^attempt, capped."""
        delay = min(
            config.RETRY_BACKOFF_BASE * (2 ** attempt),
            config.RETRY_BACKOFF_MAX,
        )
        # Немного jitter чтобы не быть предсказуемым
        delay *= random.uniform(0.8, 1.3)
        logger.info("Backoff: %.0fs (attempt %d, penalty x%.1f)", delay, attempt + 1, self._penalty)
        time.sleep(delay)

    def wait_circuit_breaker(self) -> None:
        """Долгий кулдаун при серии провалов."""
        cooldown = config.CIRCUIT_BREAKER_COOLDOWN * random.uniform(0.8, 1.2)
        logger.warning(
            "Circuit breaker: %d consecutive 403s. Cooldown %.0fs (%.1f min)",
            self._consecutive_fail, cooldown, cooldown / 60,
        )
        time.sleep(cooldown)
        self._consecutive_fail = 0
        self._penalty = max(self._penalty, 1.5)  # не снижаем сразу

    def report_ok(self) -> None:
        self._consecutive_ok += 1
        self._consecutive_fail = 0
        self._total_ok += 1
        # Плавно снижаем penalty после 8 успехов подряд
        if self._consecutive_ok >= 8 and self._penalty > 1.0:
            self._penalty = max(1.0, self._penalty * 0.85)
            logger.debug("Penalty decreased -> x%.2f", self._penalty)

    def report_fail(self) -> None:
        self._consecutive_fail += 1
        self._consecutive_ok = 0
        self._total_fail += 1
        # Увеличиваем penalty
        self._penalty = min(3.0, self._penalty * 1.4)
        logger.debug("Penalty increased -> x%.2f (consecutive_fail=%d)",
                      self._penalty, self._consecutive_fail)

    @property
    def should_circuit_break(self) -> bool:
        return self._consecutive_fail >= config.CIRCUIT_BREAKER_FAILS

    @property
    def stats(self) -> str:
        total = self._total_ok + self._total_fail
        rate = self._total_ok / total * 100 if total else 0
        return f"ok={self._total_ok} fail={self._total_fail} rate={rate:.0f}% penalty=x{self._penalty:.1f}"


throttle = AdaptiveThrottle()


# ── Session management ───────────────────────────────────────────────────────

class SessionManager:
    """Управляет curl_cffi сессией с ротацией профиля и разогревом."""

    def __init__(self):
        self._session: cffi_requests.Session | None = None
        self._request_count = 0
        self._profile_idx: int = -1
        self._imp: str = ""
        self._sec_ch_ua: str = ""
        self._user_agent: str = ""
        self._warmed_up: bool = False
        self.rotate()

    def rotate(self) -> None:
        """Создаёт новую сессию с другим профилем."""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass

        # Выбираем следующий профиль (циклически, не случайно — чтобы не повторять)
        self._profile_idx = (self._profile_idx + 1) % len(_PROFILES)
        self._imp, self._sec_ch_ua, self._user_agent = _PROFILES[self._profile_idx]
        self._session = cffi_requests.Session(impersonate=self._imp)
        self._request_count = 0
        self._warmed_up = False
        logger.debug("Session rotated -> %s (count reset)", self._imp)

    def _warm_up(self) -> None:
        """
        «Разогрев» сессии — первый запрос к HTML-странице.
        Реальный браузер не начинает с API, он сначала загружает страницу.
        Это устанавливает куки и выглядит естественно.
        """
        if self._warmed_up:
            return
        try:
            warmup_url = config.REFERER_URL
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                          "image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": random.choice(_ACCEPT_LANGS),
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "User-Agent": self._user_agent,
                "Sec-Ch-Ua": self._sec_ch_ua,
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
            r = self._session.get(warmup_url, headers=headers, timeout=_TIMEOUT)
            logger.debug("Warm-up: %s -> %d (%d bytes)", self._imp, r.status_code, len(r.content))
            # Пауза после загрузки «страницы» — человек её читает
            time.sleep(random.uniform(2, 5))
        except Exception as e:
            logger.debug("Warm-up failed: %s (continuing anyway)", e)
        self._warmed_up = True

    @property
    def session(self) -> cffi_requests.Session:
        if (self._request_count >= config.SESSION_ROTATE_EVERY
                or self._session is None):
            self.rotate()
        return self._session  # type: ignore[return-value]

    def make_headers(self) -> dict:
        """Заголовки, строго соответствующие текущему профилю сессии."""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": random.choice(_ACCEPT_LANGS),
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Referer": config.REFERER_URL,
            "User-Agent": self._user_agent,
            "Sec-Ch-Ua": self._sec_ch_ua,
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }

    def get(self, url: str) -> cffi_requests.Response:
        """Выполняет GET с разогревом при первом запросе сессии."""
        self._warm_up()
        self._request_count += 1
        headers = self.make_headers()
        return self.session.get(url, headers=headers, timeout=_TIMEOUT)

    def close(self) -> None:
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass


_sm = SessionManager()


def _build_url(page: int, extra: dict | None = None) -> str:
    params = {**config.API_PARAMS, "p": page}
    if extra:
        params.update(extra)
    return config.API_URL + "?" + urllib.parse.urlencode(params)


# ── Core fetch ───────────────────────────────────────────────────────────────

def fetch_page(
    page: int,
    extra_params: dict | None = None,
    max_retries: int = 3,
) -> list[dict] | None:
    """
    Загружает одну страницу API.
    Возвращает: list[dict] — items, [] — пустая страница, None — провал.

    Стратегия retry:
    1. При 403 — экспоненциальный backoff + ротация сессии
    2. При 429 — длинный backoff
    3. Circuit breaker — при серии 403 подряд
    """
    url = _build_url(page, extra_params)

    for attempt in range(max_retries):
        # Circuit breaker check
        if throttle.should_circuit_break:
            throttle.wait_circuit_breaker()
            _sm.rotate()

        try:
            r = _sm.get(url)

            if r.status_code == 200:
                throttle.report_ok()
                data = r.json()
                cat = data.get("catalog", {})
                items = [i for i in cat.get("items", []) if i.get("type") == "item"]
                return items

            if r.status_code == 403:
                throttle.report_fail()
                if attempt < max_retries - 1:
                    throttle.wait_backoff(attempt)
                    _sm.rotate()
                    continue
                logger.debug("p%d: 403 after %d attempts", page, max_retries)
                return None

            if r.status_code == 429:
                throttle.report_fail()
                logger.warning("p%d: 429 rate limit", page)
                throttle.wait_backoff(attempt + 1)  # более агрессивный backoff
                _sm.rotate()
                continue

            logger.warning("p%d: HTTP %d", page, r.status_code)
            return None

        except Exception as e:
            logger.debug("p%d: error %s (attempt %d/%d)", page, e, attempt + 1, max_retries)
            throttle.report_fail()
            if attempt < max_retries - 1:
                throttle.wait_backoff(attempt)
                _sm.rotate()
            continue

    return None


def close() -> None:
    """Закрывает текущую сессию."""
    _sm.close()


# ── Data extraction ──────────────────────────────────────────────────────────

def extract_listing(raw: dict) -> dict:
    """Извлекает максимум полезных данных из raw API item."""
    # Изображения
    images = raw.get("images") or []
    thumbnail = ""
    all_images: list[str] = []
    for img in images:
        for key in ("864x864", "636x636"):
            if key in img:
                all_images.append(img[key])
                break
    if all_images:
        thumbnail = all_images[0]

    # Цена
    price_d = raw.get("priceDetailed") or {}

    # Координаты
    coords = raw.get("coords") or {}

    # Геоданные
    geo = raw.get("geo") or {}
    geo_refs = geo.get("geoReferences") or []
    geo_text = ", ".join(r.get("content", "") for r in geo_refs if r.get("content"))

    # URL
    url_path = raw.get("urlPath", "")
    clean_path = url_path.split("?")[0] if url_path else ""

    # Категория
    category = raw.get("category") or {}

    # Локация
    location = raw.get("location") or {}
    addr_detail = raw.get("addressDetailed") or {}

    # Продавец
    seller = _extract_seller(raw)

    # Время
    sort_ts = raw.get("sortTimeStamp")
    allow_ts = raw.get("allowTimeStamp")

    return {
        "id":               raw.get("id"),
        "categoryId":       raw.get("categoryId"),
        "categoryName":     category.get("name", ""),
        "categorySlug":     category.get("slug", ""),
        "title":            raw.get("title", ""),
        "description":      raw.get("description", ""),
        "url":              config.BASE_URL + clean_path if clean_path else "",
        "price":            price_d.get("value"),
        "priceFormatted":   price_d.get("fullString", ""),
        "normalizedPrice":  raw.get("normalizedPrice", ""),
        "wasLowered":       price_d.get("wasLowered", False),
        "discountPercent":  raw.get("discountPercent"),
        "locationId":       raw.get("locationId"),
        "locationName":     location.get("name", ""),
        "addressShort":     addr_detail.get("locationName", ""),
        "addressFull":      coords.get("address_user", ""),
        "addressFormatted": geo.get("formattedAddress", ""),
        "geoReferences":    geo_text,
        "lat":              _to_float(coords.get("lat")),
        "lng":              _to_float(coords.get("lng")),
        "imagesCount":      raw.get("imagesCount", 0),
        "thumbnail":        thumbnail,
        "images":           all_images,
        "isVerified":       raw.get("isVerifiedItem", False),
        "seller":           seller,
        "sortTimestamp":    sort_ts,
        "publishTimestamp": allow_ts,
        "closedItemsText":  raw.get("closedItemsText", ""),
    }


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_seller(raw: dict) -> dict:
    """Извлекает информацию о продавце из IVA и userLogo."""
    seller: dict = {}

    # Из IVA steps
    iva = raw.get("iva") or {}
    for step in iva.get("UserInfoStep") or []:
        payload = step.get("payload") or {}
        component = (step.get("componentData") or {}).get("component", "")
        if component == "seller-info":
            profile = payload.get("profile") or {}
            seller["name"] = profile.get("title", "")
            seller["link"] = profile.get("link", "")
            rating = payload.get("rating")
            if rating:
                seller["rating"] = rating
        elif component == "text":
            seller["closedItems"] = payload.get("value", "")

    # Из userLogo
    user_logo = raw.get("userLogo") or {}
    if user_logo.get("src"):
        seller["logoUrl"] = user_logo["src"]
    if user_logo.get("link"):
        seller.setdefault("link", user_logo["link"])

    return seller
