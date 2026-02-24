from __future__ import annotations
import os
import time
from dotenv import load_dotenv

load_dotenv()

BASE_URL: str = "https://www.avito.ru"
API_URL: str = "https://www.avito.ru/web/1/main/items"

API_PARAMS: dict = {
    "forceLocation": os.getenv("FORCE_LOCATION", "false"),
    "locationId":   int(os.getenv("LOCATION_ID",  "653240")),
    "lastStamp":    int(os.getenv("LAST_STAMP",   str(int(time.time())))),
    "categoryId":   int(os.getenv("CATEGORY_ID",  "4")),
}

LIMIT:             int   = int(os.getenv("LIMIT",             "10"))
OFFSET_START:      int   = int(os.getenv("OFFSET_START",      "0"))
REQUEST_DELAY:     float = float(os.getenv("REQUEST_DELAY",    "0.8"))
PAGE_LOAD_TIMEOUT: int   = int(os.getenv("PAGE_LOAD_TIMEOUT", "20"))
OUTPUT_FILE:       str   = os.getenv("OUTPUT_FILE", "output/avito_listings.json")
