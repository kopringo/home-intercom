"""Command-line interface."""

from __future__ import annotations

import argparse
import sys

from home_intercom import __version__
from home_intercom.button import (
    DEFAULT_BOUNCE_TIME,
    DEFAULT_BUTTON_PIN,
    DEFAULT_HOLD_DELAY_S,
    DEFAULT_TRIPLE_PRESS_WINDOW_S,
)
from home_intercom.core import DEFAULT_RECORD_LED_PIN


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="home-intercom",
        description="Home intercom daemon for Raspberry Pi + ReSpeaker",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    subparsers.required = True

    run_parser = subparsers.add_parser(
        "run",
        help="Start the intercom (GPIO button + LED, block until exit)",
    )
    run_parser.add_argument(
        "--button-pin",
        type=int,
        default=DEFAULT_BUTTON_PIN,
        metavar="GPIO",
        help=f"Button GPIO pin (default: {DEFAULT_BUTTON_PIN})",
    )
    run_parser.add_argument(
        "--record-led-pin",
        type=int,
        default=DEFAULT_RECORD_LED_PIN,
        metavar="GPIO",
        help=f"Recording LED GPIO pin (default: {DEFAULT_RECORD_LED_PIN})",
    )
    run_parser.add_argument(
        "--hold-delay",
        type=float,
        default=DEFAULT_HOLD_DELAY_S,
        metavar="SEC",
        help=f"Hold time before recording starts (default: {DEFAULT_HOLD_DELAY_S})",
    )
    run_parser.add_argument(
        "--triple-press-window",
        type=float,
        default=DEFAULT_TRIPLE_PRESS_WINDOW_S,
        metavar="SEC",
        help=(
            "Max interval between presses for double/triple-press gestures "
            f"(default: {DEFAULT_TRIPLE_PRESS_WINDOW_S})"
        ),
    )
    run_parser.add_argument(
        "--bounce-time",
        type=float,
        default=DEFAULT_BOUNCE_TIME,
        metavar="SEC",
        help=f"Button debounce time (default: {DEFAULT_BOUNCE_TIME})",
    )
    run_parser.add_argument(
        "--no-keyboard-debug",
        action="store_true",
        help="Disable keyboard [b]/[q] debug input on a TTY",
    )
    run_parser.add_argument(
        "--alsa-device",
        metavar="NAME",
        default=None,
        help="ALSA device for arecord/aplay (e.g. plughw:1,0)",
    )
    run_parser.set_defaults(func=_cmd_run)

    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    from home_intercom.button import ButtonHandler
    from home_intercom.core import IntercomApp

    button = ButtonHandler(
        pin=args.button_pin,
        bounce_time=args.bounce_time,
        hold_delay_s=args.hold_delay,
        triple_press_window_s=args.triple_press_window,
    )
    IntercomApp(
        button,
        record_led_pin=args.record_led_pin,
        alsa_device=args.alsa_device,
    ).run(keyboard_debug=not args.no_keyboard_debug)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
