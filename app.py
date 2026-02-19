import atexit
import base64
import json
import os
import random
import re
import signal
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from contextlib import suppress

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    stream_with_context,
    url_for,
)

app = Flask(__name__)

PLAYER_LOCK = threading.Lock()
PLAYER_PROCESS = None
PID_FILE = "/tmp/jukebox_mpv.pid"
STATE_LOCK = threading.Lock()
CURRENT_VIDEO = {
    "id": "",
    "title": "",
    "embed_url": "",
    "stream_url": "",
    "stream_headers": {},
    "stream_revision": "",
    "mode": "",
    "query": "",
}
PLAYBACK_MODE = os.environ.get("PLAYBACK_MODE", "browser").strip().lower()
BASELINE_SPOTIFY_URL = os.environ.get(
    "BASELINE_SPOTIFY_URL",
    "https://open.spotify.com/playlist/1o6pxgjA5affQmUdRSIVuh",
).strip()
BASELINE_CACHE = {
    "url": "",
    "loaded_at": 0.0,
    "tracks": [],
}
BASELINE_TTL_SECONDS = 900
BASELINE_SESSION = {
    "enabled": False,
    "tracks": [],
    "remaining": [],
}

INDEX_TEMPLATE = """
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>YouTube Jukebox</title>
  <style>
    :root {
      --bg: #0b0d11;
      --panel: rgba(10, 13, 18, 0.82);
      --text: #f2f4f8;
      --muted: #a3adba;
      --accent: #ff3b30;
      --accent-2: #ff645f;
      --border: rgba(255, 255, 255, 0.18);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100dvh;
      overflow: hidden;
    }
    .bg {
      position: fixed;
      inset: 0;
      z-index: 0;
      background: #090c10;
    }
    .bg iframe {
      width: 100%;
      height: 100%;
      border: 0;
      pointer-events: none;
      transform: scale(1.04);
      transform-origin: center center;
    }
    .bg video {
      width: 100%;
      height: 100%;
      border: 0;
      pointer-events: none;
      object-fit: cover;
      transform: scale(1.04);
      transform-origin: center center;
    }
    .bg::after {
      content: "";
      position: absolute;
      inset: 0;
      background: radial-gradient(150% 90% at 50% 10%, rgba(0,0,0,0.16), rgba(0,0,0,0.72));
    }
    .start-overlay {
      position: fixed;
      inset: 0;
      z-index: 3;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.45);
    }
    .start-overlay.show { display: flex; }
    .start-btn {
      min-height: 76px;
      border: 0;
      border-radius: 16px;
      padding: 0 28px;
      background: linear-gradient(180deg, #ff645f, #ff3b30);
      color: #fff;
      font-size: clamp(1.15rem, 2.8vw, 1.4rem);
      font-weight: 700;
      cursor: pointer;
    }
    .shell {
      position: fixed;
      bottom: 2rem;
      left: 50%;
      transform: translateX(-50%);
      width: min(1100px, calc(100% - 24px));
      z-index: 2;
    }
    .notice-stack {
      position: fixed;
      top: 2rem;
      left: 50%;
      transform: translateX(-50%);
      width: min(860px, calc(100% - 24px));
      z-index: 4;
      pointer-events: none;
    }
    .loading-bar {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 0.5rem;
      z-index: 6;
      opacity: 0;
      pointer-events: none;
      background: rgba(255, 0, 0, 0.25);
      transition: opacity 120ms ease;
      overflow: hidden;
    }
    .loading-bar::before {
      content: "";
      position: absolute;
      top: 0;
      left: -35%;
      width: 35%;
      height: 100%;
      background: #ff0000;
      animation: loading-slide 900ms linear infinite;
    }
    .loading-bar.show {
      opacity: 1;
    }
    .brand-logo {
      position: fixed;
      top: 1rem;
      right: 1rem;
      width: clamp(64px, 8vw, 110px);
      height: auto;
      z-index: 7;
      pointer-events: none;
      filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.35));
    }
    @keyframes loading-slide {
      0% { left: -35%; }
      100% { left: 100%; }
    }
    .wrap {
      width: 100%;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.35);
      backdrop-filter: blur(8px);
    }
    .msg {
      margin: 0 0 10px;
      padding: 10px 12px;
      border-radius: 12px;
      font-size: 0.98rem;
      backdrop-filter: blur(8px);
      box-shadow: 0 8px 18px rgba(0, 0, 0, 0.25);
      transition: opacity 260ms ease, transform 260ms ease;
    }
    .msg.error { background: rgba(255, 59, 48, 0.15); border: 1px solid rgba(255, 59, 48, 0.45); }
    .msg.status { background: rgba(0, 204, 102, 0.15); border: 1px solid rgba(0, 204, 102, 0.4); }
    .msg.fade-out {
      opacity: 0;
      transform: translateY(-8px);
    }
    form { position: relative; }
    .row {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 8px;
      align-items: stretch;
    }
    input[type=text] {
      width: 100%;
      min-height: 70px;
      border-radius: 16px;
      border: 2px solid rgba(255, 255, 255, 0.22);
      background: rgba(10, 14, 19, 0.92);
      color: var(--text);
      padding: 16px 18px;
      font-size: clamp(1.2rem, 2.8vw, 1.7rem);
      outline: none;
    }
    input[type=text]:focus {
      border-color: var(--accent-2);
      box-shadow: 0 0 0 3px rgba(255, 100, 95, 0.2);
    }
    button {
      min-height: 70px;
      border: 0;
      border-radius: 16px;
      padding: 0 36px;
      background: linear-gradient(180deg, var(--accent-2), var(--accent));
      color: white;
      font-size: clamp(1.2rem, 2.6vw, 1.45rem);
      font-weight: 700;
      cursor: pointer;
    }
    button:active { transform: translateY(1px); }
    button.secondary {
      background: linear-gradient(180deg, #3f4a5d, #2f3848);
    }
    .suggest {
      position: absolute;
      bottom: 78px;
      top: auto;
      left: 0;
      right: 320px;
      max-height: min(55vh, 480px);
      overflow: auto;
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.18);
      background: rgba(11, 16, 22, 0.95);
      z-index: 10;
      display: none;
    }
    .suggest.open { display: block; }
    .item {
      padding: 14px 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      font-size: clamp(1.12rem, 2.2vw, 1.28rem);
      line-height: 1.2;
      cursor: pointer;
      user-select: none;
    }
    .item:last-child { border-bottom: 0; }
    .item.active, .item:hover { background: rgba(255, 255, 255, 0.12); }
    @media (max-width: 700px) {
      .row { grid-template-columns: 1fr; }
      .suggest { right: 0; bottom: 150px; top: auto; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <div id="loading-bar" class="loading-bar" aria-hidden="true"></div>
  <img class="brand-logo" src="{{ url_for('static', filename='MTUI.svg') }}" alt="MTUI Logo" />

  <div class="bg">
    {% if video_stream_ready %}
      <video
        id="bg-video-el"
        src="{{ url_for('stream_current') }}?v={{ video_stream_revision }}"
        autoplay
        preload="auto"
        playsinline
      ></video>
    {% elif video_embed_url %}
      <iframe
        id="bg-video"
        src="{{ video_embed_url }}"
        title="Aktuelles Video"
        allow="autoplay; encrypted-media; picture-in-picture"
        allowfullscreen
      ></iframe>
    {% endif %}
  </div>

  <div id="start-overlay" class="start-overlay">
    <button id="start-btn" class="start-btn" type="button">Tap to start audio</button>
  </div>

  <div class="notice-stack">
    {% if error %}
      <p class="msg error">{{ error }}</p>
    {% endif %}
    {% if status %}
      <p id="status-msg" class="msg status">{{ status }}</p>
    {% endif %}
  </div>

  <div class="shell">
    <main class="wrap">
      <form id="play-form" method="post" action="{{ url_for('play') }}" autocomplete="off">
        <div class="row">
          <input
            id="query"
            name="query"
            type="text"
            placeholder="z. B. daft punk around the world"
            value="{{ query }}"
            autofocus
            required
          />
          <button type="submit">▶ Play</button>
          <button type="submit" class="secondary" formaction="{{ url_for('play_baseline') }}">Random Baseline</button>
        </div>
        <div id="suggest" class="suggest" role="listbox" aria-label="Vorschlaege"></div>
      </form>
    </main>
  </div>

  <script>
    (function () {
      const input = document.getElementById('query');
      const form = document.getElementById('play-form');
      const box = document.getElementById('suggest');
      const bgVideoEl = document.getElementById('bg-video-el');
      const startOverlay = document.getElementById('start-overlay');
      const startBtn = document.getElementById('start-btn');
      const statusMsg = document.getElementById('status-msg');
      const loadingBar = document.getElementById('loading-bar');
      let suggestions = [];
      let activeIndex = -1;
      let timer = null;
      let requestSeq = 0;
      const videoEmbedUrl = {{ video_embed_url|tojson }};
      const videoStreamReady = {{ video_stream_ready|tojson }};
      const streamRevision = {{ video_stream_revision|tojson }};
      const videoTitle = {{ video_title|tojson }};
      const videoMode = {{ video_mode|tojson }};
      let currentMode = videoMode || '';
      let baselineAdvanceInFlight = false;
      let ytPlayer = null;

      function setLoading(active) {
        if (!loadingBar) return;
        loadingBar.classList.toggle('show', !!active);
      }

      function canControlPlayer() {
        return ytPlayer && typeof ytPlayer.getPlayerState === 'function';
      }

      function hideStartOverlay() {
        if (startOverlay) startOverlay.classList.remove('show');
      }

      function showStartOverlay() {
        if (startOverlay) startOverlay.classList.add('show');
      }

      function togglePlayPause() {
        if (bgVideoEl) {
          if (bgVideoEl.paused) {
            bgVideoEl.play().catch(() => {});
          } else {
            bgVideoEl.pause();
          }
          return;
        }
        if (!canControlPlayer() || !window.YT || !window.YT.PlayerState) return;
        const state = ytPlayer.getPlayerState();
        if (state === window.YT.PlayerState.PLAYING) {
          ytPlayer.pauseVideo();
        } else {
          ytPlayer.playVideo();
        }
      }

      function inBaselineMode() {
        return currentMode === 'baseline';
      }

      async function requestNextBaseline() {
        if (!inBaselineMode() || baselineAdvanceInFlight) return;
        baselineAdvanceInFlight = true;
        setLoading(true);
        try {
          const res = await fetch('/next-baseline', { method: 'POST' });
          if (!res.ok) return;
          const data = await res.json();
          if (!data || !data.stream_url) return;

          currentMode = data.mode || 'baseline';
          if (typeof data.query === 'string' && data.query.length) {
            input.value = data.query;
          }
          const rev = data.stream_revision || Date.now().toString();
          bgVideoEl.src = `/stream/current?v=${encodeURIComponent(rev)}`;
          bgVideoEl.load();
          const p = bgVideoEl.play();
          if (p && typeof p.catch === 'function') {
            p.catch(() => showStartOverlay());
          }

          if ('mediaSession' in navigator) {
            try {
              navigator.mediaSession.metadata = new MediaMetadata({
                title: data.title || 'YouTube Jukebox',
                artist: 'YouTube',
                album: 'Jukebox',
              });
            } catch (_) {}
          }
        } catch (_) {
          // silent fallback
        } finally {
          baselineAdvanceInFlight = false;
          setLoading(false);
        }
      }

      function nextTrack() {
        if (bgVideoEl) {
          if (inBaselineMode()) requestNextBaseline();
          return;
        }
        if (ytPlayer && typeof ytPlayer.nextVideo === 'function') {
          ytPlayer.nextVideo();
        }
      }

      function previousTrack() {
        if (bgVideoEl) return;
        if (ytPlayer && typeof ytPlayer.previousVideo === 'function') {
          ytPlayer.previousVideo();
        }
      }

      function setupMediaSession() {
        if (!('mediaSession' in navigator)) return;
        try {
          navigator.mediaSession.metadata = new MediaMetadata({
            title: videoTitle || 'YouTube Jukebox',
            artist: 'YouTube',
            album: 'Jukebox',
          });
        } catch (_) {}

        const bind = (action, handler) => {
          try {
            navigator.mediaSession.setActionHandler(action, handler);
          } catch (_) {}
        };

        bind('play', () => {
          if (bgVideoEl) {
            bgVideoEl.play().catch(() => {});
            return;
          }
          if (canControlPlayer()) ytPlayer.playVideo();
        });
        bind('pause', () => {
          if (bgVideoEl) {
            bgVideoEl.pause();
            return;
          }
          if (canControlPlayer()) ytPlayer.pauseVideo();
        });
        bind('nexttrack', () => { nextTrack(); });
        bind('previoustrack', () => { previousTrack(); });
      }

      function initYouTubeApiControls() {
        if (!videoEmbedUrl) return;
        if (!window.YT || typeof window.YT.Player !== 'function') return;
        try {
          ytPlayer = new window.YT.Player('bg-video', {
            events: {
              onReady: () => {
                setupMediaSession();
              }
            }
          });
        } catch (_) {}
      }

      if (videoStreamReady && bgVideoEl) {
        setupMediaSession();
        setLoading(true);
        if (streamRevision) {
          bgVideoEl.src = `/stream/current?v=${encodeURIComponent(streamRevision)}`;
        }
        const tryPlay = bgVideoEl.play();
        if (tryPlay && typeof tryPlay.catch === 'function') {
          tryPlay.catch(() => {
            showStartOverlay();
            setLoading(false);
          });
        }
        bgVideoEl.addEventListener('play', hideStartOverlay);
        bgVideoEl.addEventListener('loadstart', () => setLoading(true));
        bgVideoEl.addEventListener('waiting', () => setLoading(true));
        bgVideoEl.addEventListener('canplay', () => setLoading(false));
        bgVideoEl.addEventListener('playing', () => setLoading(false));
        bgVideoEl.addEventListener('ended', () => {
          if (inBaselineMode()) requestNextBaseline();
        });
        bgVideoEl.addEventListener('error', () => {
          if (inBaselineMode()) {
            requestNextBaseline();
          } else {
            showStartOverlay();
            setLoading(false);
          }
        });
        if (startBtn) {
          startBtn.addEventListener('click', () => {
            bgVideoEl.muted = false;
            setLoading(true);
            bgVideoEl.play().then(() => {
              hideStartOverlay();
              setLoading(false);
            }).catch(() => {
              showStartOverlay();
              setLoading(false);
            });
          });
        }
      } else if (videoEmbedUrl) {
        window.onYouTubeIframeAPIReady = function () {
          initYouTubeApiControls();
        };
        const ytApiScript = document.createElement('script');
        ytApiScript.src = 'https://www.youtube.com/iframe_api';
        document.head.appendChild(ytApiScript);
      }

      function escapeHtml(text) {
        return text
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\"/g, '&quot;')
          .replace(/'/g, '&#039;');
      }

      function closeSuggest() {
        suggestions = [];
        activeIndex = -1;
        box.innerHTML = '';
        box.classList.remove('open');
      }

      function render() {
        if (!suggestions.length) {
          closeSuggest();
          return;
        }
        box.innerHTML = suggestions.map((text, idx) => {
          const cls = idx === activeIndex ? 'item active' : 'item';
          return `<div class=\"${cls}\" data-idx=\"${idx}\" role=\"option\">${escapeHtml(text)}</div>`;
        }).join('');
        box.classList.add('open');
      }

      function choose(idx, submit) {
        if (idx < 0 || idx >= suggestions.length) return;
        input.value = suggestions[idx];
        closeSuggest();
        if (submit) form.submit();
      }

      function fetchSuggest() {
        const q = input.value.trim();
        if (q.length < 2) {
          closeSuggest();
          return;
        }
        const mySeq = ++requestSeq;
        fetch(`/suggest?q=${encodeURIComponent(q)}`)
          .then((r) => r.ok ? r.json() : [])
          .then((data) => {
            if (mySeq !== requestSeq) return;
            if (!Array.isArray(data)) {
              closeSuggest();
              return;
            }
            suggestions = data.slice(0, 8);
            activeIndex = suggestions.length ? 0 : -1;
            render();
          })
          .catch(() => {
            closeSuggest();
          });
      }

      input.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(fetchSuggest, 200);
      });

      input.addEventListener('keydown', (e) => {
        if (!box.classList.contains('open')) {
          if (e.key === 'Enter') {
            return;
          }
          return;
        }

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          activeIndex = Math.min(activeIndex + 1, suggestions.length - 1);
          render();
          return;
        }

        if (e.key === 'ArrowUp') {
          e.preventDefault();
          activeIndex = Math.max(activeIndex - 1, 0);
          render();
          return;
        }

        if (e.key === 'Enter') {
          if (activeIndex >= 0) {
            e.preventDefault();
            choose(activeIndex, true);
          }
          return;
        }

        if (e.key === 'Escape') {
          e.preventDefault();
          closeSuggest();
        }
      });

      box.addEventListener('mousedown', (e) => {
        const item = e.target.closest('.item');
        if (!item) return;
        const idx = Number(item.dataset.idx);
        choose(idx, true);
      });

      document.addEventListener('keydown', (e) => {
        if (e.code === 'MediaPlayPause') {
          e.preventDefault();
          togglePlayPause();
          return;
        }
        if (e.code === 'MediaTrackNext') {
          e.preventDefault();
          nextTrack();
          return;
        }
        if (e.code === 'MediaTrackPrevious') {
          e.preventDefault();
          previousTrack();
        }
      });

      document.addEventListener('click', (e) => {
        if (!form.contains(e.target)) closeSuggest();
      });

      form.addEventListener('submit', () => {
        setLoading(true);
      });

      if (statusMsg) {
        window.setTimeout(() => {
          statusMsg.classList.add('fade-out');
          window.setTimeout(() => statusMsg.remove(), 280);
        }, 10000);
      }
    })();
  </script>
</body>
</html>
"""


