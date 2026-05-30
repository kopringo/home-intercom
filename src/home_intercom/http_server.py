"""HTTP configuration UI and JSON API (default port 8080)."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

import requests

from home_intercom.config import ConfigStore, IntercomConfig
from home_intercom.home_assistant import HomeAssistantClient
from home_intercom.restart import RestartWatcher
from home_intercom.sounds import list_sound_files

DEFAULT_HTTP_PORT = 8080

_INDEX_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Home Intercom — konfiguracja</title>
  <style>
    :root { font-family: system-ui, sans-serif; color: #1a1a1a; background: #f4f4f5; }
    body { max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.35rem; }
    fieldset { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; background: #fff; }
    legend { font-weight: 600; padding: 0 0.35rem; }
    label { display: block; margin: 0.75rem 0 0.25rem; font-size: 0.9rem; }
    input, select { width: 100%; box-sizing: border-box; padding: 0.45rem 0.55rem; font-size: 1rem; }
    .actions { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-top: 1rem; }
    button { padding: 0.55rem 1rem; font-size: 0.95rem; cursor: pointer; border-radius: 6px; border: 1px solid #888; background: #fff; }
    button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
    button.danger { background: #dc2626; color: #fff; border-color: #dc2626; }
    #status { min-height: 1.25rem; margin-top: 0.75rem; font-size: 0.9rem; }
    #status.ok { color: #15803d; }
    #status.err { color: #b91c1c; }
    .hint { font-size: 0.8rem; color: #555; margin-top: 0.2rem; }
    .info { font-size: 0.85rem; color: #333; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 0.75rem 0.9rem; margin: 0.75rem 0 0; line-height: 1.45; }
    .info ol { margin: 0.4rem 0 0; padding-left: 1.25rem; }
    .info a { color: #1d4ed8; }
  </style>
</head>
<body>
  <h1>Home Intercom — konfiguracja</h1>
  <form id="cfg">
    <fieldset>
      <legend>Dźwięk</legend>
      <label for="gong_sound">Plik gongu (katalog sounds)</label>
      <select id="gong_sound" name="gong_sound"></select>
    </fieldset>
    <fieldset>
      <legend>Home Assistant</legend>
      <label for="ha_ip">Adres Home Assistant</label>
      <input id="ha_ip" name="ha_ip" type="text" placeholder="192.168.1.10 lub 192.168.1.10:8124" autocomplete="off">
      <p class="hint">Sam IP (domyślnie port 8123), <code>IP:port</code> lub pełny URL, np. <code>http://192.168.1.10:8124</code>.</p>
      <label for="ha_token">Token</label>
      <input id="ha_token" name="ha_token" type="password" autocomplete="off">
      <div class="info">
        <strong>Gdzie wygenerować token?</strong>
        <ol>
          <li>Otwórz Home Assistant w przeglądarce.</li>
          <li>Kliknij swój <strong>profil</strong> (lewy dolny róg).</li>
          <li>Przejdź do <strong>Bezpieczeństwo</strong> → <strong>Tokeny dostępu długoterminowego</strong>.</li>
          <li>Kliknij <strong>Utwórz token</strong>, nadaj nazwę (np. „intercom”) i skopiuj wygenerowany token tutaj.</li>
        </ol>
        <p class="hint" style="margin-top:0.5rem">
          Dokumentacja:
          <a href="https://www.home-assistant.io/docs/authentication/#your-account-profile" target="_blank" rel="noopener">Long-lived access tokens</a>
        </p>
      </div>
      <label for="media_player_entity">Encja media player</label>
      <select id="media_player_entity" name="media_player_entity">
        <option value="">— wybierz po zapisaniu adresu i tokenu —</option>
      </select>
      <p class="hint">Lista encji odświeża się po zapisaniu konfiguracji HA.</p>
    </fieldset>
    <div class="actions">
      <button type="submit" class="primary">Zapisz</button>
      <button type="button" id="reloadEntities">Odśwież encje</button>
      <button type="button" id="restart" class="danger">Restart intercomu</button>
    </div>
    <div id="status"></div>
  </form>
  <script>
    const statusEl = document.getElementById("status");
    const entitySelect = document.getElementById("media_player_entity");
    const gongSelect = document.getElementById("gong_sound");

    function setStatus(text, ok) {
      statusEl.textContent = text;
      statusEl.className = ok ? "ok" : "err";
    }

    async function loadSounds(selected) {
      const res = await fetch("/api/sounds");
      const sounds = await res.json();
      gongSelect.replaceChildren();
      for (const name of sounds) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        gongSelect.appendChild(opt);
      }
      if (selected) gongSelect.value = selected;
    }

    async function loadEntities(selected) {
      const res = await fetch("/api/entities");
      if (!res.ok) {
        entitySelect.replaceChildren();
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Nie udało się pobrać encji (sprawdź adres HA i token)";
        entitySelect.appendChild(opt);
        return;
      }
      const entities = await res.json();
      entitySelect.replaceChildren();
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "— wybierz —";
      entitySelect.appendChild(empty);
      for (const e of entities) {
        const opt = document.createElement("option");
        opt.value = e.entity_id;
        const mark = e.can_play_media ? "✓" : "?";
        opt.textContent = `${mark} ${e.entity_id} (${e.name || e.entity_id})`;
        entitySelect.appendChild(opt);
      }
      if (selected) entitySelect.value = selected;
    }

    async function loadConfig() {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      document.getElementById("ha_ip").value = cfg.ha_ip || "";
      document.getElementById("ha_token").value = cfg.ha_token || "";
      await loadSounds(cfg.gong_sound);
      await loadEntities(cfg.media_player_entity);
    }

    document.getElementById("cfg").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = {
        gong_sound: gongSelect.value,
        ha_ip: document.getElementById("ha_ip").value.trim(),
        ha_token: document.getElementById("ha_token").value.trim(),
        media_player_entity: entitySelect.value,
      };
      const res = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setStatus("Zapisano. Intercom zostanie zrestartowany.", true);
      } else {
        const err = await res.json().catch(() => ({}));
        setStatus(err.error || "Błąd zapisu", false);
      }
    });

    document.getElementById("reloadEntities").addEventListener("click", () => {
      loadEntities(entitySelect.value).then(() => setStatus("Encje odświeżone.", true));
    });

    document.getElementById("restart").addEventListener("click", async () => {
      const res = await fetch("/api/restart", { method: "POST" });
      setStatus(res.ok ? "Restart zlecony." : "Błąd restartu.", res.ok);
    });

    loadConfig().catch((e) => setStatus(String(e), false));
  </script>
</body>
</html>
"""


