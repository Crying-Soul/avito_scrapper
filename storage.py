"""
Модуль хранения: сохранение/загрузка результатов в JSON.
Каждый запуск создаёт новый файл с таймстампом.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import config

logger = logging.getLogger(__name__)

_RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
_OUTPUT_PATH: str | None = None


def _get_output_path() -> str:
    global _OUTPUT_PATH
    if _OUTPUT_PATH is None:
        out_dir = os.path.abspath(config.OUTPUT_DIR)
        os.makedirs(out_dir, exist_ok=True)
        _OUTPUT_PATH = os.path.join(out_dir, f"avito_{_RUN_TIMESTAMP}.json")
    return _OUTPUT_PATH


def save_json(data: list[dict[str, Any]], filepath: str | None = None) -> str:
    """Атомарно сохраняет список объявлений в JSON."""
    abs_path = os.path.abspath(filepath or _get_output_path())
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    tmp_path = abs_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp_path, abs_path)

    logger.info("Saved %d items -> %s", len(data), abs_path)
    return abs_path


def load_json(filepath: str | None = None) -> list[dict[str, Any]]:
    """Загружает ранее сохранённые результаты."""
    abs_path = os.path.abspath(filepath or _get_output_path())
    if not os.path.isfile(abs_path):
        return []
    with open(abs_path, encoding="utf-8") as fp:
        return json.load(fp)
