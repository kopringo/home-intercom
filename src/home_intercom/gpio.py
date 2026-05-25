"""GPIO availability detection."""

from __future__ import annotations

import warnings


def is_gpio_available() -> bool:
    """
    Return True when gpiozero can use a real pin factory (typically on a Pi).

    Checks the pin factory only — does not open any pins.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            from gpiozero import Device

            Device._default_pin_factory()
            return True
        except Exception:
            return False
