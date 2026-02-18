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
