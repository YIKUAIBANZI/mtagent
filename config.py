"""Centralized environment loading. Import once at startup."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Dianping
DIANPING_BASE_URL = os.environ.get("MTAGENT_DIANPING_BASE_URL", "http://localhost:9192")
DIANPING_APPKEY = os.environ.get("DIANPING_APPKEY", "demo-appkey")
DIANPING_SECRET = os.environ.get("DIANPING_SECRET", "demo-secret")
DIANPING_SESSION = os.environ.get("DIANPING_SESSION", "demo-session")

# Mock data
MOCK_DATA_DIR = Path(os.environ.get("MTAGENT_MOCK_DATA_DIR", "data/mock_dianping"))

# LLM
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
QWEN_BASE_URL = os.environ.get(
    "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")

# Trip context
TRIPS_DIR = Path(os.environ.get("MTAGENT_TRIPS_DIR", "data/trips"))
TRIPS_DIR.mkdir(parents=True, exist_ok=True)
