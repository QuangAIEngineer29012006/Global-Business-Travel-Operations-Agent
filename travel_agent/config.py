import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    workspace: Path = ROOT / "workspace"
    provider: str = "fake"
    model: str = ""
    api_key: str = ""
    timeout: float = 12
    transport_retries: int = 1
    daily_limit: int = 100
    max_steps: int = 24
    max_model_calls: int = 16
    max_retrieval_calls: int = 6
    tool_retries: int = 1

    def __post_init__(self):
        if self.provider not in {"fake", "gemini"}:
            raise ValueError("LLM_PROVIDER must be fake or gemini")
        if self.provider == "gemini" and (not self.model or not self.api_key):
            raise ValueError("Gemini requires GEMINI_MODEL and GEMINI_API_KEY")
        if not 1 <= self.timeout <= 120 or not 0 <= self.transport_retries <= 2:
            raise ValueError("Invalid timeout/retry limit")
        if not 0 <= self.tool_retries <= 2 or not 0 <= self.daily_limit <= 10000:
            raise ValueError("Invalid tool retry/daily limit")
        if not (1 <= self.max_steps <= 50 and 1 <= self.max_model_calls <= 50
                and 1 <= self.max_retrieval_calls <= 10):
            raise ValueError("Invalid run budget")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        return cls(workspace=Path(os.getenv("TRAVEL_WORKSPACE", str(ROOT / "workspace"))),
                   provider=os.getenv("LLM_PROVIDER", "fake"), model=os.getenv("GEMINI_MODEL", ""),
                   api_key=os.getenv("GEMINI_API_KEY", ""),
                   timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "12")),
                   transport_retries=int(os.getenv("LLM_MAX_RETRIES", "1")),
                   daily_limit=int(os.getenv("LLM_DAILY_REQUEST_LIMIT", "100")))
