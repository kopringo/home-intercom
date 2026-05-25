"""GPIO button gesture detection and action dispatch."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from threading import Lock, Timer
from time import monotonic

from gpiozero import Button

from home_intercom.gpio import is_gpio_available

DEFAULT_BUTTON_PIN = 12
DEFAULT_BOUNCE_TIME = 0.05
DEFAULT_HOLD_DELAY_S = 0.5
DEFAULT_MULTI_PRESS_WINDOW_S = 1.0
# Backwards-compatible alias
DEFAULT_TRIPLE_PRESS_WINDOW_S = DEFAULT_MULTI_PRESS_WINDOW_S


class ButtonAction(Enum):
    """Recognized button gestures."""

    HOLD_START = auto()
    RELEASE = auto()
    DOUBLE_PRESS = auto()
    TRIPLE_PRESS = auto()


ActionCallback = Callable[[], None]


class ButtonHandler:
    """
    Maps physical button events to :class:`ButtonAction` callbacks.

    Register handlers with :meth:`on` before calling :meth:`start`.
    Additional gesture types can be added to :class:`ButtonAction` later.
    """

    def __init__(
        self,
        pin: int = DEFAULT_BUTTON_PIN,
        *,
        pull_up: bool = True,
        bounce_time: float = DEFAULT_BOUNCE_TIME,
        hold_delay_s: float = DEFAULT_HOLD_DELAY_S,
        multi_press_window_s: float = DEFAULT_MULTI_PRESS_WINDOW_S,
        triple_press_window_s: float | None = None,
        gpio_available: bool | None = None,
    ) -> None:
        if triple_press_window_s is not None:
            multi_press_window_s = triple_press_window_s

        if gpio_available is None:
            gpio_available = is_gpio_available()

        self._pin = pin
        self._gpio_available = gpio_available
        self._button = (
            Button(pin, pull_up=pull_up, bounce_time=bounce_time)
            if gpio_available
            else None
        )
        self._hold_delay_s = hold_delay_s
        self._multi_press_window_s = multi_press_window_s
        self._keyboard_pressed = False
        self._lock = Lock()
        self._callbacks: dict[ButtonAction, list[ActionCallback]] = {
            action: [] for action in ButtonAction
        }
        self._hold_timer: Timer | None = None
        self._double_timer: Timer | None = None
        self._press_times: list[float] = []

    @property
    def pin(self) -> int:
        return self._pin

    @property
    def gpio_available(self) -> bool:
        return self._gpio_available

    @property
    def is_pressed(self) -> bool:
        gpio_pressed = self._button.is_pressed if self._button is not None else False
        return gpio_pressed or self._keyboard_pressed

    def simulate_press(self) -> None:
        """Simulate a GPIO press (keyboard debug)."""
        self._keyboard_pressed = True
        self._on_pressed()

    def simulate_release(self) -> None:
        """Simulate a GPIO release (keyboard debug)."""
        self._keyboard_pressed = False
        self._on_released()

    def on(self, action: ButtonAction, callback: ActionCallback) -> None:
        """Register *callback* for *action* (multiple callbacks per action allowed)."""
        self._callbacks[action].append(callback)

    def start(self) -> None:
        """Attach GPIO event handlers (no-op when GPIO is unavailable)."""
        if self._button is None:
            return

        self._button.when_pressed = self._on_pressed
        self._button.when_released = self._on_released

    def _emit(self, action: ButtonAction) -> None:
        for callback in self._callbacks[action]:
            callback()

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _cancel_double_timer(self) -> None:
        if self._double_timer is not None:
            self._double_timer.cancel()
            self._double_timer = None

    def _prune_press_times(self, now: float) -> None:
        self._press_times = [
            t
            for t in self._press_times
            if now - t <= self._multi_press_window_s
        ]

    def _on_hold_timer_fired(self) -> None:
        with self._lock:
            self._hold_timer = None
            if not self.is_pressed:
                return

        self._emit(ButtonAction.HOLD_START)

    def _on_double_timer_fired(self) -> None:
        double_press = False

        with self._lock:
            self._double_timer = None
            now = monotonic()
            self._prune_press_times(now)

            if len(self._press_times) == 2:
                self._press_times = []
                double_press = True

        if double_press:
            self._emit(ButtonAction.DOUBLE_PRESS)

    def _schedule_double_timer(self) -> None:
        self._cancel_double_timer()
        self._double_timer = Timer(
            self._multi_press_window_s,
            self._on_double_timer_fired,
        )
        self._double_timer.start()

    def _on_pressed(self) -> None:
        now = monotonic()
        triple_press = False

        with self._lock:
            self._prune_press_times(now)
            self._press_times.append(now)
            count = len(self._press_times)

            if count >= 3:
                self._cancel_hold_timer()
                self._cancel_double_timer()
                self._press_times = []
                triple_press = True
            elif count == 2:
                self._cancel_hold_timer()
                self._schedule_double_timer()
            else:
                self._cancel_hold_timer()
                self._cancel_double_timer()
                self._hold_timer = Timer(
                    self._hold_delay_s, self._on_hold_timer_fired
                )
                self._hold_timer.start()

        if triple_press:
            self._emit(ButtonAction.TRIPLE_PRESS)

    def _on_released(self) -> None:
        with self._lock:
            self._cancel_hold_timer()

        self._emit(ButtonAction.RELEASE)

    @property
    def multi_press_window_s(self) -> float:
        return self._multi_press_window_s
