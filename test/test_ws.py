import asyncio, aiohttp

async def test():
    async with aiohttp.ClientSession() as s:
        try:
            ws = await s.ws_connect('ws://10.81.7.143:8910/ws/test-id-1', timeout=5)
            print(f'Connected! Closed: {ws.closed}')
            await ws.close()
            print('Closed OK')
        except Exception as e:
            print(f'Error: {type(e).__name__}: {e}')

asyncio.run(test())
