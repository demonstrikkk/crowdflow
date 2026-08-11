import io
import os
import sys
import time

sys.path.insert(0, 'C:/Users/asus/Downloads/crowdflow/backend')

env_path = 'C:/Users/asus/Downloads/crowdflow/backend/.env'
if os.path.exists(env_path):
    for line in open(env_path, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

from PIL import Image, ImageDraw

img = Image.new('RGB', (800, 600), (40, 60, 90))
d = ImageDraw.Draw(img)
for x in range(60, 760, 90):
    for y in range(120, 560, 110):
        d.ellipse([x, y - 28, x + 26, y], fill=(220, 180, 140))
        d.rectangle([x - 6, y, x + 32, y + 62], fill=(120, 140, 190))
buf = io.BytesIO()
img.save(buf, format='PNG')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
t0 = time.time()
r = client.post('/api/crowd-estimate', files={
    'file': ('stand_crowd.png', buf.getvalue(), 'image/png'),
})
wall = time.time() - t0
print(f'HTTP {r.status_code} in {wall:.1f}s')
try:
    body = r.json()
except Exception:
    body = r.text
print(body)