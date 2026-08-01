import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GAME_ENGINE = ROOT / "services" / "game_engine"
BOT_GATEWAY = ROOT / "services" / "bot_gateway"
DISCORD_GATEWAY = ROOT / "services" / "discord_gateway"
sys.path.insert(0, str(GAME_ENGINE))
sys.path.insert(1, str(BOT_GATEWAY))
sys.path.insert(2, str(DISCORD_GATEWAY))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough")
os.environ.setdefault("BOT_API_KEY", "test-bot-api-key")
os.environ.setdefault("DISCORD_BOT_API_KEY", "test-discord-api-key")
os.environ.setdefault("TWITCH_CLIENT_ID", "test-client-id")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
