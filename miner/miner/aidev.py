from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datasets import Dataset

logger = logging.getLogger(__name__)

AIDEV_DATASET_NAME = "hao-li/AIDev"


@dataclass
class AIDevOrg:
    """Organización del dataset AIDev."""
    login: str
    repo_count: int


class AIDevClient:
    """Cliente para cargar y consultar el dataset AIDev desde HuggingFace."""

    def __init__(self) -> None:
        self._dataset: Dataset | None = None
        # Repos agrupados por owner login — se construye una sola vez desde el dataset
        self._by_owner: dict[str, list[dict[str, Any]]] | None = None

    def _load_dataset(self) -> Dataset:
        """Carga el dataset de HuggingFace (lazy loading)."""
        if self._dataset is not None:
            return self._dataset

        try:
            from datasets import load_dataset
        except ImportError as err:
            raise ImportError(
                "Se requiere la librería 'datasets' para usar AIDev. "
                "Instala con: pip install datasets"
            ) from err

        logger.info(f"Cargando dataset AIDev: {AIDEV_DATASET_NAME}")
        self._dataset = load_dataset(AIDEV_DATASET_NAME, "all_repository", split="train")
        ds = self._dataset
        logger.info(f"Dataset cargado: {len(ds)} repositorios")
        return ds

    def _get_by_owner(self) -> dict[str, list[dict[str, Any]]]:
        """Agrupa todos los repos por owner login en una sola pasada (O(n))."""
        if self._by_owner is not None:
            return self._by_owner

        ds = self._load_dataset()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in ds:
            full_name = row.get("full_name")
            if not full_name or "/" not in str(full_name):
                continue
            login = str(full_name).split("/")[0]
            if login not in grouped:
                grouped[login] = []
            grouped[login].append(dict(row))

        self._by_owner = grouped
        logger.info(f"Dataset indexado: {len(grouped)} owners únicos")
        return grouped

    def list_organizations(self, min_stars: int = 0) -> list[AIDevOrg]:
        """Retorna lista de owners únicos en el dataset."""
        by_owner = self._get_by_owner()

        result: list[AIDevOrg] = []
        for login, rows in by_owner.items():
            count = sum(
                1 for r in rows if (r.get("stars") or 0) >= min_stars
            )
            if count > 0:
                result.append(AIDevOrg(login=login, repo_count=count))

        result.sort(key=lambda x: x.repo_count, reverse=True)
        logger.info(f"Owners encontrados (min_stars={min_stars}): {len(result)}")
        return result

    def iter_repos(
        self, org_filter: str | None = None, min_stars: int = 0
    ) -> Iterator[dict[str, Any]]:
        """Itera sobre los repos del dataset, filtrados por owner y/o min_stars."""
        by_owner = self._get_by_owner()

        owners = [org_filter] if org_filter else list(by_owner.keys())

        for login in owners:
            for row in by_owner.get(login, []):
                full_name = row.get("full_name")
                if not full_name or "/" not in str(full_name):
                    continue
                _, name = str(full_name).split("/", 1)
                stars = row.get("stars") or 0
                if (stars or 0) < min_stars:
                    continue
                yield {
                    **row,
                    "name": name,
                    "owner": {"login": login},
                    "stargazers_count": int(stars or 0),
                    "forks_count": int(row.get("forks") or 0),
                    "clone_url": f"https://github.com/{full_name}.git",
                }

    def org_exists(self, org_name: str) -> bool:
        """Verifica si un owner existe en el dataset."""
        return org_name in self._get_by_owner()


def create_aidev_client() -> AIDevClient:
    """Factory para crear un AIDevClient."""
    return AIDevClient()
