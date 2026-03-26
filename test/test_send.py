"""Send test danmaku through gateway with proper UTF-8 encoding."""
import json
import urllib.request

GATEWAY = 'http://localhost:8080'

def send_danmaku(text, user):
    content_obj = {
        'text': text,
        'user': user,
        'msg_type': 'danmaku',
        'guard_level': 0,
        'num': 0,
        'price': 0,
        'destination': -2,
    }
    yy_message = {
        'signal': '',
        'content': json.dumps(content_obj, ensure_ascii=False),
        'destination': 0,
    }
    data = json.dumps(yy_message, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        f'{GATEWAY}/api/send',
        data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'},
    )
    with urllib.request.urlopen(req) as r:
        print(f'Sent "{text}" by {user}: {r.read().decode()}')

send_danmaku('优酱你好呀', '小明')
send_danmaku('给我们唱首歌吧', '小红')
