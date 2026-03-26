# YACHIO Gateway - Progress

## Current Status
Gateway server with modular architecture, blivedm integration, block rules, tested and working.

## Architecture
```
Bilibili Live Room
    ↓ (blivedm WebSocket)
live/bilibili.py (BilibiliLive — receiving + block rules)
    ↓ (callbacks: on_message, on_log, on_status_change)
server.py (GatewayServer — thin router, HTTP handlers)
    ├→ livechat/broadcaster.py (LivechatBroadcaster — WebSocket broadcast to UI + overlay)
    └→ unity/client.py (UnityClient — HTTP POST to Unity + pipeline event handling)
            ↓
    Unity ExternalMessageManager (port 7890) / Fake Receiver (port 7891)
            ↓ (WebSocket)
    YACHIO Server (10.81.7.143:8910, vtuber_danmaku pipeline)
```

### Module Structure
```
YACHIO_gateway/
  server.py              # Thin router + HTTP handlers + main()
  live/
    __init__.py
    bilibili.py          # BilibiliLive + _DanmakuHandler + _OpenLiveHandler
  unity/
    __init__.py
    client.py            # UnityClient (forward + pipeline events)
  livechat/
    __init__.py
    broadcaster.py       # LivechatBroadcaster (WebSocket broadcast)
    index.html           # Overlay page (OBS Browser Source)
    style.css            # YouTube-style CSS
  test/                  # Test scripts
  fake_receiver.py       # Simulates Unity for testing
```

## Completed

### Modular Refactoring
- Extracted live receiving logic into `live/bilibili.py` (BilibiliLive class)
- Extracted Unity forwarding into `unity/client.py` (UnityClient class)
- Extracted WebSocket broadcast into `livechat/broadcaster.py` (LivechatBroadcaster class)
- server.py is now a thin router (~300 lines) connecting modules via callbacks
- Callback pattern: live module emits on_message/on_log/on_status_change → server routes to livechat + unity
- Settings mapping tables (LIVE_SETTINGS_MAP, UNITY_SETTINGS_MAP) for clean camelCase ↔ snake_case
- Each module owns its own get_state()/get_persist_data() — server merges all three for API/persistence

### Block Rules (Bilibili Filter)
- blivechat-compatible block rules, same filtering scope per message type as blivechat
- Danmaku: all 8 rules (giftDanmaku, mirror, level, newbie, mobileVerified, medalLevel, keywords, users)
- Gift: no block rules
- Guard: blockUsers only
- SC: blockKeywords + blockUsers
- Open Live: subset (mirror*, medalLevel, keywords, users) due to API field limitations
- All rules persisted to settings.json, configurable from Live Settings modal
- Blocked messages still count as received (msg_received++)

### blivedm Integration
- Direct blivedm via git submodule, 3 modes: guest, web (SESSDATA), Open Live
- CustomClientResponse fix for aiohttp CancelledError bug
- Handles: danmaku, gift, guard buy, super chat, interact word v2

### Livechat Overlay (OBS Browser Source)
- yt-live-chat-* custom elements matching blivechat structure
- SC/gift 7-tier price color mapping, guard level author-type
- WebSocket to /ws, auto-reconnect, 80 message limit
- Compatible with blivechat Style Generator output via custom CSS

### Unity Integration
- UnityClient: forward YYMessage via HTTP POST, pipeline event handling (EoS → playback_complete)
- ExternalMessageManager bidirectional support
- Pipeline event endpoint /api/pipeline-event

### Fake Unity Receiver (fake_receiver.py)
- Simulates Unity for testing, HTTP endpoints: POST /send, GET /health, GET /received

## Issues Found & Resolved

### 1. blivedm reconnect loop in gateway
**Problem**: blivedm entered reconnect loop inside aiohttp web server.
**Fix**: Added CustomClientResponse (aiohttp CancelledError → ClientConnectionError), session timeout, cookie domain fix.

### 2. destination field routing bug
**Fix**: Set content's `destination: -2` (route to next node), keep YYMessage wrapper's `destination: 0` for Unity routing.

### 3. Server requires client registration before WebSocket
**Fix**: Added registration + pipeline init steps to fake_receiver.py.

## Next Steps
- Wire up Unity ExternalMessageManager to real Unity pipeline (DataRouter for EoS)
- Test with Unity instead of fake receiver
