"""
Bilibili Live receiving module.

Connects to Bilibili live rooms via blivedm (web/guest/Open Live modes),
applies block rules, and emits normalized messages via callbacks.
"""

import sys
import asyncio
import logging
from pathlib import Path

import aiohttp

# Add blivedm submodule to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'blivedm'))

import blivedm
import blivedm.models.web as web_models
import blivedm.models.open_live as open_models

logger = logging.getLogger('live.bilibili')


# Fix aiohttp bug: _wait_released can throw CancelledError when connection drops,
# which silently kills the task. Convert to ClientConnectionError so blivedm can catch it.
# (Copied from blivechat's utils/request.py)
class _CustomClientResponse(aiohttp.ClientResponse):
    async def _wait_released(self):
        try:
            return await super()._wait_released()
        except asyncio.CancelledError as e:
            raise aiohttp.ClientConnectionError('Connection released') from e


class BilibiliLive:
    """Bilibili live room connection and message receiving with block rules."""

    def __init__(self, config, *, on_message, on_log, on_status_change):
        """
        Args:
            config: dict with bilibili-related settings
            on_message: async callback(msg_type, text, user, *, guard_level, num, price, face, should_forward)
            on_log: async callback(tag, msg)
            on_status_change: async callback(connected, room_id=None, mode=None, error=None)
        """
        self._on_message = on_message
        self._on_log = on_log
        self._on_status_change = on_status_change

        # Credentials
        self.sessdata = config.get('sessdata', '')
        self.open_live_key_id = config.get('open_live_key_id', '')
        self.open_live_key_secret = config.get('open_live_key_secret', '')
        self.open_live_app_id = config.get('open_live_app_id', 0)

        # Connection state
        self._live_client = None
        self._guest_session = None
        self.connected = False
        self.room_id = config.get('room_id') or ''
        self.auth_code = config.get('auth_code') or ''
        self.connect_mode = config.get('connect_mode') or 'guest'

        # Settings
        self.auto_forward = config.get('auto_forward', True)
        self.forward_gifts = config.get('forward_gifts', True)

        # Block rules
        self.block_gift_danmaku = config.get('block_gift_danmaku', False)
        self.block_level = config.get('block_level', 0)
        self.block_newbie = config.get('block_newbie', False)
        self.block_not_mobile_verified = config.get('block_not_mobile_verified', False)
        self.block_medal_level = config.get('block_medal_level', 0)
        self.block_keywords = config.get('block_keywords', '')
        self.block_users = config.get('block_users', '')
        self.block_mirror_messages = config.get('block_mirror_messages', False)

        # Stats
        self.msg_received = 0

        # Platform identifier (used by create_live factory)
        self.platform = 'bilibili'

        # Session
        self._bili_session = None

    async def start(self):
        """No-op at startup. Session is created in connect()."""
        pass

    async def stop(self):
        """Disconnect and close session. Call at app shutdown."""
        await self.disconnect()
        if self._bili_session:
            await self._bili_session.close()
            self._bili_session = None

    async def _create_bili_session(self):
        """Create/recreate bilibili session with current SESSDATA."""
        if self._bili_session:
            await self._bili_session.close()
        cookie_jar = aiohttp.CookieJar()
        if self.sessdata:
            cookie_jar.update_cookies({'SESSDATA': self.sessdata})
        self._bili_session = aiohttp.ClientSession(
            cookie_jar=cookie_jar,
            response_class=_CustomClientResponse,
            timeout=aiohttp.ClientTimeout(total=10),
        )

    # ─── Connection ───

    async def connect(self):
        """Connect using current settings. Returns True on success."""
        if self.connected:
            await self.disconnect()

        self.msg_received = 0
        mode = self.connect_mode or 'guest'

        if mode == 'open_live':
            if not self.auth_code:
                await self._on_status_change(False, error='authCode required')
                return False
            return await self._connect_open_live(self.auth_code)
        else:
            if not self.room_id:
                await self._on_status_change(False, error='roomId required')
                return False
            if mode == 'guest':
                return await self._connect_guest(self.room_id)
            # Rebuild session with current sessdata before connecting
            await self._create_bili_session()
            return await self._connect_web(self.room_id)

    async def _connect_guest(self, room_id):
        try:
            self._guest_session = aiohttp.ClientSession(
                response_class=_CustomClientResponse,
                timeout=aiohttp.ClientTimeout(total=10),
            )
            self._live_client = blivedm.BLiveClient(
                int(room_id), session=self._guest_session,
            )
            self._live_client.set_handler(_DanmakuHandler(self))
            self._live_client.start()
            self.connected = True
            logger.info(f'[guest] Connecting to room {room_id}')
            await self._on_status_change(True, room_id=room_id, mode='guest')
            return True
        except Exception as e:
            logger.error(f'Failed to connect (guest): {e}')
            self.connected = False
            await self._on_status_change(False, error=str(e))
            return False

    async def _connect_web(self, room_id):
        try:
            self._live_client = blivedm.BLiveClient(
                int(room_id), session=self._bili_session,
            )
            self._live_client.set_handler(_DanmakuHandler(self))
            self._live_client.start()
            self.connected = True
            logger.info(f'[web] Connecting to room {room_id}')
            await self._on_status_change(True, room_id=room_id, mode='web')
            return True
        except Exception as e:
            logger.error(f'Failed to connect (web): {e}')
            self.connected = False
            await self._on_status_change(False, error=str(e))
            return False

    async def _connect_open_live(self, auth_code):
        if not all([self.open_live_key_id, self.open_live_key_secret, self.open_live_app_id]):
            err = 'Open Live credentials not configured (key_id, key_secret, app_id)'
            logger.error(err)
            await self._on_status_change(False, error=err)
            return False

        try:
            self._live_client = blivedm.OpenLiveClient(
                access_key_id=self.open_live_key_id,
                access_key_secret=self.open_live_key_secret,
                app_id=self.open_live_app_id,
                room_owner_auth_code=auth_code,
            )
            self._live_client.set_handler(_OpenLiveHandler(self))
            self._live_client.start()
            self.connected = True
            logger.info(f'[open_live] Connecting with auth code {auth_code[:8]}...')
            await self._on_status_change(True, room_id=auth_code[:8] + '...', mode='open_live')
            return True
        except Exception as e:
            logger.error(f'Failed to connect (open_live): {e}')
            self.connected = False
            await self._on_status_change(False, error=str(e))
            return False

    async def disconnect(self):
        if self._live_client:
            if self.connect_mode == 'open_live' and hasattr(self._live_client, 'stop_and_close'):
                await self._live_client.stop_and_close()
            else:
                self._live_client.stop()
                try:
                    await self._live_client.join()
                except Exception:
                    pass
            self._live_client = None
        if self._guest_session:
            await self._guest_session.close()
            self._guest_session = None
        self.connected = False
        logger.info('Disconnected from bilibili')
        await self._on_status_change(False)

    # ─── Settings ───

    # camelCase key → (attr_name, type)
    _SETTINGS_MAP = {
        'sessdata': ('sessdata', str),
        'connectMode': ('connect_mode', str),
        'roomId': ('room_id', str),
        'authCode': ('auth_code', str),
        'autoForward': ('auto_forward', bool),
        'forwardGifts': ('forward_gifts', bool),
        'openLiveKeyId': ('open_live_key_id', str),
        'openLiveKeySecret': ('open_live_key_secret', str),
        'openLiveAppId': ('open_live_app_id', int),
        'blockGiftDanmaku': ('block_gift_danmaku', bool),
        'blockLevel': ('block_level', int),
        'blockNewbie': ('block_newbie', bool),
        'blockNotMobileVerified': ('block_not_mobile_verified', bool),
        'blockMedalLevel': ('block_medal_level', int),
        'blockKeywords': ('block_keywords', str),
        'blockUsers': ('block_users', str),
        'blockMirrorMessages': ('block_mirror_messages', bool),
    }

    # Keys whose change requires disconnect (user must manually reconnect)
    _CONNECTION_KEYS = {'connectMode', 'roomId', 'authCode', 'sessdata',
                        'openLiveKeyId', 'openLiveKeySecret', 'openLiveAppId'}

    async def update_settings(self, data):
        """Update settings from web UI (camelCase keys). Ignores unknown keys.

        If a connection-related setting actually changed while connected,
        disconnect and notify server via on_status_change(False).
        """
        # Detect connection-related changes before applying
        connection_changed = False
        for key in self._CONNECTION_KEYS:
            if key not in data:
                continue
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
            'roomId': self.room_id,
            'authCode': self.auth_code,
            'connectMode': self.connect_mode,
            'autoForward': self.auto_forward,
            'forwardGifts': self.forward_gifts,
            'sessdata': self.sessdata,
            'openLiveKeyId': self.open_live_key_id,
            'openLiveKeySecret': self.open_live_key_secret,
            'openLiveAppId': self.open_live_app_id,
            'received': self.msg_received,
            'blockGiftDanmaku': self.block_gift_danmaku,
            'blockLevel': self.block_level,
            'blockNewbie': self.block_newbie,
            'blockNotMobileVerified': self.block_not_mobile_verified,
            'blockMedalLevel': self.block_medal_level,
            'blockKeywords': self.block_keywords,
            'blockUsers': self.block_users,
            'blockMirrorMessages': self.block_mirror_messages,
        }

    def get_persist_data(self):
        """Return bilibili-specific data for settings.json (snake_case keys).

        Shared settings (platform) are saved by the server at the top level.
        """
        return {
            'auto_forward': self.auto_forward,
            'forward_gifts': self.forward_gifts,
            'sessdata': self.sessdata,
            'open_live_key_id': self.open_live_key_id,
            'open_live_key_secret': self.open_live_key_secret,
            'open_live_app_id': self.open_live_app_id,
            'room_id': self.room_id,
            'auth_code': self.auth_code,
            'connect_mode': self.connect_mode,
            'block_gift_danmaku': self.block_gift_danmaku,
            'block_level': self.block_level,
            'block_newbie': self.block_newbie,
            'block_not_mobile_verified': self.block_not_mobile_verified,
            'block_medal_level': self.block_medal_level,
            'block_keywords': self.block_keywords,
            'block_users': self.block_users,
            'block_mirror_messages': self.block_mirror_messages,
        }


