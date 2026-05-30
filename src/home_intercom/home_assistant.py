"""Home Assistant REST API integration."""

from __future__ import annotations

import json
import socket
import socketserver
import threading
import time
from http import server as http_server
from pathlib import Path

import requests

from home_intercom.config import IntercomConfig

PLAY_MEDIA_FEATURE = 512


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


class HomeAssistantClient:
    """Play media and query entities via Home Assistant."""

    def __init__(
        self,
        config: IntercomConfig,
        *,
        host_ip: str | None = None,
        serve_port: int = 8765,
    ) -> None:
        self._config = config
        self._host_ip = host_ip
        self._serve_port = serve_port

    @property
    def config(self) -> IntercomConfig:
        return self._config

    def update_config(self, config: IntercomConfig) -> None:
        self._config = config

    @property
    def base_url(self) -> str:
        return self._config.ha_base_url

    @property
    def token(self) -> str:
        return self._config.ha_token

    @property
    def entity_id(self) -> str:
        return self._config.media_player_entity

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _get(self, path: str) -> object:
        response = requests.get(
            f"{self.base_url}/api{path}",
            headers=self._headers(),
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict[str, object]) -> object | None:
        response = requests.post(
            f"{self.base_url}/api{path}",
            headers={**self._headers(), "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10,
        )
        response.raise_for_status()
        return response.json() if response.text else None

    def list_media_players(self) -> list[dict[str, object]]:
        """Return ``media_player.*`` entities that may support ``play_media``."""
        states = self._get("/states")
        if not isinstance(states, list):
            return []

        players: list[dict[str, object]] = []
        for state in states:
            if not isinstance(state, dict):
                continue
            entity_id = state.get("entity_id", "")
            if not isinstance(entity_id, str) or not entity_id.startswith(
                "media_player."
            ):
                continue

            attrs = state.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}
            supported = attrs.get("supported_features", 0) or 0
            can_play_media = bool(int(supported) & PLAY_MEDIA_FEATURE)

            players.append(
                {
                    "entity_id": entity_id,
                    "name": attrs.get("friendly_name", entity_id),
                    "state": state.get("state"),
                    "can_play_media": can_play_media,
                    "supported_features": supported,
                }
            )

        return players

    def _serve_wav(self, wav_path: Path) -> http_server.HTTPServer:
        file_path = wav_path.resolve()
        directory = str(file_path.parent)
        filename = file_path.name

        class Handler(http_server.SimpleHTTPRequestHandler):
            def translate_path(self, path: str) -> str:
                return str(Path(directory) / filename)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        httpd = http_server.HTTPServer(("", self._serve_port), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd

    def play_wav(
        self,
        wav_path: Path,
        *,
        entity_id: str | None = None,
        content_type: str = "music",
        serve_seconds: float = 3.0,
    ) -> str:
        """Serve *wav_path* locally and ask HA to play it on *entity_id*."""
        resolved = wav_path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"WAV not found: {resolved}")

        target_entity = entity_id or self.entity_id
        if not target_entity:
            raise ValueError("media_player_entity is not configured")

        host_ip = self._host_ip or local_ip()
        httpd = self._serve_wav(resolved)
        url = f"http://{host_ip}:{self._serve_port}/{resolved.name}"

        try:
            self._post(
                "/services/media_player/play_media",
                {
                    "entity_id": target_entity,
                    "media_content_id": url,
                    "media_content_type": content_type,
                },
            )
        finally:
            time.sleep(serve_seconds)
            httpd.shutdown()

        return url
