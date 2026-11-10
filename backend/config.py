import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    provider: str = "fake"
    model: str = ""
    api_key: str = ""
    timeout: float = 12
    max_retries: int = 1
    state_db_path: str = ""

    def __post_init__(self):
        if self.provider not in {"fake", "gemini"}:
            raise ValueError("LLM_PROVIDER must be fake or gemini")
        if self.provider == "gemini" and (not self.api_key or not re.fullmatch(r"[A-Za-z0-9._-]+", self.model)):
            raise ValueError("Gemini requires GEMINI_API_KEY and a valid GEMINI_MODEL")
        if not 1 <= self.timeout <= 120 or not 0 <= self.max_retries <= 2:
            raise ValueError("Timeout must be 1-120 seconds and retries 0-2")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        return cls(provider=os.getenv("LLM_PROVIDER", "fake"), model=os.getenv("GEMINI_MODEL", ""),
                   api_key=os.getenv("GEMINI_API_KEY", ""), timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "12")),
                   max_retries=int(os.getenv("LLM_MAX_RETRIES", "1")),
                   state_db_path=os.getenv("AGENT_STATE_DB", str(ROOT / "data" / "processed" / "agent_state.sqlite")))
