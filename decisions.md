# decisions.md

Date: 2026-02-18
Target host: `tui@10.146.105.62` (Raspberry Pi, LXDE)

## 1. Connectivity and SSH hardening

- `nmap` was installed locally on the admin machine to run the requested scans.
- Initial state: Pi host up, selected ports filtered.
- After SSH enablement on Pi, TCP/22 became reachable.
- SSH key auth configured for user `tui` with existing key `~/.ssh/id_ed25519_pi`.
- SSH hardening applied in `/etc/ssh/sshd_config`:
  - `PermitRootLogin no`
  - `PubkeyAuthentication yes`
  - `PasswordAuthentication no`
  - `KbdInteractiveAuthentication no`
- Config validated with `sshd -t`, then `systemctl reload ssh`.
- Verification:
  - Key login works.
  - Password login is disabled (`Permission denied (publickey)`).

## 2. Firewall (UFW)

- `ufw` installed on Pi.
- Rules configured:
  - Default incoming: deny
  - Default outgoing: allow
  - Allow `OpenSSH` (`22/tcp`)
- Firewall enabled at boot.
- Verification from client:
  - Port 22 reachable.
  - Ports `80,443,8080,3000,5000,631,1880` timed out/blocked.

## 3. Desktop wallpapers (dual HDMI)

Monitor mapping (`xrandr`):
- Index 0: `HDMI-1` (primary)
- Index 1: `HDMI-2`

Wallpaper files on Pi:
- `/home/tui/Pictures/wallpapers/code-cat.png`
- `/home/tui/Pictures/wallpapers/smiling-robbe.png`

Configured wallpapers:
- `HDMI-1` (`desktop-items-0.conf`): `code-cat.png`
- `HDMI-2` (`desktop-items-1.conf`): `smiling-robbe.png`

Config files:
- `/home/tui/.config/pcmanfm/LXDE-pi/desktop-items-0.conf`
- `/home/tui/.config/pcmanfm/LXDE-pi/desktop-items-1.conf`

## 4. Chromium launch behavior

- Chromium launched on `HDMI-1` with window geometry `1920x1080` at position `0,0`.
- Kibana URL restored from browser history and opened:
  - `https://kibana.tui-deutschland.plusline.de:8443/app/dashboards#/view/f49f4000-2459-11ed-8b46-b5ae34236f72?_g=h@e7178c8`
- Chromium was switched to kiosk startup on HDMI-1 (fullscreen, no browser UI/chrome).

Autostart configured for user session:
- Script: `/home/tui/bin/start-chromium-hdmi1.sh`
- LXDE autostart file: `/home/tui/.config/lxsession/LXDE-pi/autostart`
- Autostart entry includes opening Chromium on HDMI-1 with the Kibana URL in kiosk mode (`--kiosk --start-fullscreen`).

## 5. Power schedule decisions

- Requested plan "boot 08:00, shutdown 18:00" evaluated.
- Result: automatic power-on at 08:00 is not possible in current hardware/software state because no RTC device is present (`/dev/rtc*` missing, RTC time n/a).
- Temporary daily shutdown timer was created, then removed on request.
- Final state:
  - No daily shutdown timer present.
  - Pi should run continuously.
  - Regular reboot configured to clear runtime state/cache.

Regular reboot setup:
- Service: `/etc/systemd/system/daily-reboot.service`
- Timer: `/etc/systemd/system/daily-reboot.timer`
- Schedule: daily `04:00` (local time, Europe/Berlin)
- Timer enabled and active.

## 6. Current intended operating mode

- Pi stays on continuously.
- Reboots automatically once per day at 04:00.
- On desktop session start, Chromium opens on HDMI-1 with Kibana.
- SSH access is key-only and hardened.
- Firewall allows SSH only unless additional ports are explicitly opened.

## 7. Jukebox setup and rollback decisions (2026-02-19)

- Local repository (`main`) now contains Jukebox app and deployment files:
  - `app.py`
  - `install.sh`
  - `jukebox.service`
  - `chromium-kiosk.desktop`
  - `README.md`
- Pi deployment path: `/home/tui/youtube-jukebox`.

Autostart decision:
- HDMI-2 Jukebox autostart was stopped/removed on request.
- Active LXDE autostart remains focused on HDMI-1 dashboard startup.

Service/runtime decisions:
- `jukebox.service` is installed as system service (`/etc/systemd/system/jukebox.service`).
- Flask app serves on `http://0.0.0.0:5000`.
- Dependency installation is done via `install.sh` (incl. `yt-dlp` user install in `~/.local/bin`).

## 8. Video playback fix on Pi (403 stream issue)

Observed issue:
- `/play` succeeded, but `/stream/current` returned `403` for YouTube stream URLs.

Diagnosis:
- Direct browser fetch of yt-dlp-resolved URL failed with default/web client.
- Test with yt-dlp extractor arg `youtube:player_client=android` returned `200`.

Implemented fix:
- In `app.py`, browser stream resolution now uses:
  - `--extractor-args youtube:player_client=android`
- Repo commit:
  - `2969b8c` (`fix: use android player client for browser stream`)

Verification after deploy on Pi:
- Pi repo hard-synced to `origin/main` (`git reset --hard origin/main`).
- `jukebox.service` restarted successfully.
- Stream endpoint now responds with partial content:
  - `GET /stream/current` -> `206 Partial Content` (`video/mp4`)
- Chromium Jukebox launched manually on HDMI-2 for test:
  - `--app=http://localhost:5000`
  - `--window-position=1920,0`
  - `--user-data-dir=/home/tui/.config/chromium-hdmi2`

## 9. Jukebox startup behavior (baseline random by default)

Decision:
- Jukebox should always start with a random baseline video when the page opens and no active stream is present.

Implementation:
- Added env-controlled flag in `app.py`:
  - `AUTO_START_BASELINE` (default `true`)
- Added JSON route:
  - `POST /play-baseline-json`
  - Starts baseline mode and returns current stream metadata for frontend startup.
- Frontend startup logic now triggers this route automatically if idle.

Verification on Pi:
- After `jukebox.service` restart and opening `http://localhost:5000` in Chromium:
  - `GET /` seen in logs
  - automatic `POST /play-baseline-json` seen in logs
  - then `GET /stream/current?...` returns `206`
- This confirms random baseline autostarts without manual button press.
