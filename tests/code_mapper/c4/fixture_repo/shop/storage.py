"""Filesystem storage and an inheritance reference."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class OrderRecord:
    order_id: str


class BaseStorage:
    data_dir: Path = Path("/data")

    def save(self, order_id: str) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / order_id).write_text(order_id, encoding="utf-8")


class Storage(BaseStorage):
    """Orders stored in the configured data directory."""
