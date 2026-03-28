# YACHIYO Gateway

Gateway server for live streaming message processing. Receives live chat messages, applies filters, and routes to display (livechat overlay) and forwarding (Unity pipeline) modules.

## Architecture

```
Live Source (Bilibili / ...)
    |  (blivedm WebSocket)
    v
live/bilibili.py  (BilibiliLive - receive + filter)
    |  callbacks: on_message, on_log, on_status_change
    v
server.py  (GatewayServer - thin router, HTTP API)
    |--- livechat/broadcaster.py  (WebSocket broadcast to UI + OBS overlay)
    |--- unity/client.py          (HTTP POST to Unity pipeline)
```

## Modules

### live/ - Live Source Receiving

Receives messages from live platforms and emits normalized events via callbacks.

#### live/bilibili.py - Bilibili

Connects to Bilibili live rooms via [blivedm](https://github.com/xfgryujk/blivedm) (git submodule).

**Connection modes:**

| Mode | Auth | Input |
|------|------|-------|
| guest | None | Room ID |
| web | SESSDATA cookie | Room ID |
| open_live | Key ID + Secret + App ID | Streamer auth code |

**Message types and output fields:**

All messages are emitted via `on_message(msg_type, text, user, *, guard_level, num, price, face, should_forward)`.

| msg_type | text | guard_level | num | price | face |
|----------|------|:-----------:|:---:|:-----:|:----:|
| `danmaku` | Message content | Privilege type (0/1/2/3) | - | - | Avatar URL |
| `gift` | Gift name | - | Gift count | Total price (yuan) | Avatar URL |
| `guard` | Guard type name (Captain/Admiral/Governor) | Guard level (1/2/3) | Months purchased | Total price (yuan) | Avatar URL |
| `super_chat` | SC message content | - | - | Price (yuan) | Avatar URL |

Additional event-only messages (on_log only, no on_message):
- `interact_word_v2`: Enter room, follow, share, like (web/guest)
- `like`, `enter_room`: Like, enter room (Open Live)

**Block rules (blivechat-compatible):**

Filtering follows [blivechat](https://github.com/xfgryujk/blivechat) behavior. Blocked messages still count toward `msg_received`.

| Rule | Danmaku | Gift | Guard | SC |
|------|:-------:|:----:|:-----:|:--:|
| blockGiftDanmaku | yes | | | |
| blockMirrorMessages | yes | | | |
| blockLevel | yes | | | |
| blockNewbie | yes | | | |
| blockNotMobileVerified | yes | | | |
| blockMedalLevel | yes | | | |
| blockKeywords | yes | | | yes |
| blockUsers | yes | | yes | yes |

Open Live mode supports a subset due to API limitations:

| Rule | Danmaku | Gift | Guard | SC |
|------|:-------:|:----:|:-----:|:--:|
| blockMirrorMessages | yes* | | | |
| blockMedalLevel | yes | | | |
| blockKeywords | yes | | | yes |
| blockUsers | yes | | yes | yes |

\* `is_mirror` is declared in blivedm's Open Live model but not parsed from API data, so this rule has no effect in practice.

**blivedm aiohttp fix:**

`_CustomClientResponse` converts `CancelledError` in `_wait_released()` to `ClientConnectionError`, preventing silent task death during reconnection.

### server.py - Router

Thin routing layer. Receives callbacks from live module, dispatches to output modules. Handles HTTP API, settings persistence, and static file serving.

### livechat/ - Display Output

WebSocket broadcast to connected clients (main UI + OBS browser source overlay).

- `broadcaster.py`: Manages WebSocket clients, broadcasts feed/log/status messages
- `index.html`: YouTube-style chat overlay with yt-live-chat-* custom elements
- `style.css`: Compatible with blivechat Style Generator CSS

### unity/ - Unity Forwarding

HTTP POST forwarding to Unity's ExternalMessageManager.

- `client.py`: Builds YYMessage, forwards to Unity endpoint, handles pipeline events
- Pipeline event handling: Detects EoS signal and sends `playback_complete` back to Unity

## Usage

```bash
python server.py [--port 8080] [--host 127.0.0.1] [--unity-endpoint http://localhost:7890/send]
```

## Test

```
test/
  fake_live_sender.py      # Sends fake messages to gateway (simulates live source)
  fake_unity_receiver.py   # Receives messages from gateway (simulates Unity)
```
