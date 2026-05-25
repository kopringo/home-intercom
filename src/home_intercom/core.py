"""Intercom application logic."""

from __future__ import annotations

import signal
import threading
from threading import Lock

from gpiozero import LED

from home_intercom.button import (
    DEFAULT_BUTTON_PIN,
    ButtonAction,
    ButtonHandler,
)
from home_intercom.keyboard import KeyboardDebug
from home_intercom.recording import AudioRecorder
from home_intercom.sounds import (
    RECORD_PATH,
    find_gong_source,
    make_beep_file,
    play_beep,
    play_wav,
)

DEFAULT_RECORD_LED_PIN = 13


class IntercomApp:
    def __init__(
        self,
        button: ButtonHandler,
        *,
        record_led_pin: int = DEFAULT_RECORD_LED_PIN,
        alsa_device: str | None = None,
    ) -> None:
        self._button = button
        self._recorder = AudioRecorder(alsa_device=alsa_device)
        self._gpio_available = button.gpio_available
        self._record_led = (
            LED(record_led_pin) if self._gpio_available else None
        )
        self._lock = Lock()
        self._recording = False
        self._shutdown = threading.Event()

        button.on(ButtonAction.HOLD_START, self._start_recording)
        button.on(ButtonAction.RELEASE, self._stop_recording)
        button.on(ButtonAction.DOUBLE_PRESS, self._on_double_press)
        button.on(ButtonAction.TRIPLE_PRESS, self._on_triple_press)

    def _start_recording(self) -> None:
        with self._lock:
            if not self._button.is_pressed:
                return
            if self._recording:
                return
            self._recording = True

        if not self._recording_started():
            with self._lock:
                self._recording = False

    def _recording_started(self) -> bool:
        if not self._recorder.start():
            return False

        if self._record_led is not None:
            self._record_led.on()
        print("Recording start")
        return True

    def _finalize_recording(self) -> None:
        if self._record_led is not None:
            self._record_led.off()

        if self._recorder.stop_and_finalize():
            print(f"Saved {RECORD_PATH}")
        else:
            print("Recording stop")

    def _stop_recording(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = False

        self._finalize_recording()

    def _on_double_press(self) -> None:
        print("Playback")
        play_wav(RECORD_PATH)

    def _toggle_recording_keyboard(self) -> None:
        with self._lock:
            if self._recording:
                self._recording = False
                stopping = True
            else:
                self._recording = True
                stopping = False

        if stopping:
            self._finalize_recording()
        elif not self._recording_started():
            with self._lock:
                self._recording = False

    def _on_triple_press(self) -> None:
        with self._lock:
            was_recording = self._recording

        if was_recording:
            self._stop_recording()

        self._recorder.erase()
        play_beep()
        print("Erase")

    def run(self, *, keyboard_debug: bool = True) -> None:
        make_beep_file()
        try:
            find_gong_source()
        except FileNotFoundError as exc:
            print(f"Warning: {exc}")
        self._button.start()

        keyboard_listener: KeyboardDebug | None = None
        keyboard_active = False
        if keyboard_debug:
            keyboard_listener = KeyboardDebug(
                on_toggle_record=self._toggle_recording_keyboard,
                on_double_press=self._on_double_press,
                on_triple_press=self._on_triple_press,
                on_quit=self._request_quit,
            )
            keyboard_active = keyboard_listener.start()

        pin = self._button.pin
        if not self._gpio_available:
            print("GPIO unavailable — physical button and LED will not work.")

        if keyboard_active:
            keys_hint = "[r] record toggle, [p] double, [c] erase, [q] quit"

            if self._gpio_available:
                print(
                    f"Waiting for button (GPIO {pin}, hold to record) or "
                    f"keyboard debug ({keys_hint})"
                )
            else:
                print(f"Waiting for keyboard debug ({keys_hint})")
        elif self._gpio_available:
            print(f"Waiting for button press (GPIO {pin})")
        else:
            print(
                "No GPIO and no keyboard debug — run from a terminal "
                "(TTY) or on a Raspberry Pi with a button wired to GPIO."
            )

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        try:
            self._shutdown.wait()
        finally:
            with self._lock:
                if self._recording:
                    self._recording = False
                    self._recorder.stop_and_finalize()
            if keyboard_listener is not None:
                keyboard_listener.stop()
            print("Exit")

    def _handle_signal(self, signum: int, frame: object | None) -> None:
        self._shutdown.set()

    def _request_quit(self) -> None:
        self._shutdown.set()


def run(
    *,
    button_pin: int = DEFAULT_BUTTON_PIN,
    record_led_pin: int = DEFAULT_RECORD_LED_PIN,
    alsa_device: str | None = None,
) -> None:
    """Build the app and block until interrupted."""
    button = ButtonHandler(pin=button_pin)
    IntercomApp(
        button,
        record_led_pin=record_led_pin,
        alsa_device=alsa_device,
    ).run()
