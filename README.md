# YACHIYO Gateway

Live streaming message gateway. Receives live chat from streaming platforms, applies filters, and routes to livechat overlay (OBS) and Unity pipeline.

## Architecture

Three separate services, connected via HTTP/WebSocket:

```
┌─────────────────────────────────────────────────────────┐
│  YACHIYO Gateway (port 8080)                            │
│                                                         │
│  Live Source ──→ server.py (router) ──┬→ livechat/      │
│  (Bilibili / YouTube)                │   (WebSocket     │
│                                      │    → OBS overlay)│
│                                      └→ unity/          │
│                                         (HTTP POST      │
│                                          → Unity)       │
└─────────────────────────────────────────────────────────┘
         ↕ HTTP POST                    ↕ WebSocket
┌────────────────────┐          ┌────────────────────────┐
│  Unity Client      │          │  YACHIYO Server        │
│  (port 7890)       │←────────→│  (port 8910)           │
│  ExternalMessage   │ WebSocket│  AI pipeline           │
│  Manager           │          │                        │
└────────────────────┘          └────────────────────────┘
```

## Modules

### live/ - Live Source Receiving

Receives messages from live platforms and emits normalized events via callbacks.

Supported platforms:
- **Bilibili** (`live/bilibili.py`) — via [blivedm](https://github.com/xfgryujk/blivedm) (git submodule). Modes: guest, web (SESSDATA), Open Live.
- **YouTube** (`live/youtube.py`) — via [pytchat](https://github.com/taizan-hokuto/pytchat) (git submodule). Connects via video URL.

Message types: `danmaku`, `gift`, `guard`, `super_chat`.

Block rules (Bilibili): blockGiftDanmaku, blockMirrorMessages, blockLevel, blockNewbie, blockNotMobileVerified, blockMedalLevel, blockKeywords, blockUsers. Configurable from web UI, persisted to `settings.json`.

### server.py - Router

Thin routing layer. Receives callbacks from live module, dispatches to output modules. Handles HTTP API, settings persistence, platform hot-swap, and static file serving.

### livechat/ - Display Output (OBS Overlay)

WebSocket broadcast to connected clients.

- `broadcaster.py`: WebSocket client management, feed/log/status broadcast
- `index.html`: YouTube-style chat overlay (`yt-live-chat-*` custom elements)
- `style.css`: Base styles, compatible with blivechat Style Generator CSS

### unity/ - Unity Forwarding

HTTP POST forwarding to Unity's `ExternalMessageManager`.

- `client.py`: Builds `YYMessage`, forwards to Unity endpoint, handles pipeline events (EoS → `playback_complete`)

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Main control UI |
| GET | `/livechat/` | OBS overlay page |
| GET | `/ws` | WebSocket (state + live feed) |
| GET | `/api/state` | Full server state |
| POST | `/api/connect` | Connect to live platform |
| POST | `/api/disconnect` | Disconnect |
| POST | `/api/settings` | Update settings (platform, block rules, etc.) |
| POST | `/api/unity-toggle` | Toggle Unity forwarding |
| POST | `/api/send` | Send raw message to Unity |
| POST | `/api/send-danmaku` | Send structured danmaku through full pipeline |
| POST | `/api/pipeline-event` | Receive pipeline output from Unity |
| POST | `/api/upload-avatar` | Upload avatar image (resize to 300x300) |
| GET | `/api/avatars` | List saved avatars |

## Usage

```bash
source activate yachiyo-gateway
python server.py [--port 8080] [--host 127.0.0.1]
```

## Test

```
test/
  fake_live_sender.py      # Simulates live source → gateway
  fake_unity_receiver.py   # Simulates Unity ← gateway
```
