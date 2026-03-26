"""
Unity forwarding module.

Handles sending messages to Unity's ExternalMessageManager via HTTP POST,
and processing pipeline events received from Unity (including EoS → playback_complete).
"""

import json
import logging

import aiohttp

logger = logging.getLogger('unity')


class UnityClient:
    """Forwards messages to Unity and handles pipeline events."""

    def __init__(self, config, *, on_log, on_stats, on_feed):
        """
        Args:
            config: dict with unity-related settings
            on_log: async callback(tag, msg)
            on_stats: async callback(forwarded)
            on_feed: async callback(msg_type, user, text)
        """
        self._on_log = on_log
        self._on_stats = on_stats
        self._on_feed = on_feed

        self.endpoint = config.get('unity_endpoint', 'http://localhost:7890/send')
        self.pipeline_destination = config.get('pipeline_destination', 0)
        self.connected = config.get('unity_connected', False)
        self.msg_forwarded = 0

        self._session = None

    async def start(self):
        """Create HTTP session. Call once at app startup."""
        self._session = aiohttp.ClientSession()

    async def stop(self):
        """Close HTTP session. Call at app shutdown."""
        if self._session:
            await self._session.close()

    # ─── Forward to Unity ───

    async def forward(self, msg_type, text, user, *,
                      guard_level=0, num=0, price=0):
        """Build YYMessage and POST to Unity endpoint. Returns True on success."""
        if not self.connected:
            await self._on_log('err', f'Unity not connected — {user}: {text}')
            return False

        content_obj = {
            'text': text, 'user': user, 'msg_type': msg_type,
            'guard_level': guard_level, 'num': num,
            'price': price, 'destination': -2,
        }
        yy_message = {
            'signal': '',
            'content': json.dumps(content_obj, ensure_ascii=False),
            'destination': self.pipeline_destination,
        }

        try:
            async with self._session.post(
                self.endpoint, json=yy_message,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    self.msg_forwarded += 1
                    await self._on_stats(self.msg_forwarded)
                    await self._on_log('fwd', f'Forwarded — {user}: {text}')
                    return True
                else:
                    logger.warning(f'Forward failed: HTTP {resp.status}')
                    await self._on_log('err', f'Forward failed: HTTP {resp.status}')
                    return False
        except Exception as e:
            logger.warning(f'Forward error: {e}')
            await self._on_log('err', f'Forward error: {e}')
            return False

    async def send_raw(self, body):
        """Forward raw JSON body to Unity endpoint. Returns (status, result_text)."""
        if not self.connected:
            return 0, 'Unity not connected'
        try:
            async with self._session.post(
                self.endpoint, json=body,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                result = await resp.text()
                return resp.status, result
        except Exception as e:
            return 0, str(e)

    # ─── Pipeline Events ───

    async def handle_pipeline_event(self, data):
        """
        Process a pipeline event from Unity.
        Broadcasts log + feed, and if EoS signal detected, sends playback_complete back.
        """
        event_name = data.get('eventName', '')
        message = data.get('message', {})

        logger.info(f'[pipeline-event] {event_name}: {message}')
        msg_str = json.dumps(message, ensure_ascii=False) if isinstance(message, dict) else str(message)
        await self._on_log('pipeline', f'[{event_name}] {msg_str}')
        await self._on_feed('pipeline', event_name, msg_str)

        # Parse message if string
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except (json.JSONDecodeError, TypeError):
                message = {}

        # EoS → send playback_complete back to pipeline
        msg_signal = message.get('signal', '') if isinstance(message, dict) else ''
        if msg_signal == 'EoS':
            timestamp = message.get('timestamp', 0)
            content_obj = {
                'signal': 'playback_complete',
                'last_batch_timestamp': timestamp,
            }
            yy_message = {
                'signal': '',
                'content': json.dumps(content_obj, ensure_ascii=False),
                'destination': self.pipeline_destination,
            }
            status, result = await self.send_raw(yy_message)
            logger.info(f'[pipeline-event] Sent playback_complete (last_batch_timestamp={timestamp}), status={status}')
            await self._on_log('fwd', f'playback_complete → Unity (last_batch_timestamp={timestamp})')

    # ─── Settings ───

    def toggle_connect(self):
        """Toggle connection state. Returns new state."""
        self.connected = not self.connected
        return self.connected

    def update_settings(self, data):
        """Update unity-owned settings from web UI (camelCase keys). Ignores unknown keys."""
        if 'unityEndpoint' in data:
            self.endpoint = data['unityEndpoint']
        if 'pipelineDestination' in data:
            self.pipeline_destination = int(data['pipelineDestination'])

    def get_state(self):
        """Return unity-related state for API (camelCase keys)."""
        return {
            'unityConnected': self.connected,
            'unityEndpoint': self.endpoint,
            'pipelineDestination': self.pipeline_destination,
            'forwarded': self.msg_forwarded,
        }

    def get_persist_data(self):
        """Return unity-related data for settings.json (snake_case keys)."""
        return {
            'unity_endpoint': self.endpoint,
            'pipeline_destination': self.pipeline_destination,
        }
