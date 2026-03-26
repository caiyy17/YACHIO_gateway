"""
Fake Unity Receiver

Simulates Unity's ExternalMessageReceiver + WebSocketClientModule + WebSocketClient
for testing the gateway → server pipeline without running Unity.

Accepts HTTP POST /send (like ExternalMessageReceiver on port 7890),
transforms YYMessage to flat JSON (like WebSocketClientModule),
and forwards via WebSocket to the YACHIO server.

Usage:
    python fake_receiver.py [--port 7891] [--server ws://10.81.7.143:8910] [--client-id test-id-1]
"""

import sys
import json
import time
import asyncio
import logging
import argparse

import aiohttp
from aiohttp import web, WSMsgType

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('fake-receiver')


class FakeUnityReceiver:
    def __init__(self, server_url, client_id):
        self.server_url = server_url
        self.client_id = client_id
        self._ws = None
        self._session = None
        self._connected = False
        self._receive_task = None
        self.sent_messages = []
        self.received_messages = []

    async def start(self):
        self._session = aiohttp.ClientSession()
        await self._register_and_init()
        await self._connect_ws()

    async def _register_and_init(self):
        """Register client and init pipeline on the server (required before WebSocket)."""
        base_url = self.server_url.replace('ws://', 'http://').replace('wss://', 'https://')

        # Step 1: Register client
        try:
            async with self._session.post(
                f'{base_url}/register/',
                json={'client_id': self.client_id},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                logger.info(f'Register: {resp.status} {result}')
        except Exception as e:
            logger.error(f'Register failed: {e}')
            return

        # Step 2: Init pipeline
        try:
            async with self._session.post(
                f'{base_url}/init_pipeline/{self.client_id}',
                json={'config': 'vtuber_danmaku'},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                result = await resp.json()
                logger.info(f'Init pipeline: {resp.status} {result}')
        except Exception as e:
            logger.error(f'Init pipeline failed: {e}')

    async def stop(self):
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def _connect_ws(self):
        ws_url = f'{self.server_url}/ws/{self.client_id}'
        try:
            self._ws = await self._session.ws_connect(ws_url, timeout=20)
            self._connected = True
            logger.info(f'WebSocket connected to {ws_url}')
            self._receive_task = asyncio.ensure_future(self._receive_loop())
        except Exception as e:
            logger.error(f'WebSocket connection failed: {e}')
            self._connected = False
            asyncio.ensure_future(self._reconnect())

    async def _reconnect(self):
        """Auto-reconnect with backoff."""
        delay = 3
        while not self._connected:
            logger.info(f'Reconnecting in {delay}s...')
            await asyncio.sleep(delay)
            try:
                await self._register_and_init()
                await self._connect_ws()
                if self._connected:
                    logger.info('Reconnected successfully')
                    return
            except Exception as e:
                logger.error(f'Reconnect failed: {e}')
            delay = min(delay * 2, 30)

    async def _receive_loop(self):
        """Receive messages from server and log them."""
        try:
            async for msg in self._ws:
                if msg.type == WSMsgType.TEXT:
                    self.received_messages.append({
                        'time': time.time(),
                        'data': msg.data
                    })
                    logger.info(f'[FROM SERVER] {msg.data}')
                    print(f'[FROM SERVER] {msg.data}', flush=True)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f'WebSocket error: {self._ws.exception()}')
                    break
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f'Receive loop error: {e}')
        finally:
            self._connected = False
            logger.info('WebSocket disconnected from server')
            asyncio.ensure_future(self._reconnect())

    async def forward_message(self, yy_message_json):
        """
        Transform YYMessage (as Unity's WebSocketClientModule does) and send via WebSocket.

        WebSocketClientModule.ProcessMessage logic:
        1. Parse YYMessage.content as JSON dict
        2. Merge signal and timestamp into the dict
        3. Serialize and send
        """
        try:
            yy_msg = json.loads(yy_message_json)
        except json.JSONDecodeError as e:
            logger.error(f'Invalid JSON: {e}')
            return False

        signal = yy_msg.get('signal', '')
        content_str = yy_msg.get('content', '{}')
        timestamp = yy_msg.get('timestamp', time.time())

        # Parse content string into dict
        try:
            content_dict = json.loads(content_str)
        except json.JSONDecodeError:
            content_dict = {'raw': content_str}

        # Merge signal and timestamp (like WebSocketClientModule)
        if 'signal' not in content_dict:
            content_dict['signal'] = signal
        if 'timestamp' not in content_dict:
            content_dict['timestamp'] = timestamp

        flat_json = json.dumps(content_dict, ensure_ascii=False)
        self.sent_messages.append({
            'time': time.time(),
            'data': flat_json
        })
        logger.info(f'[TO SERVER] {flat_json}')
        print(f'[TO SERVER] {flat_json}', flush=True)

        if not self._connected or self._ws is None or self._ws.closed:
            logger.error('WebSocket not connected, cannot forward')
            return False

        try:
            await self._ws.send_str(flat_json)
            return True
        except Exception as e:
            logger.error(f'Send error: {e}')
            return False


# ─── HTTP Handlers ───

async def handle_send(request):
    """POST /send — accepts YYMessage JSON, forwards to server via WebSocket."""
    receiver = request.app['receiver']
    try:
        body = await request.text()
        logger.info(f'[HTTP POST /send] {body}')

        ok = await receiver.forward_message(body)
        if ok:
            return web.json_response({'status': 'forwarded'})
        else:
            return web.json_response({'status': 'failed', 'error': 'ws not connected'}, status=502)
    except Exception as e:
        logger.error(f'Handle send error: {e}')
        return web.json_response({'status': 'error', 'error': str(e)}, status=500)


async def handle_received(request):
    """GET /received — show messages received from server."""
    receiver = request.app['receiver']
    return web.json_response({
        'sent_count': len(receiver.sent_messages),
        'received_count': len(receiver.received_messages),
        'received': receiver.received_messages[-20:],  # last 20
    })


async def handle_health(request):
    receiver = request.app['receiver']
    return web.json_response({
        'status': 'ok',
        'ws_connected': receiver._connected,
        'server_url': receiver.server_url,
        'sent_count': len(receiver.sent_messages),
        'received_count': len(receiver.received_messages),
    })


def create_app(server_url, client_id):
    app = web.Application()
    receiver = FakeUnityReceiver(server_url, client_id)
    app['receiver'] = receiver

    app.router.add_post('/send', handle_send)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/received', handle_received)

    async def on_startup(app):
        await receiver.start()

    async def on_shutdown(app):
        await receiver.stop()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


def main():
    parser = argparse.ArgumentParser(description='Fake Unity Receiver for testing')
    parser.add_argument('--port', type=int, default=7891,
                        help='HTTP server port (default: 7891)')
    parser.add_argument('--server', type=str, default='ws://10.81.7.143:8910',
                        help='YACHIO server WebSocket URL')
    parser.add_argument('--client-id', type=str, default='test-id-1',
                        help='WebSocket client ID')
    args = parser.parse_args()

    app = create_app(args.server, args.client_id)
    logger.info(f'Starting fake receiver on http://localhost:{args.port}')
    logger.info(f'Forwarding to {args.server}/ws/{args.client_id}')
    web.run_app(app, host='127.0.0.1', port=args.port, print=None)


if __name__ == '__main__':
    main()
