from __future__ import annotations

import logging
import sys
import time

import api_client
import config
import page_scraper
import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("parser.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def run() -> None:
    logger.info("=== Avito Parser started ===")

    # Шаг 1: прогрев сессии для получения cookies
    api_client.warm_up()
    time.sleep(0.5)

    # Шаг 2: получить список объявлений через API
    raw_items = api_client.fetch_all_items()
    if not raw_items:
        logger.warning("No items fetched. Exiting.")
        return

    metas = [api_client.extract_item_meta(r) for r in raw_items]
    total = len(metas)
    logger.info("Scraping %d listings...", total)

    # Шаг 3: скрапить каждую страницу объявления
    results: list[dict] = []
    for i, meta in enumerate(metas, 1):
        logger.info("[%d/%d] %s", i, total, meta["url"])
        extra = page_scraper.scrape_listing(meta["url"])
        meta.update(extra)
        results.append(meta)

        # Промежуточное сохранение каждые 10 записей
        if i % 10 == 0:
            storage.save_to_json(results)

        # Минимальная пауза между запросами
        if i < total:
            time.sleep(config.REQUEST_DELAY)

    saved_path = storage.save_to_json(results)
    logger.info("=== Done: %d listings saved to %s ===", total, saved_path)


if __name__ == "__main__":
    run()