# ─── Block Rule Helpers ───

def _match_keywords(block_keywords, text):
    """Check if text contains any blocked keyword."""
    if not block_keywords or not text:
        return False
    text_lower = text.lower()
    for kw in block_keywords.split('\n'):
        kw = kw.strip().lower()
        if kw and kw in text_lower:
            return True
    return False


def _match_users(block_users, uname):
    """Check if username is in blocked users list."""
    if not block_users:
        return False
    name_lower = uname.lower()
    for user in block_users.split('\n'):
        user = user.strip().lower()
        if user and user == name_lower:
            return True
    return False


# ─── blivedm Handlers ───

class _DanmakuHandler(blivedm.BaseHandler):
    """Handles blivedm web/guest mode events."""

    def __init__(self, live: BilibiliLive):
        self._live = live

    def _run(self, coro):
        asyncio.ensure_future(coro)

    def _should_block_danmaku(self, message: web_models.DanmakuMessage):
        live = self._live
        if live.block_gift_danmaku and message.msg_type == 1:
            return True
        if live.block_mirror_messages and message.is_mirror:
            return True
        if live.block_level > 0 and message.user_level < live.block_level:
            return True
        if live.block_newbie and message.urank < 10000:
            return True
        if live.block_not_mobile_verified and not message.mobile_verify:
            return True
        if live.block_medal_level > 0:
            if message.medal_room_id != int(live.room_id or 0) or message.medal_level < live.block_medal_level:
                return True
        if _match_keywords(live.block_keywords, message.msg):
            return True
        if _match_users(live.block_users, message.uname):
            return True
        return False

    def _on_danmaku(self, client, message: web_models.DanmakuMessage):
        if message.dm_type == 1:  # emoticon, skip
            return

        self._live.msg_received += 1
        if self._should_block_danmaku(message):
            self._run(self._live._on_log('blocked', f'{message.uname}: {message.msg}'))
            logger.info(f'[blocked] {message.uname}: {message.msg}')
            return

        self._run(self._live._on_log('danmaku', f'{message.uname}: {message.msg}'))
        logger.info(f'[danmaku] {message.uname}: {message.msg}')
        self._run(self._live._on_message(
            'danmaku', message.msg, message.uname,
            guard_level=message.privilege_type, face=message.face,
            should_forward=self._live.auto_forward,
        ))

    def _on_gift(self, client, message: web_models.GiftMessage):
        price = message.total_coin / 1000 if message.coin_type == 'gold' else 0

        self._live.msg_received += 1
        self._run(self._live._on_log(
            'gift',
            f'{message.uname} {message.action} {message.gift_name} x{message.num} (¥{price})'
        ))
        logger.info(f'[gift] {message.uname}: {message.gift_name} x{message.num} (¥{price})')
        self._run(self._live._on_message(
            'gift', message.gift_name, message.uname,
            num=message.num, price=price, face=message.face,
            should_forward=self._live.auto_forward and self._live.forward_gifts,
        ))

    def _on_user_toast_v2(self, client, message: web_models.UserToastV2Message):
        if message.source == 2:  # gifted membership, skip
            return

        guard_names = {1: 'Governor', 2: 'Admiral', 3: 'Captain'}
        guard_name = guard_names.get(message.guard_level, f'guard_{message.guard_level}')
        price = message.price * message.num / 1000

        self._live.msg_received += 1
        if _match_users(self._live.block_users, message.username):
            return

        self._run(self._live._on_log('member', f'{message.username} became {guard_name} x{message.num} (¥{price})'))
        logger.info(f'[member] {message.username}: {guard_name} x{message.num} (¥{price})')
        self._run(self._live._on_message(
            'guard', guard_name, message.username,
            guard_level=message.guard_level, num=message.num, price=price,
            should_forward=self._live.auto_forward and self._live.forward_gifts,
        ))

    def _on_super_chat(self, client, message: web_models.SuperChatMessage):
        self._live.msg_received += 1
        if _match_keywords(self._live.block_keywords, message.message) or \
           _match_users(self._live.block_users, message.uname):
            return

        self._run(self._live._on_log('sc', f'[SC ¥{message.price}] {message.uname}: {message.message}'))
        logger.info(f'[SC ¥{message.price}] {message.uname}: {message.message}')
        self._run(self._live._on_message(
            'super_chat', message.message, message.uname,
            price=message.price, face=message.face,
            should_forward=self._live.auto_forward and self._live.forward_gifts,
        ))

    def _on_interact_word_v2(self, client, message: web_models.InteractWordV2Message):
        type_names = {1: 'entered', 2: 'followed', 3: 'shared', 4: 'special-followed', 5: 'mutual-followed', 6: 'liked'}
        action = type_names.get(message.msg_type, f'interact_{message.msg_type}')

        self._live.msg_received += 1
        self._run(self._live._on_log('danmaku', f'{message.username} {action}'))
        logger.info(f'[interact] {message.username} {action}')

    def on_client_stopped(self, client, exception):
        self._live.connected = False
        self._run(self._live._on_status_change(False))
        if exception:
            logger.error(f'blivedm client stopped with error: {exception}')
        else:
            logger.info('blivedm client stopped')


