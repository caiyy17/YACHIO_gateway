"""
Fake Unity Receiver — simulates Unity's ExternalMessageManager for testing.

Accepts HTTP POST /send from the gateway and logs received messages.
No real YACHIO server connection needed.

Usage:
    python test/fake_unity_receiver.py [--port 7891]

Then configure gateway's Unity endpoint to http://localhost:7891/send
"""

import json
import time
import logging
import argparse

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('fake-unity')


class FakeUnity:
    def __init__(self):
        self.received = []

    def add(self, data):
        entry = {'time': time.strftime('%H:%M:%S'), 'data': data}
        self.received.append(entry)
        # Keep last 200
        if len(self.received) > 200:
            self.received = self.received[-200:]


async def handle_send(request):
    """POST /send — accept YYMessage from gateway, log it."""
    unity = request.app['unity']
    try:
        body = await request.json()
        unity.add(body)

        # Parse content for display
        content_str = body.get('content', '{}')
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            content = {'raw': content_str}

        user = content.get('user', '?')
        text = content.get('text', '')
        msg_type = content.get('msg_type', '?')
        signal = content.get('signal', body.get('signal', ''))

        if signal:
            logger.info(f'[RECV] signal={signal} dest={body.get("destination", "?")}')
        else:
            logger.info(f'[RECV] [{msg_type}] {user}: {text}')

        return web.json_response({'status': 'received'})
    except Exception as e:
        logger.error(f'Error: {e}')
        return web.json_response({'status': 'error', 'error': str(e)}, status=500)


async def handle_received(request):
    """GET /received — show received messages."""
    unity = request.app['unity']
    return web.json_response({
        'count': len(unity.received),
        'messages': unity.received[-50:],
    })


async def handle_health(request):
    unity = request.app['unity']
    return web.json_response({
        'status': 'ok',
        'received_count': len(unity.received),
    })


def main():
    parser = argparse.ArgumentParser(description='Fake Unity Receiver for testing')
    parser.add_argument('--port', type=int, default=7891, help='HTTP port (default: 7891)')
    args = parser.parse_args()

    app = web.Application()
    app['unity'] = FakeUnity()
    app.router.add_post('/send', handle_send)
    app.router.add_get('/received', handle_received)
    app.router.add_get('/health', handle_health)

    logger.info(f'Fake Unity receiver on http://localhost:{args.port}')
    logger.info(f'Configure gateway Unity endpoint to http://localhost:{args.port}/send')
    web.run_app(app, host='127.0.0.1', port=args.port, print=None)


if __name__ == '__main__':
    main()
