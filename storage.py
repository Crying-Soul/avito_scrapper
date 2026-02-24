from __future__ import annotations

import json
import logging
import os
from typing import Any

import config

logger = logging.getLogger(__name__)


def save_to_json(data: list[dict[str, Any]], filepath: str = config.OUTPUT_FILE) -> str:
    abs_path = os.path.abspath(filepath)
    with open(abs_path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    logger.info("Saved %d listings -> %s", len(data), abs_path)
    return abs_path


def load_from_json(filepath: str = config.OUTPUT_FILE) -> list[dict[str, Any]]:
    abs_path = os.path.abspath(filepath)
    if not os.path.isfile(abs_path):
        return []
    with open(abs_path, encoding="utf-8") as fp:
        return json.load(fp)
