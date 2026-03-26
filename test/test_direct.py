"""Direct WebSocket test: register, init, connect, send, and wait for response."""
import json
import time
import asyncio
import aiohttp

SERVER = 'http://10.81.7.143:8910'
WS_URL = 'ws://10.81.7.143:8910'
CLIENT_ID = 'test-direct-1'

async def main():
    async with aiohttp.ClientSession() as session:
        # Register
        async with session.post(f'{SERVER}/register/', json={'client_id': CLIENT_ID}) as r:
            print(f'Register: {r.status} {await r.json()}')

        # Init pipeline (force=True to reset history)
        async with session.post(f'{SERVER}/init_pipeline/{CLIENT_ID}', json={'config': 'vtuber_danmaku', 'force': True}) as r:
            print(f'Init: {r.status} {await r.json()}')

        # Connect WebSocket
        ws = await session.ws_connect(f'{WS_URL}/ws/{CLIENT_ID}')
        print(f'WebSocket connected: {not ws.closed}')

        # Send 2 danmaku (min_batch_size=2)
        for i, (text, user) in enumerate([
            ('hello yuchan', 'testUserA'),
            ('sing a song please', 'testUserB'),
        ]):
            msg = {
                'text': text,
                'user': user,
                'msg_type': 'danmaku',
                'guard_level': 0,
                'num': 0,
                'price': 0,
                'signal': '',
                'timestamp': time.time(),
            }
            flat = json.dumps(msg, ensure_ascii=False)
            await ws.send_str(flat)
            print(f'Sent [{i}]: {flat}')

        # Wait for responses (up to 90s)
        print(f'\nWaiting for responses (up to 90s)...')
        start = time.time()
        count = 0
        while time.time() - start < 90:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=10)
            except asyncio.TimeoutError:
                elapsed = time.time() - start
                print(f'[{elapsed:.1f}s] ... still waiting ...')
                continue
            if msg.type == aiohttp.WSMsgType.TEXT:
                count += 1
                elapsed = time.time() - start
                data = msg.data
                try:
                    parsed = json.loads(data)
                    keys = list(parsed.keys())
                    has_audio = 'audio_data' in parsed
                    has_action = 'action' in parsed
                    is_pipeline = has_audio or has_action or 'expression' in parsed
                    tag = 'PIPELINE' if is_pipeline else 'MSG'
                    print(f'[{elapsed:.1f}s] [{tag}] keys={keys}')
                    print(f'  DATA: {data[:500]}')
                except:
                    print(f'[{elapsed:.1f}s] RAW: {data[:200]}')
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                print(f'WebSocket closed/error')
                break

        print(f'\nTotal received: {count} messages in {time.time()-start:.1f}s')
        await ws.close()

asyncio.run(main())
