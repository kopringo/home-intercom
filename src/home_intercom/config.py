"""Intercom configuration — YAML on disk, JSON over the wire."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from home_intercom.sounds import GONG_FILENAME

DEFAULT_CONFIG_DIR = Path(
    os.environ.get("HOME_INTERCOM_CONFIG_DIR", "/etc/home-intercom")
)
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("HOME_INTERCOM_CONFIG", DEFAULT_CONFIG_DIR / "config.yaml")
)
DEFAULT_HA_PORT = 8123


@dataclass
class IntercomConfig:
    """Runtime configuration for the intercom daemon."""

    gong_sound: str = GONG_FILENAME
    ha_ip: str = ""
    ha_token: str = ""
    media_player_entity: str = ""

    @property
    def ha_base_url(self) -> str:
        address = self.ha_ip.strip()
        if not address:
            return ""
        if address.startswith("http://") or address.startswith("https://"):
            return address.rstrip("/")
        if ":" in address:
            return f"http://{address}"
        return f"http://{address}:{DEFAULT_HA_PORT}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntercomConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, payload: str) -> IntercomConfig:
        return cls.from_dict(json.loads(payload))

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.to_dict(),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    @classmethod
    def from_yaml(cls, payload: str) -> IntercomConfig:
        data = yaml.safe_load(payload)
        if not isinstance(data, dict):
            raise ValueError("Config YAML must be a mapping")
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> IntercomConfig:
        if not path.is_file():
            return cls()
        return cls.from_yaml(path.read_text(encoding="utf-8"))

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_yaml(), encoding="utf-8")


class ConfigStore:
    """Read/write ``IntercomConfig`` with an optional in-memory cache."""

    def __init__(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        self._path = path
        self._config = IntercomConfig.load(path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def config(self) -> IntercomConfig:
        return self._config

    def reload(self) -> IntercomConfig:
        self._config = IntercomConfig.load(self._path)
        return self._config

    def update(self, config: IntercomConfig) -> IntercomConfig:
        self._config = config
        return self._config

    def save(self, config: IntercomConfig | None = None) -> IntercomConfig:
        if config is not None:
            self._config = config
        self._config.save(self._path)
        return self._config

    def to_json(self) -> str:
        return self._config.to_json()

    def from_json(self, payload: str) -> IntercomConfig:
        self._config = IntercomConfig.from_json(payload)
        return self._config
