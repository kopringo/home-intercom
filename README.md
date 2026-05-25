# home-intercom

Software for a **Raspberry Pi Zero 2 W** with a **ReSpeaker 1.1** (Seeed 2-Mic Pi HAT), turning the device into a home intercom.

Repository: [https://github.com/kopringo/home-intercom](https://github.com/kopringo/home-intercom)

## Hardware

- Raspberry Pi Zero 2 W
- ReSpeaker 1.1 (Seeed)

## Quick start

### 1. Flash the OS (latest image)

On your PC, use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) with the **PiCompose** image catalog so you get the newest compatible system:

```bash
./imager_2.0.7_amd64.AppImage --repo https://github.com/florian-asche/PiCompose/releases/download/rpi-imager-json/rpi-imager.json
```

Select the latest Raspberry Pi OS image for your board, write it to the SD card, and boot the Pi.

> **Linux tip:** If the AppImage fails to render the UI, try:
> `sudo QT_QUICK_BACKEND=software ./imager_2.0.7_amd64.AppImage --repo ...` (see [NOTES.md](NOTES.md) for ReSpeaker overlay setup and other dev notes).

### 2. Clone this repository

On the Raspberry Pi:

```bash
git clone https://github.com/kopringo/home-intercom.git
cd home-intercom
```

### 3. Install the application

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run the daemon (requires GPIO access on the Pi):

```bash
home-intercom run
```

Or use `install.sh` (when available) to register a **systemd** service for boot-time startup.

Check status:

```bash
sudo systemctl status home-intercom
```

## Development notes

Extra setup (device tree overlay for the ReSpeaker HAT, build steps, etc.) is documented in [NOTES.md](NOTES.md).

## License

MIT — see [LICENSE](LICENSE).
