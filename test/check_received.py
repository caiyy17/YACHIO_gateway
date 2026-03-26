"""Check received messages from fake receiver."""
import json, urllib.request, pathlib

with urllib.request.urlopen('http://localhost:7891/received') as r:
    d = json.loads(r.read().decode('utf-8'))

lines = []
lines.append(f'sent: {d["sent_count"]}, received: {d["received_count"]}')
for i, m in enumerate(d['received']):
    data = json.loads(m['data'])
    signal = data.get('signal', '')
    text = data.get('text', '')[:40]
    audio = len(data.get('audio_data', ''))
    expr = data.get('expression', '')
    act = data.get('action_hint', '') or data.get('action', '')
    if signal:
        lines.append(f'  [{i}] signal={signal}')
    else:
        lines.append(f'  [{i}] PIPELINE text={text} audio={audio}b expr={expr} action={act}')

out = pathlib.Path(__file__).parent / 'test_results.txt'
out.write_text('\n'.join(lines), encoding='utf-8')
print(f'Results written to {out}')
