"""Keyboard debug via the terminal (stdin) — no extra permissions."""

from __future__ import annotations

import select
import sys
import termios
import threading
import tty
from collections.abc import Callable
from typing import Any

OnQuitCallback = Callable[[], None]
OnToggleRecordCallback = Callable[[], None]
OnDoublePressCallback = Callable[[], None]
OnTriplePressCallback = Callable[[], None]


class KeyboardDebug:
    """
    Console shortcuts (TTY stdin):

    * ``r`` — toggle recording (start / stop)
    * ``p`` — double-press action
    * ``c`` — triple-press action (erase)
    * ``q`` — quit
    """

    def __init__(
        self,
        *,
        on_toggle_record: OnToggleRecordCallback,
        on_double_press: OnDoublePressCallback,
        on_triple_press: OnTriplePressCallback,
        on_quit: OnQuitCallback,
    ) -> None:
        self._on_toggle_record = on_toggle_record
        self._on_double_press = on_double_press
        self._on_triple_press = on_triple_press
        self._on_quit = on_quit
        self._thread: threading.Thread | None = None
        self._running = False
        self._fd = sys.stdin.fileno()
        self._old_term: Any = None

    def start(self) -> bool:
        if not sys.stdin.isatty():
            print(
                "Keyboard debug: stdin is not a TTY "
                "(run from a terminal, not a pipe or service without console)"
            )
            return False

        self._old_term = termios.tcgetattr(self._fd)
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="keyboard-stdin",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        self._restore_terminal()

    def _restore_terminal(self) -> None:
        if self._old_term is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_term)
            self._old_term = None

    def _run(self) -> None:
        assert self._old_term is not None
        tty.setcbreak(self._fd)
        try:
            while self._running:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not ready:
                    continue

                ch = sys.stdin.read(1).lower()
                if ch == "r":
                    self._on_toggle_record()
                elif ch == "p":
                    self._on_double_press()
                elif ch == "c":
                    self._on_triple_press()
                elif ch == "q":
                    self._on_quit()
                    break
        finally:
            self._restore_terminal()
