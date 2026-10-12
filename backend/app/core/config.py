"""Application settings, loaded from environment variables (and `.env` files)."""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEV_APP_SECRET = "dev-insecure-app-secret-do-not-use-in-production"
_DEV_JWT_SECRET = "dev-insecure-jwt-secret-do-not-use-in-production"
_MIN_SECRET_LENGTH = 32
# Passwords that ship in .env.example / docs / defaults: never acceptable outside development.
_KNOWN_DB_PASSWORDS = {"", "leadfinder", "postgres", "password", "change-me", "change-me-local-dev-password"}
_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env when run from backend/, or a local .env
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"

    database_url: str = "postgresql+psycopg://leadfinder:leadfinder@localhost:5432/leadfinder"

    # APP_SECRET is reserved for application-level signing/encryption
    # (e.g. encrypting integration credentials once Settings manages them).
    app_secret: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    session_expire_minutes: int = 480

    frontend_url: str = "http://localhost:3000"
    cors_extra_origins: str = ""

    cookie_name: str = "lf_session"
    cookie_secure: bool | None = None

    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 300

    # Company discovery (Step 3). Source extracts (Overture, OpenStreetMap, Wikidata) are cached here.
    discovery_cache_dir: str = "storage/discovery"
    # Which sources run, in which order, with which quality weight (see services/discovery/config.py).
    discovery_connectors_file: str = "app/services/discovery/connectors.json"
    # Run the job worker inside the API process. Development runs it as its own process instead
    # (docker compose service `worker`: python -m app.services.jobs) so discovery never slows the API.
    discovery_worker_enabled: bool = True
    discovery_worker_threads: int = 2  # discovery jobs running at once per worker process
    # A source that has not answered within this many seconds is reported as timed out; the search goes on.
    discovery_connector_timeout_seconds: float = 20
    # Company websites (services/enrichment): every request goes through the SSRF-safe, robots-aware fetcher.
    website_timeout_seconds: float = 8  # per request (connect / each read); a whole response gets twice that
    website_max_bytes: int = 2_000_000  # research reads the first 2 MB of a larger page (head, navigation first)
    website_min_interval_seconds: float = 1.0  # per website host (a longer robots.txt Crawl-delay wins)
    # Company research (Step 4): queued for new search results with a website, opened companies, refreshes.
    enrichment_enabled: bool = True
    enrichment_worker_threads: int = 4  # companies researched at once per worker process (different hosts)
    enrichment_page_budget: int = 12  # pages fetched per company, homepage included
    enrichment_job_seconds: float = 60  # a company's research stops (partial) after this long
    enrichment_fresh_days: int = 14  # a company researched more recently is not researched again on open
    # Agents (services/agents), run by the worker. Profiler: brief + description from the cached website pages,
    # written by a local model (Ollama; nothing leaves the machine). Scout: learns from sales statuses which
    # companies become leads, scores all companies and starts lookalike searches.
    agents_enabled: bool = True
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 180
    profiler_enrich_per_hour: int = 30  # companies with a website but no cached pages: research queued per hour
    scout_min_labels: int = 5  # leads (and non-leads) needed before the Scout scores anything
    scout_daily_searches: int = 1  # lookalike searches the Scout may start per day (0 = never)
    scout_search_size: int = 25
    # External people discovery (Step 5.1): free public sources beyond the company's own website (Lebanon source
    # pack, Common Crawl, Wikidata, documents the company links to). No paid API is needed.
    external_people_enabled: bool = True
    # Optional and OFF: a public web search API (never a search engine's result pages). "brave" is paid and also
    # needs BRAVE_SEARCH_API_KEY; anything else = no search.
    people_search_provider: str = "none"
    brave_search_api_key: SecretStr | None = None  # BRAVE_SEARCH_API_KEY; never logged
    search_min_interval_seconds: float = 1.1  # the provider's rate limit (Brave free tier: 1 query / second)
    search_timeout_seconds: float = 10
    search_cache_days: int = 14
    external_people_worker_threads: int = 2  # companies researched externally at once (separate lanes)
    external_max_queries: int = 8  # per company
    external_results_per_query: int = 5
    external_max_fetches: int = 25  # external pages + documents per company
    external_max_pdfs: int = 5
    external_job_seconds: float = 120  # deep people research stops (timed_out, results kept) after this long
    external_fresh_days: int = 30  # missing departments are researched externally again after this
    commoncrawl_crawls: int = 4  # index lookups per company (newest crawls first, then about a year back)
    commoncrawl_max_captures: int = 8  # archived pages read per company
    contact_job_seconds: float = 45  # one company's contact research stops (timed_out, results kept) after this
    # Mailbox check at the company's mail server (RCPT only, nothing sent). OFF by default: it talks to the
    # companies' mail servers from this host; DNS / MX checks always run.
    email_smtp_verification: bool = False
    email_smtp_timeout_seconds: float = 8
    email_smtp_helo: str = "localhost"
    # MAIL FROM of the check ("" = the null sender <>). Backscatter filters refuse <>: a real mailbox of TECOMSA's
    # domain (verify@...) gets an answer from them.
    email_smtp_mail_from: str = ""
    # Publicly researched people / contacts not seen again by any source for this long are deleted (daily, worker).
    # TECOMSA's own (Odoo, contributed) and colleague-confirmed data is kept. 0 = never.
    contact_retention_days: int = 730
    commoncrawl_budget_seconds: float = 45  # Common Crawl's share of one company's deep research
    commoncrawl_down_seconds: float = 600  # after the index failed: skipped for every company for this long
    commoncrawl_min_interval_seconds: float = 1.5  # Common Crawl's public index is shared: never hammered
    # Lusha (services/lusha.py): paid people search + per-person reveal, only on an explicit, confirmed click.
    lusha_api_key: SecretStr | None = None  # LUSHA_API_KEY; empty = feature off. Never logged or returned
    lusha_base_url: str = "https://api.lusha.com"
    lusha_monthly_credit_budget: int = 0  # hard cap on LeadFinder's Lusha credits per calendar month (0 = no cap)
    lusha_search_size: int = 25  # people per company search (Lusha bills search per result: api_search)
    lusha_search_cache_days: int = 30  # a company's Lusha people list is reused this long (no new paid search)
    lusha_timeout_seconds: float = 20
    # One Lusha seat for the whole team: numbers only (an email reveal is refused), at most this many paid reveals per
    # user per day (0 = no cap), never for a person LeadFinder already has a number for.
    lusha_phone_only: bool = True
    lusha_user_daily_reveals: int = 20

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "production")

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is None:
            return self.is_production
        return self.cookie_secure

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.frontend_url] + [o for o in self.cors_extra_origins.split(",")]
        return [o.strip().rstrip("/") for o in origins if o and o.strip()]

    def production_problems(self) -> list[str]:
        """Unsafe settings for staging/production. Startup refuses to run while any remain (fail closed)."""
        problems = []
        for name in ("app_secret", "jwt_secret"):
            value = getattr(self, name)
            if len(value) < _MIN_SECRET_LENGTH or value in (_DEV_APP_SECRET, _DEV_JWT_SECRET):
                problems.append(f"{name.upper()} must be a random value of at least {_MIN_SECRET_LENGTH} characters")
        if self.app_secret and self.app_secret == self.jwt_secret:
            problems.append("APP_SECRET and JWT_SECRET must be different values")
        if self.jwt_algorithm not in _JWT_ALGORITHMS:
            problems.append(f"JWT_ALGORITHM must be one of {sorted(_JWT_ALGORITHMS)}")
        from sqlalchemy.engine import make_url

        try:
            db_password = make_url(self.database_url).password or ""
        except Exception:  # noqa: BLE001 - reported below as unusable
            db_password = ""
        if db_password in _KNOWN_DB_PASSWORDS or len(db_password) < 16:
            problems.append("the database password (DATABASE_URL / POSTGRES_PASSWORD) is a default or shorter "
                            "than 16 characters")
        if self.cookie_secure is False:
            problems.append("COOKIE_SECURE=false: session cookies must only travel over HTTPS")
        for origin in self.cors_origins:
            if origin == "*" or not origin.startswith("https://") or "localhost" in origin or "127.0.0.1" in origin:
                problems.append(f"FRONTEND_URL / CORS_EXTRA_ORIGINS must be explicit https origins (got {origin!r})")
        return problems

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        if self.is_production:
            problems = self.production_problems()
            if problems:
                raise ValueError(f"Unsafe {self.environment} configuration: " + "; ".join(problems))
        else:
            if not self.app_secret:
                self.app_secret = _DEV_APP_SECRET
            if not self.jwt_secret:
                self.jwt_secret = _DEV_JWT_SECRET
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
