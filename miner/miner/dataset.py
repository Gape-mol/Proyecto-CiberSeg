from __future__ import annotations

import logging
from typing import Any, Generator

logger = logging.getLogger(__name__)

_DATASET_NAME = "hao-li/AIDev"
_DATASET_CONFIG = "all_repository"


def iter_org_repos(org_name: str) -> Generator[dict[str, Any], None, None]:
    """Yields raw dataset rows for a given org from the AIDev HuggingFace dataset."""
    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError as e:
        raise ImportError("Instala la dependencia: pip install datasets") from e

    logger.info(f"Cargando dataset '{_DATASET_NAME}' desde Hugging Face…")
    ds = load_dataset(_DATASET_NAME, _DATASET_CONFIG, split="train")
    logger.info(f"Dataset cargado: {len(ds)} repositorios en total.")

    org_lower = org_name.lower()
    count = 0
    for row in ds:
        full_name = (row.get("full_name") or "").strip()
        owner = full_name.split("/")[0] if "/" in full_name else ""
        if owner.lower() == org_lower:
            count += 1
            yield dict(row)

    logger.info(f"Repos encontrados en dataset para org '{org_name}': {count}")
