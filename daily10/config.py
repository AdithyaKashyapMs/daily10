"""Settings from environment variables (and a .env file in the repo root)."""

import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_FALLBACK_API_KEY = os.getenv("GROQ_FALLBACK_API_KEY")
# Main model for generating lessons and questions, then fallbacks tried in order when it
# fails (e.g. its free-tier daily token limit is used up). Each model has its own limits.
MODEL = os.getenv("DAILY10_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODELS = [m.strip() for m in os.getenv("DAILY10_FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
# A different model family judges question quality, so it isn't grading its own work.
JUDGE_MODEL = os.getenv("DAILY10_JUDGE_MODEL", "qwen/qwen3.8-27b")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
