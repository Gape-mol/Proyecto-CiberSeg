from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

from .types import StoreCollections
from .utils import now_str

logger = logging.getLogger(__name__)


# Manages the in-memory JSON store and disk persistence.
class StoreCore:
    # Initializes the core store with a JSON file path.
    def __init__(self, db_path: str, collections: StoreCollections) -> None:
        self._db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._collections = collections
        self._store: dict[str, Any] = self._base_store()

    # Loads or creates the JSON store on disk.
    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not (self._db_path.exists() and self._db_path.stat().st_size > 0)
        loaded = self._base_store() if is_new else self._load_store()
        # Update in-place so sub-stores that hold a reference to this dict stay in sync.
        self._store.clear()
        self._store.update(loaded)
        if is_new:
            self.flush_unlocked()
        logger.info(f"JSON store conectado: {self._db_path}")

    # Flushes the store to disk and releases resources.
    async def close(self) -> None:
        async with self._lock:
            self.flush_unlocked()
        logger.info("JSON store cerrado.")

    # Keeps compatibility with legacy schema calls.
    async def apply_schema(self, schema_path: Path) -> None:
        logger.info(f"Schema SQLite ignorado; usando JSON store en {self._db_path}")

    # Returns the internal asyncio lock.
    def lock(self) -> asyncio.Lock:
        return self._lock

    # Returns the in-memory store dictionary.
    def store(self) -> dict[str, Any]:
        return self._store

    # Writes the in-memory store to disk.
    def flush_unlocked(self) -> None:
        self._store["meta"]["updated_at"] = now_str()
        self._db_path.write_text(json.dumps(self._store, indent=2, ensure_ascii=True))

    # Allocates an id for a collection and increments the counter.
    def allocate_id_unlocked(self, collection: str) -> int:
        next_id = cast(int, self._store["next_ids"][collection])
        self._store["next_ids"][collection] += 1
        return next_id

    # Appends a row to a collection and assigns an id.
    def append_row_unlocked(self, collection: str, row: dict[str, Any]) -> int:
        row["id"] = self.allocate_id_unlocked(collection)
        self._store[collection].append(row)
        return cast(int, row["id"])

    # Finds the first row matching the provided filters.
    def find_one_unlocked(self, collection: str, **filters: Any) -> dict[str, Any] | None:
        for row in self._store[collection]:
            if all(row.get(key) == value for key, value in filters.items()):
                return cast(dict[str, Any], row)
        return None

    def _base_store(self) -> dict[str, Any]:
        collections = [value for value in vars(self._collections).values() if isinstance(value, str)]
        return {
            "meta": {
                "format": "miner-json-v1",
                "updated_at": now_str(),
            },
            "next_ids": {name: 1 for name in collections},
            **{name: [] for name in collections},
        }

    def _load_store(self) -> dict[str, Any]:
        collections = [value for value in vars(self._collections).values() if isinstance(value, str)]
        data = cast(dict[str, Any], json.loads(self._db_path.read_text()))
        for name in collections:
            data.setdefault(name, [])
        next_ids = data.setdefault("next_ids", {})
        for name in collections:
            next_ids.setdefault(name, self._next_id_from_rows(data[name]))
        data.setdefault("meta", {})
        data["meta"].setdefault("format", "miner-json-v1")
        data["meta"]["updated_at"] = now_str()
        return data

    @staticmethod
    def _next_id_from_rows(rows: list[dict[str, Any]]) -> int:
        return max((row.get("id", 0) for row in rows), default=0) + 1
