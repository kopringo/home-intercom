"""Intercom application logic."""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path
from threading import Lock

from gpiozero import LED

from home_intercom.button import (
    DEFAULT_BOUNCE_TIME,
    DEFAULT_BUTTON_PIN,
    DEFAULT_HOLD_DELAY_S,
    DEFAULT_TRIPLE_PRESS_WINDOW_S,
    ButtonAction,
    ButtonHandler,
)
from home_intercom.config import DEFAULT_CONFIG_PATH, ConfigStore, IntercomConfig
from home_intercom.home_assistant import HomeAssistantClient
from home_intercom.http_server import DEFAULT_HTTP_PORT, ConfigHttpServer
from home_intercom.keyboard import KeyboardDebug
from home_intercom.recording import AudioRecorder
from home_intercom.restart import RestartWatcher
from home_intercom.sounds import (
    RECORD_PATH,
    find_gong_source,
    find_sound_file,
    make_beep_file,
    play_beep,
    play_wav,
)

DEFAULT_RECORD_LED_PIN = 13


def _resolve_gong_path(config: IntercomConfig) -> Path | None:
    if config.gong_sound:
        try:
            return find_sound_file(config.gong_sound)
        except FileNotFoundError:
            pass
    try:
        return find_gong_source()
    except FileNotFoundError:
        return None


class IntercomApp:
    def __init__(
        self,
        button: ButtonHandler,
        *,
        store: ConfigStore,
        ha_client: HomeAssistantClient,
        record_led_pin: int = DEFAULT_RECORD_LED_PIN,
        alsa_device: str | None = None,
    ) -> None:
        self._store = store
        self._ha = ha_client
        self._button = button
        self._recorder = AudioRecorder(
            alsa_device=alsa_device,
            alert_path=_resolve_gong_path(store.config),
        )
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

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def _ha_playback_ready(self) -> bool:
        config = self._store.config
        return bool(
            config.ha_ip.strip()
            and config.ha_token.strip()
            and config.media_player_entity.strip()
        )

    def _play_via_ha(self) -> None:
        try:
            self._ha.update_config(self._store.config)
            self._ha.play_wav(RECORD_PATH)
        except Exception as exc:  # noqa: BLE001
            print(f"HA playback failed: {exc}, falling back to local speaker")
            play_wav(RECORD_PATH)

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
        if self._ha_playback_ready() and RECORD_PATH.is_file():
            threading.Thread(target=self._play_via_ha, daemon=True).start()
        else:
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

    def run(self, *, keyboard_debug: bool = True, http_port: int | None = None) -> None:
        make_beep_file()
        gong = _resolve_gong_path(self._store.config)
        if gong is None:
            print(
                f"Warning: gong sound {self._store.config.gong_sound!r} not found"
            )
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

        if http_port is not None:
            print(f"Config UI: http://0.0.0.0:{http_port}/")

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
        self.request_shutdown()

    def _request_quit(self) -> None:
        self.request_shutdown()


def run(
    *,
    button_pin: int = DEFAULT_BUTTON_PIN,
    bounce_time: float = DEFAULT_BOUNCE_TIME,
    hold_delay_s: float = DEFAULT_HOLD_DELAY_S,
    triple_press_window_s: float = DEFAULT_TRIPLE_PRESS_WINDOW_S,
    record_led_pin: int = DEFAULT_RECORD_LED_PIN,
    alsa_device: str | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    http_port: int = DEFAULT_HTTP_PORT,
    enable_http: bool = True,
    keyboard_debug: bool = True,
) -> None:
    """Build the app, serve config UI, and restart on config changes."""
    while True:
        store = ConfigStore(config_path)
        if not config_path.is_file():
            store.save()

        restart_requested = threading.Event()
        button = ButtonHandler(
            pin=button_pin,
            bounce_time=bounce_time,
            hold_delay_s=hold_delay_s,
            triple_press_window_s=triple_press_window_s,
        )
        ha_client = HomeAssistantClient(store.config)
        app = IntercomApp(
            button,
            store=store,
            ha_client=ha_client,
            record_led_pin=record_led_pin,
            alsa_device=alsa_device,
        )

        def on_restart() -> None:
            restart_requested.set()
            app.request_shutdown()

        watcher = RestartWatcher(config_path, on_restart)
        http_server: ConfigHttpServer | None = None
        if enable_http:
            http_server = ConfigHttpServer(
                store,
                ha_client=ha_client,
                restart_watcher=watcher,
                port=http_port,
            )
            http_server.start()
        watcher.start()

        try:
            app.run(
                keyboard_debug=keyboard_debug,
                http_port=http_port if enable_http else None,
            )
        finally:
            watcher.stop()
            if http_server is not None:
                http_server.stop()

        if restart_requested.is_set():
            os.execv(sys.executable, [sys.executable, *sys.argv])
        return
