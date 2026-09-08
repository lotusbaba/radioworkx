import os
from pathlib import Path

DATA = Path(os.getenv("DATA_DIR", "data"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
THRESHOLD = int(os.getenv("REACTION_THRESHOLD", "20"))
MAX_TRACKS = 10_000  # Deliberately not configurable above the requested hard ceiling.
DEMO = os.getenv("DEMO_MODE", "0") == "1"
EMOJIS = ["❤️", "🔥", "🙌", "😍", "💃", "🤯"]
