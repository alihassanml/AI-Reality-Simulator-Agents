"""Runtime configuration, loaded from .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# Pydantic AI takes a "provider:model" string, which is the format already in .env.
MODEL_NAME = os.getenv("MODEL_NAME", "openai:gpt-4.1-mini").strip('"').strip("'")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "simulator.db")

# Minimum wall-clock seconds a workflow step is held on screen. LLM latency alone
# is uneven -- a cached fast step would otherwise flash past before it can be read.
MIN_STEP_SECONDS = float(os.getenv("MIN_STEP_SECONDS", "1.6"))

# Guard against a runaway agent loop burning tokens.
MAX_TOOL_CALLS_PER_STEP = int(os.getenv("MAX_TOOL_CALLS_PER_STEP", "6"))

HAS_API_KEY = bool(os.getenv("OPENAI_API_KEY"))
