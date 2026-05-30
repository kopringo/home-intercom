"""Restart signalling via marker file and config mtime watch."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable


class RestartWatcher:
    """Detect restart requests and external config edits.

    Two triggers:

    1. Marker file ``<config>.restart`` — written by :meth:`request_restart`
       (HTTP ``POST /api/restart`` or after saving config in-process).
    2. Config file mtime newer than the baseline — e.g. manual ``vi`` edit.
    """

    def __init__(
        self,
        config_path: Path,
        on_restart: Callable[[], None],
        *,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._config_path = config_path
        self._marker_path = config_path.with_suffix(config_path.suffix + ".restart")
        self._on_restart = on_restart
        self._poll_interval_s = poll_interval_s
        self._baseline_mtime = self._current_mtime()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def marker_path(self) -> Path:
        return self._marker_path

    def _current_mtime(self) -> float:
        if self._config_path.is_file():
            return self._config_path.stat().st_mtime
        return 0.0

    def note_config_saved(self) -> None:
        """Call after the app itself writes config (updates mtime baseline)."""
        self._baseline_mtime = self._current_mtime()

    def request_restart(self) -> None:
        """Touch the marker file; :meth:`start` loop will invoke the callback."""
        self._marker_path.parent.mkdir(parents=True, exist_ok=True)
        self._marker_path.touch()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_s + 1)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._marker_path.is_file():
                self._marker_path.unlink(missing_ok=True)
                self._on_restart()
                return

            mtime = self._current_mtime()
            if mtime > self._baseline_mtime + 0.001:
                self._on_restart()
                return

            self._stop.wait(self._poll_interval_s)
