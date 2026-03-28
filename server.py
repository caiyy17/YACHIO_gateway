"""
YACHIYO Gateway Server

Thin routing layer that connects live receiving modules to output modules:
  live/ (input) → server.py (router) → livechat/ (WebSocket display) + unity/ (forward)

Usage:
    python server.py [--port 8080] [--host 127.0.0.1]
"""

import sys
import io
import json
import uuid
import logging
import argparse
from pathlib import Path

# Fix Windows console encoding for Chinese characters
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from aiohttp import web

from live import create_live
from unity import UnityClient
from livechat import LivechatBroadcaster

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('gateway')

SETTINGS_FILE = Path(__file__).parent / 'settings.json'


def load_settings():
    """Load settings from JSON file."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f'Failed to load settings: {e}')
    return {}


def save_settings(data):
    """Save settings dict to JSON file."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f'Failed to save settings: {e}')


class GatewayServer:
    """Thin routing layer: receives from live modules, dispatches to output modules."""

    def __init__(self, config):
        # Livechat broadcast module (WebSocket output)
        self.livechat = LivechatBroadcaster(config)

        # Live receiving module (input)
        self.live = create_live(
            config,
            on_message=self._handle_live_message,
            on_log=self._handle_log,
            on_status_change=self._handle_live_status,
        )

        # Unity forwarding module (output)
        self.unity = UnityClient(
            config,
            on_log=self._handle_log,
            on_stats=self._handle_unity_stats,
            on_feed=self._handle_unity_feed,
        )

    async def start(self):
        await self.live.start()
        await self.unity.start()

    async def stop(self):
        await self.live.stop()
        await self.unity.stop()

    def _save(self):
        """Persist current settings to file with nested platform configs."""
        data = load_settings()
        data['platform'] = self.live.platform
        # Platform-specific settings nested under platform key
        data[self.live.platform] = self.live.get_persist_data()
        data.update(self.livechat.get_persist_data())
        data.update(self.unity.get_persist_data())
        save_settings(data)

    def get_state(self):
        """Return full state for API / WebSocket initial push.

        Includes 'saved' key with raw settings.json so the UI can
        populate fields for non-active platforms without the server
        needing to know platform-specific field mappings.
        """
        state = {}
        state.update(self.livechat.get_state())
        state.update(self.live.get_state())
        state.update(self.unity.get_state())
        state['saved'] = load_settings()
        return state

    # ─── Callbacks from Live module ───

    async def _handle_live_message(self, msg_type, text, user, *,
                                    guard_level=0, num=0, price=0,
                                    face='', should_forward=True):
        """Route live message to livechat (WebSocket feed) and Unity."""
        await self.livechat.broadcast({
            'type': 'feed',
            'msg_type': msg_type, 'user': user, 'text': text,
            'guard_level': guard_level, 'num': num,
            'price': price, 'face': face,
        })
        if should_forward:
            await self.unity.forward(
                msg_type, text, user,
                guard_level=guard_level, num=num,
                price=price,
            )

    async def _handle_live_status(self, connected, room_id=None, mode=None, error=None):
        """Route live status change to UI."""
        status = {'type': 'status', 'connected': connected}
        if room_id is not None:
            status['roomId'] = room_id
        if mode is not None:
            status['mode'] = mode
        if error is not None:
            status['error'] = error
        await self.livechat.broadcast(status)

    # ─── Callbacks from Unity module ───

    async def _handle_unity_stats(self, forwarded):
        """Route Unity stats update to UI."""
        await self.livechat.broadcast({
            'type': 'stats',
            'received': self.live.msg_received,
            'forwarded': forwarded,
        })

    async def _handle_unity_feed(self, msg_type, user, text):
        """Route Unity pipeline feed to UI."""
        await self.livechat.broadcast({
            'type': 'feed',
            'msg_type': msg_type, 'user': user, 'text': text,
            'guard_level': 0, 'num': 0, 'price': 0, 'face': '',
        })

    # ─── Shared callback ───

    async def _handle_log(self, tag, msg):
        """Route log message to UI."""
        await self.livechat.broadcast({'type': 'log', 'tag': tag, 'msg': msg})


# ─── Settings key mappings (camelCase API → snake_case internal) ───


# ─── HTTP Handlers ───

async def handle_index(request):
    html_path = Path(__file__).parent / 'index.html'
    return web.FileResponse(html_path)


async def handle_api_state(request):
    gw = request.app['gateway']
    return web.json_response(gw.get_state())


async def handle_api_connect(request):
    gw = request.app['gateway']
    ok = await gw.live.connect()
    gw._save()
    return web.json_response({'connected': ok})


async def handle_api_disconnect(request):
    gw = request.app['gateway']
    await gw.live.disconnect()
    return web.json_response({'connected': False})


async def handle_api_unity_toggle(request):
    gw = request.app['gateway']
    connected = gw.unity.toggle_connect()
    return web.json_response({'connected': connected})


