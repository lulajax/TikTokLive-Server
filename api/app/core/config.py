import json
import os
from typing import List

from dotenv import load_dotenv

if os.environ.get('ENV_PATH'):
    loaded = load_dotenv(os.environ['ENV_PATH'])
    print("Is ENV Loaded:", loaded)
else:
    print("No ENV_PATH specified")

PORT: int = int(os.environ.get('PORT', '3005'))
TEST_MODE: bool = os.environ.get('TEST_MODE', 'true').lower() == 'true'

CLEAN_UP_INTERVAL: int = int(os.environ.get('CLEAN_UP_INTERVAL', '60'))

_proxy_fp = os.environ.get('PROXY_FP')
PROXIES: List[str] = json.loads(open(_proxy_fp, "r").read()) if _proxy_fp else []
SESSION_ID: str | None = os.environ.get('TIKTOK_SESSION_ID', None)
