import os, json
from pathlib import Path

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# 可选本地配置文件（不进 git）
CONFIG_PATH = Path.home() / ".config" / "cipher" / "telegram.json"
if not TOKEN and CONFIG_PATH.exists():
    data = json.loads(CONFIG_PATH.read_text())
    TOKEN = data.get("token", "")

# 白名单：None 表示允许所有人
ALLOWED_USER_IDS = None  # 或 [123456789]

# Cipher 管线路径
CIPHER_ENTRY = Path(__file__).resolve().parent.parent / "skills" / "routing" / "entry.py"
WORKDIR = Path(__file__).resolve().parent.parent
