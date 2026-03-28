# YACHIYO Gateway

## Conda Environment

- Environment name: `yachiyo-gateway`
- Always `source activate yachiyo-gateway` before running any Python command

## Server Management

- Server entry: `python server.py` (default port 8080)
- When restarting the server:
  - Check what's using the port (`netstat -ano | grep ":8080"`)
  - If it's the old gateway server process, kill it and restart
  - If it's an unknown process, investigate what it is, report to the user with PID and process info, let the user decide
  - On Windows, use `powershell -Command "Stop-Process -Id <PID> -Force"` to kill processes (bash `kill` doesn't work for Windows processes)

## Architecture

- `live/` (input) → `server.py` (router) → `livechat/` (WebSocket display) + `unity/` (forward)
- Settings stored in `settings.json` with nested per-platform structure
- Platform-specific config under `settings["bilibili"]`, `settings["youtube"]`, etc.
- Top-level keys: `platform`, `unity_endpoint`, `pipeline_destination`, `custom_css`

## Submodules

- `blivedm/` — Bilibili live danmaku library
- `pytchat/` — YouTube live chat library (requires `httpx[http2]`)
