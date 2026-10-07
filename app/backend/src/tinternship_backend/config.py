"""Application settings, loaded from the repo-root .env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/tinternship_backend/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Everything the app needs to boot. Only `google_api_key` is truly required."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Gemini -----------------------------------------------------------
    google_api_key: str = ""
    google_genai_use_vertexai: str = "FALSE"

    # --- Models -----------------------------------------------------------
    # Either a Gemini model id, or `ollama/<name>` for a model served by a local
    # Ollama. See agents/models.py for how one becomes a runnable agent.
    model_primary: str = "gemini-3.6-flash"
    model_fast: str = "gemini-3.5-flash-lite"

    # The Scout and the HR researcher carry Google Search, which is a Gemini
    # server-side tool: ADK refuses outright to attach it to anything else. They
    # run on this model whatever the two above are set to, so choosing a local
    # model for the writing does not cost you job discovery.
    model_grounded: str = "gemini-3.6-flash"

    # --- Ollama (optional) ------------------------------------------------
    # From a container this has to be host.docker.internal, not 127.0.0.1 —
    # localhost inside the container is the container.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: float = 600.0

    # --- Quality gate -----------------------------------------------------
    audit_pass_threshold: float = 7.5
    audit_max_revisions: int = 2

    # --- Follow-ups -------------------------------------------------------
    # Days of silence on an application that is waiting on the employer before
    # the Tracker raises it and the chase email is drafted. Two weeks is the
    # convention recruiters themselves quote; it is a runtime knob because the
    # right number depends on the sector — see services/runtime_config.py.
    follow_up_after_days: int = 14
    # How often the background sweep looks for applications that have newly
    # gone quiet. It only spends a model call on one that has, so this is a
    # latency setting rather than a cost one: at 6 hours a follow-up is drafted
    # within a quarter of a day of coming due.
    follow_up_sweep_hours: float = 6.0

    # --- Job discovery ----------------------------------------------------
    # Boards the Scout searches before anything general, in this order. Keys
    # come from tools/job_sources/platforms.py; reorder or trim for a search
    # outside France. Empty disables the priority pass entirely.
    priority_job_platforms: str = "welcome_to_the_jungle,linkedin,station_f"

    # Where the Jobs page slider starts. Each run can override it; this is only
    # the default. Clamped to MIN_RESULTS…MAX_RESULTS in agents/investigator.py.
    results_per_run: int = 15

    # --- Recency ----------------------------------------------------------
    # How fast a posting's age discounts its match. A posting is worth half as
    # much as an identical one published today after this many days, a quarter
    # after twice as many, and so on down to a floor — see services/recency.py.
    # Lower means a more aggressive bias toward what was published this week.
    posting_half_life_days: float = 21.0
    # The window a structured job board is asked for at all. Grounded search has
    # no equivalent knob, so this only bounds Adzuna; the ranking above is what
    # prioritises recency everywhere else.
    posting_max_age_days: int = 45

    # --- Link verification ------------------------------------------------
    # Boards behind bot protection (Welcome to the Jungle among them) answer an
    # HTTP client with a challenge page, not the posting, so a status code
    # cannot tell a live job from a 404. Chromium runs the challenge and reads
    # the rendered title, which can. It runs only on the links the HTTP check
    # could not settle, and needs `playwright install chromium`; without that
    # the app degrades to reporting those links as unchecked.
    browser_verify: bool = True
    browser_verify_max: int = 25
    browser_verify_timeout_seconds: float = 30.0
    # How long to let a challenge swap itself out, or a single-page app paint
    # its 404, after the DOM is ready.
    browser_verify_settle_seconds: float = 2.5

    # --- Adzuna (optional) ------------------------------------------------
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "fr"


    # --- Server -----------------------------------------------------------
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    data_dir: str = "./data"
    log_level: str = "INFO"

    # --- Derived ----------------------------------------------------------
    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        return self.data_path / "tinternship.db"

    @property
    def trace_db_path(self) -> Path:
        """OpenTelemetry spans live in their own file so they can be wiped freely."""
        return self.data_path / "traces.db"

    @property
    def sessions_db_path(self) -> Path:
        """ADK owns this file's schema; keep it away from our SQLModel tables."""
        return self.data_path / "sessions.db"

    @property
    def uploads_path(self) -> Path:
        path = self.data_path / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def artifacts_path(self) -> Path:
        path = self.data_path / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def adzuna_enabled(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)

    @property
    def allowed_origins(self) -> list[str]:
        origins = {self.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"}
        return sorted(o for o in origins if o)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # google-genai reads these from the process environment, not from us.
    if settings.google_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", settings.google_genai_use_vertexai)
    return settings
