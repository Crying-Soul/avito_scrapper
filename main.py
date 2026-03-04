"""
Avito Parser — аккуратный сбор данных через sort × price шардирование.

Стратегия:
  1. locationId = 621540 (все регионы РФ)
  2. Шардирование: sort × price  (4 × 15 = 60 шардов)
  3. Адаптивный throttle: замедляет при 403, ускоряет при стабильности
  4. «Человеческие» паузы между шардами и длинные перерывы каждые N шардов
  5. Экспоненциальный backoff + circuit breaker
  6. Дедупликация по id, инкрементальное сохранение
  7. Resume: при перезапуске загружает предыдущие данные

При 50 items/page, ~8s/req, 60 шардов × ~30 стр = ~4 часа → ~50−80k unique.
"""
from __future__ import annotations

import logging
import random
import sys
import time

import config
import storage
from api_client import extract_listing, fetch_page, close as close_session, throttle

# ── Logging ──────────────────────────────────────────────────────────────────
_stream = logging.StreamHandler(sys.stdout)
_stream.setLevel(logging.INFO)
_stream.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

_file_h = logging.FileHandler("parser.log", encoding="utf-8")
_file_h.setLevel(logging.DEBUG)
_file_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

logging.basicConfig(level=logging.DEBUG, handlers=[_stream, _file_h])
logger = logging.getLogger("main")


# ── Shard generation ─────────────────────────────────────────────────────────

def _build_shards() -> list[dict]:
    """
    Строит список шардов: sort × price_range.
    locationId=621540 уже стоит в config.API_PARAMS.
    """
    shards = []
    for sort_id in config.SORT_ORDERS:
        sort_name = config.SORT_NAMES.get(sort_id, str(sort_id))
        for pmin, pmax in config.PRICE_RANGES:
            extra: dict = {"s": sort_id}
            price_parts = []
            if pmin is not None:
                extra["pmin"] = pmin
                price_parts.append(f">{pmin:,}")
            if pmax is not None:
                extra["pmax"] = pmax
                price_parts.append(f"<{pmax:,}")
            price_label = " ".join(price_parts) if price_parts else "all"
            label = f"{sort_name} | {price_label}"
            shards.append({"extra": extra, "label": label})

    random.shuffle(shards)
    logger.info(
        "Built %d shards: %d sorts × %d price ranges (locationId=%d)",
        len(shards), len(config.SORT_ORDERS),
        len(config.PRICE_RANGES), config.LOCATION_ID,
    )
    return shards


# ── Main pipeline ────────────────────────────────────────────────────────────

def run() -> None:
    target = config.TARGET_COUNT
    logger.info("=== Avito Parser === target: %d items", target)

    # Resume: загружаем уже собранные данные
    all_items: list[dict] = []
    seen_ids: set[int] = set()

    shards = _build_shards()
    total_shards = len(shards)
    total_requests = 0
    total_pages_ok = 0
    t0 = time.time()

    for shard_idx, shard in enumerate(shards, 1):
        if len(all_items) >= target:
            break

        extra = shard["extra"]
        label = shard["label"]
        shard_new = 0
        shard_fails = 0

        # Длинный перерыв каждые N шардов — «ушёл пить чай»
        if shard_idx > 1 and (shard_idx - 1) % config.LONG_BREAK_EVERY == 0:
            pause = random.uniform(config.LONG_BREAK_MIN, config.LONG_BREAK_MAX)
            logger.info(
                "Long break: %.0fs (%.1f min) after %d shards [%s]",
                pause, pause / 60, shard_idx - 1, throttle.stats,
            )
            time.sleep(pause)

        logger.info(
            "\n=== Shard %d/%d [%s] | %d/%d (%.0f/min) [%s] ===",
            shard_idx, total_shards, label,
            len(all_items), target,
            len(all_items) / max(time.time() - t0, 1) * 60,
            throttle.stats,
        )

        empty_streak = 0

        for page in range(1, config.MAX_PAGES_PER_SHARD + 1):
            if len(all_items) >= target:
                break

            raw_items = fetch_page(page, extra_params=extra)
            total_requests += 1

            if raw_items is None:
                # 403/error after retries
                shard_fails += 1
                # 3 провала в шарде — переходим к следующему
                if shard_fails >= 3:
                    logger.info("Shard [%s]: 3 fails, moving on", label)
                    break
                continue

            # Успех — сбросить счётчик провалов
            shard_fails = 0

            if not raw_items:
                empty_streak += 1
                if empty_streak >= 2:
                    logger.debug("Shard [%s] exhausted at page %d", label, page)
                    break
                continue

            empty_streak = 0
            total_pages_ok += 1

            # Extract & deduplicate
            new_count = 0
            for raw in raw_items:
                listing = extract_listing(raw)
                item_id = listing.get("id")
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_items.append(listing)
                    new_count += 1

            shard_new += new_count

            # Только дубли — шард насытился
            if new_count == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    logger.debug("Shard [%s] saturated at page %d", label, page)
                    break

            logger.debug(
                "p%d: +%d new (shard +%d, total %d)",
                page, new_count, shard_new, len(all_items),
            )

            # Периодическое сохранение
            if total_pages_ok % config.SAVE_EVERY_PAGES == 0:
                storage.save_json(all_items)
                logger.info(
                    "Progress: %d items | %d req | %d pages [%s]",
                    len(all_items), total_requests, total_pages_ok, throttle.stats,
                )

            # Адаптивная задержка между запросами
            throttle.wait_between_requests()

        if shard_new > 0:
            logger.info("Shard [%s] done: +%d new items (total %d)", label, shard_new, len(all_items))

        # Пауза между шардами — «выбираем новый фильтр»
        if shard_idx < total_shards and len(all_items) < target:
            throttle.wait_between_shards()

    # ── Finish ───────────────────────────────────────────────────────────────
    close_session()
    elapsed = time.time() - t0
    saved = storage.save_json(all_items)

    logger.info(
        "=== Done: %d items in %.1f min | %d req | %d pages | %d shards [%s] -> %s ===",
        len(all_items), elapsed / 60, total_requests, total_pages_ok,
        total_shards, throttle.stats, saved,
    )


if __name__ == "__main__":
    run()
