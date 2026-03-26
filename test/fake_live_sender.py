"""
Fake Live Sender — sends test messages to gateway as if from a live room.

Sends danmaku, gift, super chat, and guard messages via POST /api/send-danmaku.
Tests the full pipeline: gateway → livechat (WebSocket feed) + unity (HTTP forward).

Usage:
    python test/fake_live_sender.py [--gateway http://localhost:8080] [--interval 2]

Modes:
    --mode single    Send one message of each type and exit (default)
    --mode loop      Send random messages in a loop
"""

import json
import time
import random
import logging
import argparse
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('fake-live')

# Sample data for generating fake messages
USERS = ['小明', '小红', '张三', '李四', 'TestUser', 'Viewer_42', '弹幕王']
DANMAKU_TEXTS = [
    '你好呀', '主播唱首歌吧', '哈哈哈哈', '666666', '好厉害',
    '加油', '来了来了', '感谢主播', 'hhh太搞笑了', '问号？',
]
GIFT_NAMES = ['辣条', '小心心', '打call', '礼花', '告白气球', '小电视飞船']
SC_TEXTS = ['主播生日快乐！', '希望主播天天开心', '请问今天玩什么游戏？']
GUARD_LEVELS = {1: 'Governor', 2: 'Admiral', 3: 'Captain'}


def send_to_gateway(gateway_url, payload):
    """POST JSON to gateway /api/send-danmaku."""
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        f'{gateway_url}/api/send-danmaku',
        data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            result = r.read().decode('utf-8')
            logger.info(f'  → {r.status} {result}')
            return True
    except Exception as e:
        logger.error(f'  → Failed: {e}')
        return False


def make_danmaku(user=None, text=None):
    return {
        'msg_type': 'danmaku',
        'user': user or random.choice(USERS),
        'text': text or random.choice(DANMAKU_TEXTS),
        'guard_level': random.choice([0, 0, 0, 3]),  # mostly non-guard
        'face': '',
    }


def make_gift(user=None):
    return {
        'msg_type': 'gift',
        'user': user or random.choice(USERS),
        'text': random.choice(GIFT_NAMES),
        'num': random.randint(1, 10),
        'price': random.choice([0, 0, 1, 6.6, 30]),
        'face': '',
    }


def make_super_chat(user=None, text=None):
    return {
        'msg_type': 'super_chat',
        'user': user or random.choice(USERS),
        'text': text or random.choice(SC_TEXTS),
        'price': random.choice([30, 50, 100, 500]),
        'face': '',
    }


def make_guard(user=None):
    level = random.choice([1, 2, 3])
    return {
        'msg_type': 'guard',
        'user': user or random.choice(USERS),
        'text': GUARD_LEVELS[level],
        'guard_level': level,
        'face': '',
    }


def send_single_set(gateway_url):
    """Send one message of each type."""
    messages = [
        ('danmaku', make_danmaku('小明', '你好呀主播')),
        ('danmaku', make_danmaku('小红', '今天直播什么')),
        ('gift',    make_gift('张三')),
        ('sc',      make_super_chat('李四', '主播加油！')),
        ('guard',   make_guard('Viewer_42')),
    ]
    for label, payload in messages:
        logger.info(f'[{label}] {payload["user"]}: {payload.get("text", "")}')
        send_to_gateway(gateway_url, payload)
        time.sleep(0.5)


def send_loop(gateway_url, interval):
    """Send random messages in a loop."""
    generators = [make_danmaku] * 7 + [make_gift] * 2 + [make_super_chat, make_guard]
    logger.info(f'Sending random messages every {interval}s (Ctrl+C to stop)')
    while True:
        gen = random.choice(generators)
        payload = gen()
        msg_type = payload['msg_type']
        logger.info(f'[{msg_type}] {payload["user"]}: {payload.get("text", "")}')
        send_to_gateway(gateway_url, payload)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='Fake Live Sender for testing')
    parser.add_argument('--gateway', type=str, default='http://localhost:8080',
                        help='Gateway URL (default: http://localhost:8080)')
    parser.add_argument('--mode', choices=['single', 'loop'], default='single',
                        help='single: one set then exit; loop: continuous random messages')
    parser.add_argument('--interval', type=float, default=2.0,
                        help='Seconds between messages in loop mode (default: 2)')
    args = parser.parse_args()

    logger.info(f'Target gateway: {args.gateway}')

    if args.mode == 'single':
        send_single_set(args.gateway)
        logger.info('Done — sent one message of each type')
    else:
        try:
            send_loop(args.gateway, args.interval)
        except KeyboardInterrupt:
            logger.info('Stopped')


if __name__ == '__main__':
    main()