class ConfigHttpServer:
    """Serve config UI/API and coordinate restarts."""

    def __init__(
        self,
        store: ConfigStore,
        *,
        ha_client: HomeAssistantClient | None = None,
        restart_watcher: RestartWatcher | None = None,
        port: int = DEFAULT_HTTP_PORT,
        on_config_saved: Callable[[IntercomConfig], None] | None = None,
    ) -> None:
        self._store = store
        self._ha_client = ha_client or HomeAssistantClient(store.config)
        self._restart_watcher = restart_watcher
        self._port = port
        self._on_config_saved = on_config_saved
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._port

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        store = self._store
        ha_client = self._ha_client
        restart_watcher = self._restart_watcher
        on_config_saved = self._on_config_saved

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                del format, args

            def _send_json(
                self, status: HTTPStatus, payload: object
            ) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json_body(self) -> dict[str, object]:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                return data

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                try:
                    if path in ("/", "/index.html"):
                        body = _INDEX_HTML.encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return

                    if path == "/api/config":
                        self._send_json(HTTPStatus.OK, store.config.to_dict())
                        return

                    if path == "/api/sounds":
                        self._send_json(HTTPStatus.OK, list_sound_files())
                        return

                    if path == "/api/entities":
                        ha_client.update_config(store.config)
                        players = ha_client.list_media_players()
                        self._send_json(HTTPStatus.OK, players)
                        return

                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                except requests.RequestException as exc:
                    self._send_json(
                        HTTPStatus.BAD_GATEWAY,
                        {"error": str(exc)},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": str(exc)},
                    )

            def do_PUT(self) -> None:  # noqa: N802
                if urlparse(self.path).path != "/api/config":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                try:
                    data = self._read_json_body()
                    config = IntercomConfig.from_dict(data)
                    store.save(config)
                    ha_client.update_config(config)
                    if restart_watcher is not None:
                        restart_watcher.note_config_saved()
                        restart_watcher.request_restart()
                    if on_config_saved is not None:
                        on_config_saved(config)
                    self._send_json(HTTPStatus.OK, store.config.to_dict())
                except (json.JSONDecodeError, ValueError) as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": str(exc)},
                    )

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path != "/api/restart":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                try:
                    if restart_watcher is not None:
                        restart_watcher.request_restart()
                    self._send_json(HTTPStatus.OK, {"status": "restart_requested"})
                except Exception as exc:  # noqa: BLE001
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": str(exc)},
                    )

        return Handler

    def start(self) -> None:
        if self._httpd is not None:
            return
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(("", self._port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
