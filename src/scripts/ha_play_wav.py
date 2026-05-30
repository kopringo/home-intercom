#!/usr/bin/env python3
import argparse
import http.server
import json
import os
import socket
import socketserver
import threading
import time
from pathlib import Path

import requests

PLAY_MEDIA_FEATURE = 512


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def ha_get(base, token, path):
    r = requests.get(
        f"{base}/api{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def ha_post(base, token, path, payload):
    r = requests.post(
        f"{base}/api{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=10,
    )
    r.raise_for_status()
    return r.json() if r.text else None


def list_players(base, token):
    states = ha_get(base, token, "/states")
    players = []

    for s in states:
        entity_id = s.get("entity_id", "")
        if not entity_id.startswith("media_player."):
            continue

        attrs = s.get("attributes", {})
        supported = attrs.get("supported_features", 0) or 0
        can_play_media = bool(supported & PLAY_MEDIA_FEATURE)

        players.append({
            "entity_id": entity_id,
            "name": attrs.get("friendly_name", entity_id),
            "state": s.get("state"),
            "can_play_media": can_play_media,
            "supported_features": supported,
        })

    return players


def serve_file(path, port):
    file_path = Path(path).resolve()
    directory = str(file_path.parent)
    filename = file_path.name

    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, p):
            return str(Path(directory) / filename)

        def log_message(self, *args):
            pass

    httpd = socketserver.TCPServer(("", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ha", required=True, help="np. http://192.168.1.10:8123")
    parser.add_argument("--token", required=True)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--entity")
    parser.add_argument("--wav")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host-ip", help="IP komputera ze skryptem, widoczne dla głośnika")
    parser.add_argument("--content-type", default="music")
    args = parser.parse_args()

    base = args.ha.rstrip("/")

    if args.list:
        players = list_players(base, args.token)
        for i, p in enumerate(players, 1):
            mark = "OK" if p["can_play_media"] else "?"
            print(f"{i:2}. [{mark}] {p['entity_id']} | {p['name']} | state={p['state']}")
        return

    if not args.entity or not args.wav:
        parser.error("Do odtwarzania podaj --entity i --wav albo użyj --list")

    wav_path = Path(args.wav)
    if not wav_path.exists():
        raise SystemExit(f"Nie ma pliku: {wav_path}")

    host_ip = args.host_ip or local_ip()
    httpd = serve_file(wav_path, args.port)
    url = f"http://{host_ip}:{args.port}/{wav_path.name}"

    print(f"Udostępniam WAV pod: {url}")
    print(f"Wysyłam do: {args.entity}")

    ha_post(base, args.token, "/services/media_player/play_media", {
        "entity_id": args.entity,
        "media_content_id": url,
        "media_content_type": args.content_type,
    })

    time.sleep(3)
    httpd.shutdown()


if __name__ == "__main__":
    main()