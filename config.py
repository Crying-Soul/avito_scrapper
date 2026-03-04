"""
Конфигурация парсера Avito.
Все параметры можно переопределить через .env или переменные окружения.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Базовые URL ──────────────────────────────────────────────────────────────
BASE_URL: str = "https://www.avito.ru"
API_URL: str = "https://www.avito.ru/web/1/js/items"

# ── Локация ──────────────────────────────────────────────────────────────────
LOCATION_ID: int = int(os.getenv("LOCATION_ID", "621540"))  # Все регионы

# ── Параметры API-запроса (земельные участки, продажа) ─────────────────────────
API_PARAMS: dict = {
    "categoryId":         int(os.getenv("CATEGORY_ID", "26")),
    "params[203]":        int(os.getenv("PARAMS_203", "1069")),
    "verticalCategoryId": int(os.getenv("VERTICAL_CATEGORY_ID", "1")),
    "rootCategoryId":     int(os.getenv("ROOT_CATEGORY_ID", "4")),
    "locationId":         LOCATION_ID,
    "localPriority":      0,
    "updateListOnly":     "true",
}

# ── Referer ──────────────────────────────────────────────────────────────────
REFERER_URL: str = os.getenv(
    "REFERER_URL",
    "https://www.avito.ru/rossiya/zemelnye_uchastki/"
    "prodam-ASgBAgECAkSSA8gQ8AeQUg",
)

# ── Пагинация ────────────────────────────────────────────────────────────────
MAX_PAGES_PER_SHARD: int = int(os.getenv("MAX_PAGES_PER_SHARD", "100"))

# ── Целевое количество ───────────────────────────────────────────────────────
TARGET_COUNT: int = int(os.getenv("TARGET_COUNT", "100000"))

# ── Тайминг (секунды) — имитация человека ────────────────────────────────────
REQUEST_DELAY_MIN: float = float(os.getenv("REQUEST_DELAY_MIN", "6"))
REQUEST_DELAY_MAX: float = float(os.getenv("REQUEST_DELAY_MAX", "12"))
# Пауза между шардами (имитирует выбор нового фильтра)
SHARD_PAUSE_MIN: float = float(os.getenv("SHARD_PAUSE_MIN", "12"))
SHARD_PAUSE_MAX: float = float(os.getenv("SHARD_PAUSE_MAX", "25"))
# Длинный перерыв (каждые N шардов — «ушёл пить чай»)
LONG_BREAK_EVERY: int = int(os.getenv("LONG_BREAK_EVERY", "12"))
LONG_BREAK_MIN: float = float(os.getenv("LONG_BREAK_MIN", "60"))
LONG_BREAK_MAX: float = float(os.getenv("LONG_BREAK_MAX", "150"))
# Backoff при 403 — экспоненциальный
RETRY_BACKOFF_BASE: float = float(os.getenv("RETRY_BACKOFF_BASE", "15"))
RETRY_BACKOFF_MAX: float = float(os.getenv("RETRY_BACKOFF_MAX", "300"))
# Circuit breaker — при серии 403 подряд
CIRCUIT_BREAKER_FAILS: int = int(os.getenv("CIRCUIT_BREAKER_FAILS", "5"))
CIRCUIT_BREAKER_COOLDOWN: float = float(os.getenv("CIRCUIT_BREAKER_COOLDOWN", "300"))

# ── Сессии (ротация для анти-детекта) ────────────────────────────────────────
SESSION_ROTATE_EVERY: int = int(os.getenv("SESSION_ROTATE_EVERY", "35"))

# ── Вывод ────────────────────────────────────────────────────────────────────
OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "output")
SAVE_EVERY_PAGES: int = int(os.getenv("SAVE_EVERY_PAGES", "20"))

# ── Сортировки Avito ─────────────────────────────────────────────────────────
# 101=по умолчанию, 1=дешевле, 2=дороже, 104=по дате
SORT_ORDERS: list[int] = [101, 1, 2, 104]
SORT_NAMES: dict[int, str] = {
    101: "default", 1: "cheapest", 2: "expensive", 104: "newest",
}

# ── Ценовые диапазоны (гранулярное шардирование) ─────────────────────────────
# Чем мельче диапазоны — тем больше уникальных объявлений на каждый шард
PRICE_RANGES: list[tuple[int | None, int | None]] = [
    (None,          100_000),
    (100_000,       200_000),
    (200_000,       350_000),
    (350_000,       500_000),
    (500_000,       700_000),
    (700_000,     1_000_000),
    (1_000_000,   1_500_000),
    (1_500_000,   2_000_000),
    (2_000_000,   3_000_000),
    (3_000_000,   5_000_000),
    (5_000_000,   8_000_000),
    (8_000_000,  15_000_000),
    (15_000_000, 30_000_000),
    (30_000_000, 60_000_000),
    (60_000_000, None),
]