class _OpenLiveHandler(blivedm.BaseHandler):
    """Handles Open Live (主播码) events."""

    def __init__(self, live: BilibiliLive):
        self._live = live

    def _run(self, coro):
        asyncio.ensure_future(coro)

    def _should_block_danmaku(self, message: open_models.DanmakuMessage):
        live = self._live
        if live.block_mirror_messages and message.is_mirror:
            return True
        if live.block_medal_level > 0 and message.fans_medal_level < live.block_medal_level:
            return True
        if _match_keywords(live.block_keywords, message.msg):
            return True
        if _match_users(live.block_users, message.uname):
            return True
        return False

    def _on_open_live_danmaku(self, client, message: open_models.DanmakuMessage):
        self._live.msg_received += 1
        if self._should_block_danmaku(message):
            self._run(self._live._on_log('blocked', f'{message.uname}: {message.msg}'))
            logger.info(f'[blocked] {message.uname}: {message.msg}')
            return

        self._run(self._live._on_log('danmaku', f'{message.uname}: {message.msg}'))
        logger.info(f'[danmaku] {message.uname}: {message.msg}')
        self._run(self._live._on_message(
            'danmaku', message.msg, message.uname,
            guard_level=message.guard_level, face=message.uface,
            should_forward=self._live.auto_forward,
        ))

    def _on_open_live_gift(self, client, message: open_models.GiftMessage):
        price = message.price * message.gift_num / 1000 if message.paid else 0

        self._live.msg_received += 1
        self._run(self._live._on_log(
            'gift',
            f'{message.uname} sent {message.gift_name} x{message.gift_num} (¥{price})'
        ))
        logger.info(f'[gift] {message.uname}: {message.gift_name} x{message.gift_num} (¥{price})')
        self._run(self._live._on_message(
            'gift', message.gift_name, message.uname,
            num=message.gift_num, price=price, face=message.uface,
            should_forward=self._live.auto_forward and self._live.forward_gifts,
        ))

    def _on_open_live_buy_guard(self, client, message: open_models.GuardBuyMessage):
        guard_names = {1: 'Governor', 2: 'Admiral', 3: 'Captain'}
        guard_name = guard_names.get(message.guard_level, f'guard_{message.guard_level}')
        price = message.price / 1000

        self._live.msg_received += 1
        if _match_users(self._live.block_users, message.user_info.uname):
            return

        self._run(self._live._on_log('member', f'{message.user_info.uname} became {guard_name} x{message.guard_num} (¥{price})'))
        logger.info(f'[member] {message.user_info.uname}: {guard_name} x{message.guard_num} (¥{price})')
        self._run(self._live._on_message(
            'guard', guard_name, message.user_info.uname,
            guard_level=message.guard_level, num=message.guard_num, price=price,
            face=message.user_info.uface,
            should_forward=self._live.auto_forward and self._live.forward_gifts,
        ))

    def _on_open_live_super_chat(self, client, message: open_models.SuperChatMessage):
        self._live.msg_received += 1
        if _match_keywords(self._live.block_keywords, message.message) or \
           _match_users(self._live.block_users, message.uname):
            return

        self._run(self._live._on_log('sc', f'[SC ¥{message.rmb}] {message.uname}: {message.message}'))
        logger.info(f'[SC ¥{message.rmb}] {message.uname}: {message.message}')
        self._run(self._live._on_message(
            'super_chat', message.message, message.uname,
            price=message.rmb, face=message.uface,
            should_forward=self._live.auto_forward and self._live.forward_gifts,
        ))

    def _on_open_live_like(self, client, message: open_models.LikeMessage):
        self._live.msg_received += 1
        self._run(self._live._on_log('danmaku', f'{message.uname} liked'))

    def _on_open_live_enter_room(self, client, message: open_models.RoomEnterMessage):
        self._live.msg_received += 1
        self._run(self._live._on_log('danmaku', f'{message.uname} entered'))

    def on_client_stopped(self, client, exception):
        self._live.connected = False
        self._run(self._live._on_status_change(False))
        if exception:
            logger.error(f'OpenLive client stopped with error: {exception}')
        else:
            logger.info('OpenLive client stopped')