def _player_env():
    env = os.environ.copy()
    uid = env.get("JUKEBOX_UID", "1000")
    env.setdefault("DISPLAY", env.get("JUKEBOX_DISPLAY", ":0"))
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    bus_path = f"/run/user/{uid}/bus"
    if "DBUS_SESSION_BUS_ADDRESS" not in env and os.path.exists(bus_path):
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
    return env


def _read_pid_file():
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def _write_pid_file(pid):
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except OSError:
        pass


def _remove_pid_file():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _stop_pid(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def _stop_player_locked():
    global PLAYER_PROCESS

    if PLAYER_PROCESS is not None:
        if PLAYER_PROCESS.poll() is None:
            _stop_pid(PLAYER_PROCESS.pid)
        PLAYER_PROCESS = None

    stale_pid = _read_pid_file()
    if stale_pid:
        _stop_pid(stale_pid)

    _remove_pid_file()


def stop_player():
    with PLAYER_LOCK:
        _stop_player_locked()


def _resolve_tool(name):
    candidates = [
        shutil.which(name),
        os.path.expanduser(f"~/.local/bin/{name}"),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
    ]

    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    raise RuntimeError(f"{name} nicht gefunden. Bitte install.sh ausfuehren.")


def _extract_spotify_playlist_id(url):
    match = re.search(r"/playlist/([A-Za-z0-9]+)", url or "")
    return match.group(1) if match else ""


def _decode_spotify_state_from_html(html_text):
    payloads = re.findall(r'<script[^>]*type="text/plain"[^>]*>([^<]+)</script>', html_text)
    for payload in payloads:
        blob = payload.strip()
        if not blob:
            continue
        padding = "=" * ((4 - len(blob) % 4) % 4)
        try:
            decoded = base64.b64decode(blob + padding)
            parsed = json.loads(decoded)
        except Exception:
            continue
        if isinstance(parsed, dict) and "entities" in parsed:
            return parsed
    return {}


def _collect_tracks_from_spotify_state(state, playlist_id):
    entities = state.get("entities", {}).get("items", {})
    playlist_key = f"spotify:playlist:{playlist_id}"
    playlist = entities.get(playlist_key, {})
    items = playlist.get("content", {}).get("items", [])

    tracks = []
    for item in items:
        data = item.get("itemV2", {}).get("data", {})
        title = (data.get("name") or "").strip()
        artist_items = data.get("artists", {}).get("items", [])
        artist = ""
        if artist_items:
            artist = (artist_items[0].get("profile", {}).get("name") or "").strip()
        if not title:
            continue
        query = f"{artist} - {title}" if artist else title
        tracks.append(query)

    # keep order, drop duplicates
    deduped = []
    seen = set()
    for track in tracks:
        if track.lower() in seen:
            continue
        deduped.append(track)
        seen.add(track.lower())
    return deduped


def get_baseline_tracks():
    now = time.time()
    with STATE_LOCK:
        if (
            BASELINE_CACHE["url"] == BASELINE_SPOTIFY_URL
            and BASELINE_CACHE["tracks"]
            and (now - BASELINE_CACHE["loaded_at"]) < BASELINE_TTL_SECONDS
        ):
            return list(BASELINE_CACHE["tracks"])

    playlist_id = _extract_spotify_playlist_id(BASELINE_SPOTIFY_URL)
    if not playlist_id:
        raise RuntimeError("Baseline-Playlist URL ist ungueltig.")

    req = urllib.request.Request(
        BASELINE_SPOTIFY_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html_text = response.read().decode("utf-8", "ignore")
    except Exception as exc:
        raise RuntimeError(f"Spotify Baseline nicht erreichbar: {exc}") from exc

    state = _decode_spotify_state_from_html(html_text)
    tracks = _collect_tracks_from_spotify_state(state, playlist_id)
    if not tracks:
        raise RuntimeError("Keine Tracks aus der Spotify-Baseline gelesen.")

    with STATE_LOCK:
        BASELINE_CACHE["url"] = BASELINE_SPOTIFY_URL
        BASELINE_CACHE["loaded_at"] = now
        BASELINE_CACHE["tracks"] = tracks
    return list(tracks)


def disable_baseline_mode():
    with STATE_LOCK:
        BASELINE_SESSION["enabled"] = False
        BASELINE_SESSION["tracks"] = []
        BASELINE_SESSION["remaining"] = []


def _next_baseline_query():
    tracks = get_baseline_tracks()
    with STATE_LOCK:
        BASELINE_SESSION["enabled"] = True
        if not BASELINE_SESSION["tracks"]:
            BASELINE_SESSION["tracks"] = list(tracks)
        if not BASELINE_SESSION["remaining"]:
            BASELINE_SESSION["remaining"] = list(BASELINE_SESSION["tracks"])
            random.shuffle(BASELINE_SESSION["remaining"])
        if not BASELINE_SESSION["remaining"]:
            raise RuntimeError("Baseline-Playlist ist leer.")
        return BASELINE_SESSION["remaining"].pop()


def find_first_video(query):
    ytdlp = _resolve_tool("yt-dlp")
    cmd = [ytdlp, "--dump-single-json", "--no-warnings", f"ytsearch1:{query}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "yt-dlp Suche fehlgeschlagen.")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp lieferte ungueltige Daten.") from exc

    entry = None
    entries = payload.get("entries")
    if isinstance(entries, list) and entries:
        entry = entries[0]
    elif payload.get("id"):
        entry = payload

    if not entry or not entry.get("id"):
        return None

    video_id = entry.get("id")
    title = entry.get("title") or "Unbekannter Titel"
    webpage_url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"

    return {
        "id": video_id,
        "title": title,
        "url": webpage_url,
    }


def build_embed_url(video_id, origin=""):
    params = urllib.parse.urlencode(
        {
            "autoplay": 1,
            "controls": 0,
            "modestbranding": 1,
            "rel": 0,
            "iv_load_policy": 3,
            "playsinline": 1,
            "enablejsapi": 1,
        }
    )
    if origin:
        params = f"{params}&origin={urllib.parse.quote(origin, safe='')}"
    return f"https://www.youtube.com/embed/{video_id}?{params}"


def resolve_stream_url(video_url, target="mpv"):
    ytdlp = _resolve_tool("yt-dlp")
    if target == "browser":
        format_selector = (
            "22/18/"
            "best[ext=mp4][protocol=https][acodec!=none][vcodec!=none]/"
            "best[ext=mp4][acodec!=none][vcodec!=none]/"
            "best[acodec!=none][vcodec!=none]"
        )
    else:
        format_selector = (
            "best[ext=mp4][acodec!=none][vcodec!=none]/"
            "best[acodec!=none][vcodec!=none]/best"
        )

    cmd = [
        ytdlp,
        "-f",
        format_selector,
        "--no-playlist",
        "-g",
        "--no-warnings",
        video_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "Konnte Stream-URL nicht aufloesen.")

    stream_url = ""
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if candidate.startswith("http"):
            stream_url = candidate
            break

    if not stream_url:
        raise RuntimeError("Kein gueltiger Stream-Link gefunden.")

    return stream_url


def resolve_stream_source_for_browser(video_url):
    ytdlp = _resolve_tool("yt-dlp")
    format_selector = (
        "22/18/"
        "best[ext=mp4][protocol=https][acodec!=none][vcodec!=none]/"
        "best[ext=mp4][acodec!=none][vcodec!=none]/"
        "best[acodec!=none][vcodec!=none]"
    )
    cmd = [
        ytdlp,
        "-f",
        format_selector,
        "--extractor-args",
        "youtube:player_client=android",
        "--no-playlist",
        "--print",
        "URL=%(url)s",
        "--print",
        "HEADERS=%(http_headers)j",
        "--no-warnings",
        video_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "Konnte Browser-Stream nicht aufloesen.")

    stream_url = ""
    stream_headers = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("URL="):
            stream_url = line[4:].strip()
        elif line.startswith("HEADERS="):
            raw = line[8:].strip()
            if raw:
                with suppress(json.JSONDecodeError):
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        stream_headers = {str(k): str(v) for k, v in parsed.items() if v}

    if not stream_url:
        raise RuntimeError("Kein gueltiger Browser-Stream-Link gefunden.")

    if "User-Agent" not in stream_headers:
        stream_headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
        )
    if "Accept" not in stream_headers:
        stream_headers["Accept"] = "*/*"

    return stream_url, stream_headers


def start_player(stream_url):
    global PLAYER_PROCESS

    mpv = _resolve_tool("mpv")

    cmd = [
        mpv,
        "--fullscreen",
        "--force-window=yes",
        "--no-terminal",
        "--really-quiet",
        stream_url,
    ]

    with PLAYER_LOCK:
        _stop_player_locked()
        try:
            PLAYER_PROCESS = subprocess.Popen(
                cmd,
                env=_player_env(),
                preexec_fn=os.setsid,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RuntimeError(f"mpv konnte nicht gestartet werden: {exc}") from exc

        _write_pid_file(PLAYER_PROCESS.pid)


def play_video_for_query(query, mode="search"):
    video = find_first_video(query)
    if not video:
        return None

    if PLAYBACK_MODE == "mpv":
        stream_url = resolve_stream_url(video["url"], target="mpv")
        start_player(stream_url)
        with STATE_LOCK:
            CURRENT_VIDEO["id"] = video["id"]
            CURRENT_VIDEO["title"] = video["title"]
            CURRENT_VIDEO["stream_url"] = ""
            CURRENT_VIDEO["stream_headers"] = {}
            CURRENT_VIDEO["stream_revision"] = ""
            CURRENT_VIDEO["embed_url"] = ""
            CURRENT_VIDEO["mode"] = mode
            CURRENT_VIDEO["query"] = query
    else:
        stream_url, stream_headers = resolve_stream_source_for_browser(video["url"])
        stop_player()
        with STATE_LOCK:
            CURRENT_VIDEO["id"] = video["id"]
            CURRENT_VIDEO["title"] = video["title"]
            CURRENT_VIDEO["stream_url"] = stream_url
            CURRENT_VIDEO["stream_headers"] = stream_headers
            CURRENT_VIDEO["stream_revision"] = str(int(time.time() * 1000))
            CURRENT_VIDEO["embed_url"] = ""
            CURRENT_VIDEO["mode"] = mode
            CURRENT_VIDEO["query"] = query

    return video


def play_next_baseline_video(max_attempts=6):
    last_query = ""
    for _ in range(max_attempts):
        baseline_query = _next_baseline_query()
        last_query = baseline_query
        video = play_video_for_query(baseline_query, mode="baseline")
        if video:
            return video, baseline_query
    raise RuntimeError(f"Kein spielbarer Treffer in Baseline (zuletzt: {last_query}).")


@app.route("/", methods=["GET"])
def index():
    with STATE_LOCK:
        current_embed_url = CURRENT_VIDEO.get("embed_url", "")
        current_stream_url = CURRENT_VIDEO.get("stream_url", "")
        current_stream_revision = CURRENT_VIDEO.get("stream_revision", "")
        current_title = CURRENT_VIDEO.get("title", "")
        current_mode = CURRENT_VIDEO.get("mode", "")

    return render_template_string(
        INDEX_TEMPLATE,
        error=request.args.get("error", ""),
        status=request.args.get("status", ""),
        query=request.args.get("query", ""),
        video_embed_url=current_embed_url,
        video_stream_ready=bool(current_stream_url),
        video_stream_revision=current_stream_revision,
        video_title=current_title,
        video_mode=current_mode,
    )


@app.route("/stream/current", methods=["GET"])
def stream_current():
    with STATE_LOCK:
        stream_url = CURRENT_VIDEO.get("stream_url", "")
        base_headers = dict(CURRENT_VIDEO.get("stream_headers") or {})

    if not stream_url:
        return Response("Kein aktiver Stream.", status=404, mimetype="text/plain")

    outbound_headers = {}
    for key, value in base_headers.items():
        if not value:
            continue
        lk = key.lower()
        if lk in {"host", "content-length", "accept-encoding", "connection", "range"}:
            continue
        outbound_headers[key] = value

    request_range = request.headers.get("Range")
    if request_range:
        outbound_headers["Range"] = request_range

    if "User-Agent" not in outbound_headers:
        outbound_headers["User-Agent"] = "Mozilla/5.0"

    upstream_req = urllib.request.Request(stream_url, headers=outbound_headers, method="GET")
    try:
        upstream = urllib.request.urlopen(upstream_req, timeout=30)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return Response(
            body,
            status=exc.code,
            headers={"Content-Type": exc.headers.get("Content-Type", "text/plain")},
        )
    except Exception as exc:
        return Response(f"Stream proxy error: {exc}", status=502, mimetype="text/plain")

    def generate():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            with suppress(Exception):
                upstream.close()

    proxied = Response(stream_with_context(generate()), status=getattr(upstream, "status", 200))
    for header in (
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "Cache-Control",
        "ETag",
        "Last-Modified",
    ):
        value = upstream.headers.get(header)
        if value:
            proxied.headers[header] = value
    return proxied


@app.route("/suggest", methods=["GET"])
def suggest():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify([])

    query = query[:120]
    params = urllib.parse.urlencode({"client": "firefox", "ds": "yt", "q": query})
    url = f"https://suggestqueries.google.com/complete/search?{params}"

    try:
        with urllib.request.urlopen(url, timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        suggestions = [str(item).strip() for item in raw if str(item).strip()]
        return jsonify(suggestions[:8])
    except Exception:
        return jsonify([])


@app.route("/play", methods=["POST"])
def play():
    query = (request.form.get("query") or "").strip()

    if not query:
        return redirect(url_for("index", error="Bitte Suchbegriff eingeben."))
    disable_baseline_mode()

    try:
        video = play_video_for_query(query, mode="search")
    except RuntimeError as exc:
        return f"Wiedergabe-Fehler: {exc}", 500

    if not video:
        return redirect(url_for("index", error="Kein Treffer fuer diese Suche."))

    status = f"Spiele: {video['title']}"
    return redirect(url_for("index", status=status, query=query))


@app.route("/play-baseline", methods=["POST"])
def play_baseline():
    try:
        video, baseline_query = play_next_baseline_video()
    except RuntimeError as exc:
        return redirect(url_for("index", error=f"Baseline-Fehler: {exc}"))

    if not video:
        return redirect(url_for("index", error="Kein Treffer fuer Baseline-Titel."))

    status = f"Baseline random: {video['title']}"
    return redirect(url_for("index", status=status, query=baseline_query))


@app.route("/next-baseline", methods=["POST"])
def next_baseline():
    with STATE_LOCK:
        enabled = BASELINE_SESSION.get("enabled", False)
    if not enabled:
        return jsonify({"error": "Baseline-Modus ist nicht aktiv."}), 409

    try:
        video, baseline_query = play_next_baseline_video()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    with STATE_LOCK:
        stream_url = CURRENT_VIDEO.get("stream_url", "")
        stream_revision = CURRENT_VIDEO.get("stream_revision", "")
        mode = CURRENT_VIDEO.get("mode", "")

    return jsonify(
        {
            "title": video.get("title", ""),
            "query": baseline_query,
            "stream_url": stream_url,
            "stream_revision": stream_revision,
            "mode": mode,
        }
    )


@atexit.register
def _cleanup_on_exit():
    stop_player()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
