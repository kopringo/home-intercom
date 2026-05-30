"""Microphone capture via ALSA ``arecord``."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

from home_intercom.sounds import RECORD_PATH, build_record_file, gong_path, wav_format

MESSAGE_RAW_PATH = Path("/tmp/message_raw.wav")

_ARECORD_FORMAT = {
    1: "U8",
    2: "S16_LE",
    3: "S24_LE",
    4: "S32_LE",
}


class AudioRecorder:
    def __init__(self, *, alsa_device: str | None = None, alert_path: Path | None = None) -> None:
        self._alsa_device = alsa_device
        self._alert_path = alert_path
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def is_capturing(self) -> bool:
        return self._process is not None

    def start(self) -> bool:
        if self._process is not None:
            return True

        if shutil.which("arecord") is None:
            print("Recording failed: arecord not found (install alsa-utils)")
            return False

        try:
            alert = self._alert_path if self._alert_path is not None else gong_path()
        except FileNotFoundError as exc:
            print(f"Recording failed: {exc}")
            return False

        MESSAGE_RAW_PATH.unlink(missing_ok=True)

        try:
            sample_rate, channels, sample_width = wav_format(alert)
            sample_format = _ARECORD_FORMAT.get(sample_width)
            if sample_format is None:
                print(f"Recording failed: unsupported WAV sample width {sample_width}")
                return False
        except (OSError, wave.Error) as exc:
            print(f"Recording failed: cannot read alert format: {exc}")
            return False

        cmd = ["arecord"]
        if self._alsa_device:
            cmd.extend(["-D", self._alsa_device])
        cmd.extend(
            [
                "-q",
                "-f",
                sample_format,
                "-r",
                str(sample_rate),
                "-c",
                str(channels),
                str(MESSAGE_RAW_PATH),
            ]
        )

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            print(f"Recording failed: {exc}")
            self._process = None
            return False

        return True

    def stop_and_finalize(self) -> bool:
        """Stop capture and write ``/tmp/record.wav`` (alert + pause + message)."""
        if self._process is None:
            return False

        self._process.terminate()
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=1)

        self._process = None

        if not MESSAGE_RAW_PATH.is_file():
            print("Recording failed: no audio captured")
            return False

        try:
            build_record_file(message_path=MESSAGE_RAW_PATH, output_path=RECORD_PATH)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Recording failed: {exc}")
            return False

        return True

    @staticmethod
    def erase() -> None:
        RECORD_PATH.unlink(missing_ok=True)
        MESSAGE_RAW_PATH.unlink(missing_ok=True)
