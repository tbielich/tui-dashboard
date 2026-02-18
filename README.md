# YouTube Jukebox (Raspberry Pi Kiosk)

Minimalistische Flask-Webapp fuer Touchscreen-Kiosk:
- Suchfeld
- Autosuggest
- Play-Button
- Random-Baseline-Button (Spotify Playlist -> zufaelliger Track -> YouTube)
- Wiedergabe mit `mpv` im Fullscreen
- Immer nur ein aktiver Player

## Dateien

- `app.py`: Flask-App (`/`, `/suggest`, `/play`)
- `jukebox.service`: systemd-Service fuer Flask
- `chromium-kiosk.desktop`: LXDE-Autostart fuer Chromium Kiosk (`http://localhost:5000`)
- `install.sh`: installiert benoetigte Pakete

## 1) Installation auf dem Pi

```bash
cd /home/tui/youtube-jukebox
chmod +x install.sh
./install.sh
```

## 2) Flask-App als Service aktivieren

```bash
sudo cp jukebox.service /etc/systemd/system/jukebox.service
sudo systemctl daemon-reload
sudo systemctl enable --now jukebox.service
sudo systemctl status jukebox.service
```

## 3) Chromium Kiosk Autostart aktivieren

```bash
mkdir -p /home/tui/.config/autostart
cp chromium-kiosk.desktop /home/tui/.config/autostart/
```

Danach einmal neu anmelden oder rebooten.

## 4) Manuell testen

### Web-UI lokal

```bash
python3 app.py
```

Dann im Browser:
- `http://localhost:5000`

### Service Logs

```bash
journalctl -u jukebox.service -f
```

## 5) Bedienung

1. Suchbegriff eingeben
2. Optional Suggestion anklicken/mit Pfeiltasten waehlen
3. `Play` druecken
4. Die App sucht mit `yt-dlp ytsearch1:<query>` und spielt den ersten Treffer
5. Alternativ `Random Baseline` druecken: zufaelliger Titel aus der Spotify-Baseline-Playlist
6. Im Baseline-Modus laeuft nach jedem Video automatisch ein weiteres zufaelliges Baseline-Video
7. Sobald du manuell etwas suchst und `Play` drueckst, endet der Baseline-Durchlauf

## 5a) Baseline Playlist konfigurieren

Standard-Baseline:
- `https://open.spotify.com/playlist/1o6pxgjA5affQmUdRSIVuh`

Optional eigene Baseline per Env:

```bash
BASELINE_SPOTIFY_URL='https://open.spotify.com/playlist/<deine-id>' python3 app.py
```

## 6) Troubleshooting

### Media Keys (Play/Pause/Next/Prev) funktionieren nicht

- Die App unterstuetzt `MediaPlayPause`, `MediaTrackNext`, `MediaTrackPrevious` in der UI.
- Stelle sicher, dass Chromium im Vordergrund ist (aktive Kiosk-Seite).
- In Chromium sollte Hardware Media Key Handling aktiv sein (Standard in aktuellen Versionen).

### Video startet nicht (schwarzer Hintergrund / kein Ton)

- Die App zeigt dann einen Button `Tap to start audio`; einmal tippen.
- Ursache ist meist Browser-Autoplay-Policy (Audio ohne explizite Nutzeraktion blockiert).

### Kein Audio

- Aktiven Sink pruefen:

```bash
pactl list short sinks
```

- Gewuenschten HDMI-Sink setzen:

```bash
pactl set-default-sink <sink-name>
```

### `yt-dlp` fehlt

- `install.sh` erneut ausfuehren
- Falls in `~/.local/bin` installiert, sicherstellen dass PATH dies enthaelt

### Suggest liefert nichts

- UI faellt still auf manuelle Suche zurueck
- Moegliche Ursachen: DNS/Firewall/Rate-Limit auf Suggest-Endpoint

### `mpv` startet nicht

- Pruefen ob GUI-Session vorhanden ist (`DISPLAY=:0`)
- Service-Umgebung (`JUKEBOX_DISPLAY`, `JUKEBOX_UID`) in `jukebox.service` pruefen
