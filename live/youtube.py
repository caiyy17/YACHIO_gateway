"""
YouTube Live chat receiving module.

Connects to YouTube live streams via pytchat (LiveChatAsync),
applies block rules, and emits normalized messages via callbacks.
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add pytchat submodule to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pytchat'))

from pytchat import LiveChatAsync, InvalidVideoIdException
from pytchat.util import extract_video_id


logger = logging.getLogger('live.youtube')


class YouTubeLive:
    """YouTube live chat connection and message receiving with block rules."""

    def __init__(self, config, *, on_message, on_log, on_status_change):
        """
        Args:
            config: dict with youtube-related settings
            on_message: async callback(msg_type, text, user, *, guard_level, num, price, face, should_forward)
            on_log: async callback(tag, msg)
            on_status_change: async callback(connected, room_id=None, mode=None, error=None)
        """
        self._on_message = on_message
        self._on_log = on_log
        self._on_status_change = on_status_change

        # Connection state
        self.platform = 'youtube'
        self.yt_url = config.get('url', '')
        self.connected = False
        self.msg_received = 0
        self._pytchat = None

        # Settings
        self.auto_forward = config.get('auto_forward', True)
        self.forward_gifts = config.get('forward_gifts', True)

        # Block rules
        self.block_keywords = config.get('block_keywords', '')
        self.block_users = config.get('block_users', '')

    async def start(self):
        """No-op for YouTube (pytchat created in connect)."""
        pass

    async def stop(self):
        """Disconnect and clean up."""
        await self.disconnect()

    # ─── Connection ───

    async def connect(self):
        """Connect to YouTube live chat. Returns True on success."""
        if self.connected:
            await self.disconnect()

        self.msg_received = 0

        if not self.yt_url:
            await self._on_status_change(False, error='YouTube URL required')
            return False

        try:
            video_id = extract_video_id(self.yt_url)
        except (InvalidVideoIdException, TypeError) as e:
            await self._on_status_change(False, error=f'Invalid YouTube URL: {e}')
            return False

        try:
            # LiveChatAsync creates event loop tasks in __init__,
            # so it must be created inside an async context.
            self._pytchat = LiveChatAsync(
                video_id,
                interruptable=False,
                callback=self._on_chat_batch,
                done_callback=self._on_stream_end,
            )
            self.connected = True
            logger.info(f'[youtube] Connected to video {video_id}')
            await self._on_status_change(True, room_id=video_id, mode='youtube')
            return True
        except Exception as e:
            logger.error(f'Failed to connect (youtube): {e}')
            self.connected = False
            await self._on_status_change(False, error=str(e))
            return False

    async def disconnect(self):
        """Disconnect from YouTube live chat."""
        if self._pytchat:
            self._pytchat.terminate()
            self._pytchat = None
        if self.connected:
            self.connected = False
            logger.info('Disconnected from YouTube')
            await self._on_status_change(False)

    # ─── Chat Processing ───

    async def _on_chat_batch(self, chatdata):
        """Callback from pytchat: receives a Chatdata with .items list."""
        for chat in chatdata.items:
            self._process_chat(chat)

    def _process_chat(self, chat):
        """Map a pytchat Chat object to internal message format and emit."""
        chat_type = getattr(chat, 'type', '')
        message = getattr(chat, 'message', '')
        author = getattr(chat, 'author', None)
        user = getattr(author, 'name', '') if author else ''
        face = getattr(author, 'imageUrl', '') if author else ''
        amount_value = getattr(chat, 'amountValue', 0.0)
        amount_string = getattr(chat, 'amountString', '')

        # Member badge (isChatSponsor = YouTube channel member ≈ bilibili Captain)
        is_member = getattr(author, 'isChatSponsor', False) if author else False

        # Map pytchat type -> internal type
        if chat_type == 'textMessage':
            msg_type = 'danmaku'
            text = message
            price, num, guard_level = 0, 0, (3 if is_member else 0)
        elif chat_type == 'superChat':
            msg_type = 'super_chat'
            text = message
            price, num, guard_level = amount_value, 0, (3 if is_member else 0)
        elif chat_type == 'superSticker':
            msg_type = 'super_chat'
            text = amount_string  # stickers have no text, use amount display
            price, num, guard_level = amount_value, 0, (3 if is_member else 0)
        elif chat_type == 'newSponsor':
            msg_type = 'guard'
            text = message
            price, num, guard_level = 0, 1, 3  # 3 = Captain equivalent
        else:
            return  # skip donation and unknown types

        self.msg_received += 1

        # Block rules
        if self._is_keyword_blocked(text):
            asyncio.ensure_future(self._on_log('blocked', f'{user}: {text}'))
            logger.info(f'[blocked] {user}: {text}')
            return
        if self._is_user_blocked(user):
            asyncio.ensure_future(self._on_log('blocked', f'{user}: {text}'))
            logger.info(f'[blocked] {user}: {text}')
            return

        # Forwarding decision
        should_forward = self.auto_forward
        if msg_type != 'danmaku':
            should_forward = self.auto_forward and self.forward_gifts

        # Logging
        if msg_type == 'super_chat':
            log_tag, log_msg = 'sc', f'[SC ${price}] {user}: {text}'
        elif msg_type == 'guard':
            log_tag, log_msg = 'member', f'{user} became Member'
        else:
            log_tag, log_msg = 'danmaku', f'{user}: {text}'

        asyncio.ensure_future(self._on_log(log_tag, log_msg))
        logger.info(f'[{msg_type}] {log_msg}')
        asyncio.ensure_future(self._on_message(
            msg_type, text, user,
            guard_level=guard_level, num=num, price=price, face=face,
            should_forward=should_forward,
        ))

    def _on_stream_end(self, task):
        """Called when pytchat listen task finishes (stream ended or error)."""
        was_connected = self.connected
        self.connected = False

        # Clean up pytchat internals
        if self._pytchat:
            if self._pytchat.is_alive():
                self._pytchat.terminate()
            self._pytchat = None

        if was_connected:
            asyncio.ensure_future(self._on_status_change(False))

        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug('YouTube listen task cancelled')
        except Exception as e:
            logger.error(f'YouTube stream ended with error: {e}')
        else:
            if was_connected:
                logger.info('YouTube stream ended')

    # ─── Block Rules ───

    def _is_keyword_blocked(self, text):
        """Check if text contains any blocked keyword."""
        if not self.block_keywords or not text:
            return False
        text_lower = text.lower()
        for kw in self.block_keywords.split('\n'):
            kw = kw.strip().lower()
            if kw and kw in text_lower:
                return True
        return False

    def _is_user_blocked(self, author_name):
        """Check if YouTube author name is in blocked users list."""
        if not self.block_users or not author_name:
            return False
        name_lower = author_name.lower()
        for user in self.block_users.split('\n'):
            user = user.strip().lower()
            if user and user == name_lower:
                return True
        return False

    # ─── Settings ───

    _SETTINGS_MAP = {
        'ytUrl': ('yt_url', str),
        'autoForward': ('auto_forward', bool),
        'forwardGifts': ('forward_gifts', bool),
        'blockKeywords': ('block_keywords', str),   # UI sends this key
        'blockUsers': ('block_users', str),          # UI sends this key
    }
    # NOTE: get_state() returns ytBlockKeywords/ytBlockUsers to avoid
    # collision with bilibili's blockKeywords/blockUsers in the same response.

    # Keys whose change requires disconnect (user must manually reconnect)
    _CONNECTION_KEYS = {'ytUrl'}

    async def update_settings(self, data):
        """Update settings from web UI (camelCase keys). Ignores unknown keys.

        If a connection-related setting actually changed while connected,
        disconnect and notify server via on_status_change(False).
        """
        # Detect connection-related changes before applying
        connection_changed = False
        for key in self._CONNECTION_KEYS:
            if key in data:
                attr, typ = self._SETTINGS_MAP[key]
                if typ(data[key]) != getattr(self, attr):
                    connection_changed = True
                    break

        # Disconnect first (while old values still intact) if needed
        if connection_changed and self.connected:
            await self.disconnect()

        # Then apply all new settings
        for camel, (attr, typ) in self._SETTINGS_MAP.items():
            if camel in data:
                setattr(self, attr, typ(data[camel]))

    def get_state(self):
        """Return live-related state for API (camelCase keys)."""
        return {
            'platform': self.platform,
            'connected': self.connected,
            'ytUrl': self.yt_url,
            'autoForward': self.auto_forward,
            'forwardGifts': self.forward_gifts,
            'received': self.msg_received,
            'ytBlockKeywords': self.block_keywords,
            'ytBlockUsers': self.block_users,
        }

    def get_persist_data(self):
        """Return youtube-specific data for settings.json (snake_case keys).

        Shared settings (platform) are saved by the server at the top level.
        """
        return {
            'auto_forward': self.auto_forward,
            'forward_gifts': self.forward_gifts,
            'url': self.yt_url,
            'block_keywords': self.block_keywords,
            'block_users': self.block_users,
        }
