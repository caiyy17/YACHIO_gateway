"""
Livechat broadcast module.

Manages WebSocket clients (main UI + livechat overlay) and broadcasts
messages to them. Also handles custom CSS for the livechat overlay.
"""

import json
import logging

from aiohttp import web

logger = logging.getLogger('livechat')


class LivechatBroadcaster:
    """Manages WebSocket broadcast to main UI and livechat overlay."""

    def __init__(self, config):
        self._clients = set()
        self.custom_css = config.get('custom_css', '')

    async def broadcast(self, data):
        """Send JSON data to all connected WebSocket clients."""
        if not self._clients:
            return
        msg = json.dumps(data, ensure_ascii=False)
        closed = set()
        for ws in self._clients:
            try:
                await ws.send_str(msg)
            except Exception:
                closed.add(ws)
        self._clients -= closed

    async def handle_ws(self, request, initial_state):
        """Handle WebSocket connection: add client, send initial state, wait until close."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)

        await ws.send_json(initial_state)

        try:
            async for msg in ws:
                pass
        finally:
            self._clients.discard(ws)

        return ws

    # ─── Settings ───

    def update_settings(self, settings):
        """Update livechat-owned settings."""
        if 'custom_css' in settings:
            self.custom_css = settings['custom_css']

    def get_state(self):
        """Return livechat-related state for API (camelCase keys)."""
        return {
            'customCss': self.custom_css,
        }

    def get_persist_data(self):
        """Return livechat-related data for settings.json (snake_case keys)."""
        return {
            'custom_css': self.custom_css,
        }
