"""Sound generation and playback."""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2

DEFAULT_BEEP_PATH = Path("/tmp/kasowanie_beep.wav")
RECORD_PATH = Path("/tmp/record.wav")
GONG_FILENAME = "gongi.wav"

BEEP_DURATION_S = 0.15
BEEP_FREQUENCY_HZ = 1000
BEEP_VOLUME = 0.4

RECORD_SILENCE_S = 0.5


def _tone_pcm(
    frequency_hz: float,
    duration_s: float,
    *,
    volume: float = 0.5,
    attack_s: float = 0.015,
    release_s: float = 0.04,
) -> bytes:
    frames = int(SAMPLE_RATE * duration_s)
    attack = max(1, int(SAMPLE_RATE * attack_s))
    release = max(1, int(SAMPLE_RATE * release_s))
    chunks: list[bytes] = []

    for i in range(frames):
        env = 1.0
        if i < attack:
            env = i / attack
        elif i > frames - release:
            env = max(0.0, (frames - i) / release)

        sample = int(
            32767
            * volume
            * env
            * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE)
        )
        chunks.append(struct.pack("<h", sample))

    return b"".join(chunks)


def _write_mono_wav(path: Path, pcm: bytes) -> Path:
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return path



def _gong_source_candidates() -> tuple[Path, ...]:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent.parent
    return (
        project_root / "sounds" / GONG_FILENAME,
        project_root / "src" / "home_intercom" / "sounds" / GONG_FILENAME,
        package_dir / GONG_FILENAME,
    )


def find_gong_source() -> Path:
    for path in _gong_source_candidates():
        if path.is_file():
            return path
    locations = ", ".join(str(path) for path in _gong_source_candidates())
    raise FileNotFoundError(
        f"{GONG_FILENAME} not found. Place it in one of: {locations}"
    )


def gong_path() -> Path:
    """Resolved path to ``gongi.wav`` (used in place, never copied)."""
    return find_gong_source()


def wav_format(path: Path) -> tuple[int, int, int]:
    """Return ``(sample_rate, channels, sample_width_bytes)`` from a WAV file."""
    with wave.open(str(path), "rb") as wav:
        return wav.getframerate(), wav.getnchannels(), wav.getsampwidth()


def make_beep_file(path: Path = DEFAULT_BEEP_PATH) -> Path:
    """Short single beep (erase feedback)."""
    return _write_mono_wav(path, _tone_pcm(BEEP_FREQUENCY_HZ, BEEP_DURATION_S, volume=BEEP_VOLUME))


def build_record_file(
    *,
    alert_path: Path | None = None,
    message_path: Path,
    output_path: Path = RECORD_PATH,
    silence_s: float = RECORD_SILENCE_S,
) -> Path:
    """``output`` = gong + silence + message (via ``sox``)."""
    if alert_path is None:
        alert_path = gong_path()

    sox = shutil.which("sox")
    if sox is None:
        raise RuntimeError("sox is required to build record.wav (install sox)")

    padded_path = output_path.parent / "_alert_padded.wav"
    try:
        subprocess.run(
            [sox, str(alert_path), str(padded_path), "pad", str(silence_s)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [sox, str(padded_path), str(message_path), str(output_path)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"sox failed to build {output_path}: {exc.stderr.decode(errors='replace')}"
        ) from exc
    finally:
        padded_path.unlink(missing_ok=True)

    return output_path


def play_wav(path: Path) -> None:
    """Play *path* asynchronously via ALSA (``aplay``)."""
    if not path.is_file():
        print(f"Playback skipped: {path} not found")
        return

    subprocess.Popen(
        ["aplay", "-q", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def play_beep(path: Path = DEFAULT_BEEP_PATH) -> None:
    play_wav(path)


def delete_record_files(
    *,
    record_path: Path = RECORD_PATH,
    message_path: Path | None = None,
) -> None:
    record_path.unlink(missing_ok=True)
    if message_path is not None:
        message_path.unlink(missing_ok=True)