async def handle_api_settings(request):
    gw = request.app['gateway']
    data = await request.json()

    # Platform switch: hot-swap live module if platform changed
    new_platform = data.get('platform')
    if new_platform and new_platform != gw.live.platform:
        await gw.live.stop()
        saved_config = load_settings()
        saved_config['platform'] = new_platform
        gw.live = create_live(
            saved_config,
            on_message=gw._handle_live_message,
            on_log=gw._handle_log,
            on_status_change=gw._handle_live_status,
        )
        await gw.live.start()

    # Livechat settings
    if 'customCss' in data:
        gw.livechat.update_settings({'custom_css': data['customCss']})
        await gw.livechat.broadcast({'type': 'css_update'})

    # Live settings
    await gw.live.update_settings(data)

    # Unity settings
    gw.unity.update_settings(data)

    gw._save()
    return web.json_response(gw.get_state())


async def handle_api_send(request):
    gw = request.app['gateway']
    body = await request.json()
    status, result = await gw.unity.send_raw(body)
    return web.json_response({'status': status, 'result': result})


async def handle_api_send_danmaku(request):
    """Send structured danmaku message through the same path as live messages."""
    gw = request.app['gateway']
    body = await request.json()
    face = body.get('face', '') or '/uploads/avatars/noface.jpg'
    await gw._handle_live_message(
        body.get('msg_type', 'danmaku'),
        body.get('text', ''),
        body.get('user', ''),
        guard_level=body.get('guard_level', 0),
        num=body.get('num', 0),
        price=body.get('price', 0),
        face=face,
        should_forward=True,
    )
    return web.json_response({'status': 'ok'})


async def handle_api_pipeline_event(request):
    """Receive pipeline output events from Unity's ExternalMessageManager."""
    gw = request.app['gateway']
    data = await request.json()
    await gw.unity.handle_pipeline_event(data)
    return web.json_response({'status': 'ok'})


async def handle_livechat_index(request):
    """Serve livechat overlay page."""
    html_path = Path(__file__).parent / 'livechat' / 'index.html'
    return web.FileResponse(html_path)


AVATAR_SIZE = 300
AVATAR_DIR = Path(__file__).parent / 'uploads' / 'avatars'


async def handle_api_upload_avatar(request):
    """Upload avatar image, resize to 300x300, save as JPEG, return URL."""
    from PIL import Image

    reader = await request.multipart()
    field = await reader.next()
    if not field or field.name != 'file':
        return web.json_response({'error': 'No file field'}, status=400)

    data = await field.read(limit=5 * 1024 * 1024)  # 5MB max
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert('RGB')
        img = img.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    except Exception as e:
        return web.json_response({'error': f'Invalid image: {e}'}, status=400)

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    original_name = Path(field.filename).stem if field.filename else uuid.uuid4().hex[:12]
    filename = f'{original_name}.jpg'
    filepath = AVATAR_DIR / filename
    img.save(filepath, 'JPEG', quality=85)

    url = f'/uploads/avatars/{filename}'
    return web.json_response({'url': url})


async def handle_api_list_avatars(request):
    """List saved avatar files."""
    avatars = []
    if AVATAR_DIR.exists():
        for f in sorted(AVATAR_DIR.iterdir()):
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif'):
                avatars.append({'name': f.stem, 'url': f'/uploads/avatars/{f.name}'})
    return web.json_response(avatars)


async def handle_livechat_custom_css(request):
    """Serve user-configured custom CSS content."""
    gw = request.app['gateway']
    return web.Response(text=gw.livechat.custom_css or '', content_type='text/css')


async def handle_ws(request):
    gw = request.app['gateway']
    return await gw.livechat.handle_ws(request, gw.get_state())


def create_app(config):
    app = web.Application()
    gw = GatewayServer(config)
    app['gateway'] = gw

    app.router.add_get('/', handle_index)
    app.router.add_get('/api/state', handle_api_state)
    app.router.add_post('/api/connect', handle_api_connect)
    app.router.add_post('/api/disconnect', handle_api_disconnect)
    app.router.add_post('/api/unity-toggle', handle_api_unity_toggle)
    app.router.add_post('/api/settings', handle_api_settings)
    app.router.add_post('/api/send', handle_api_send)
    app.router.add_post('/api/send-danmaku', handle_api_send_danmaku)
    app.router.add_post('/api/pipeline-event', handle_api_pipeline_event)
    app.router.add_post('/api/upload-avatar', handle_api_upload_avatar)
    app.router.add_get('/api/avatars', handle_api_list_avatars)
    app.router.add_get('/livechat/', handle_livechat_index)
    app.router.add_get('/livechat-custom.css', handle_livechat_custom_css)
    app.router.add_get('/ws', handle_ws)

    # Static files
    livechat_path = Path(__file__).parent / 'livechat'
    app.router.add_static('/livechat', livechat_path)
    uploads_path = Path(__file__).parent / 'uploads'
    uploads_path.mkdir(exist_ok=True)
    app.router.add_static('/uploads', uploads_path)

    async def on_startup(app):
        await gw.start()

    async def on_shutdown(app):
        await gw.stop()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


def main():
    parser = argparse.ArgumentParser(description='YACHIYO Gateway Server')
    parser.add_argument('--port', type=int, default=8080, help='Server port (default: 8080)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Server host (default: 127.0.0.1)')
    args = parser.parse_args()

    config = load_settings()
    app = create_app(config)
    logger.info(f'Starting gateway on http://{args.host}:{args.port}')
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == '__main__':
    main()
