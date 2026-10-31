"""Application configuration — the single source of settings (pydantic-settings).

Security settings are **validated** here, not merely declared. Pydantic without a validator
is just a type annotation; a value like `CORS_ORIGINS=*` used to pass and turned the API into
an open endpoint for any origin.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.domain.environments import AppEnv

# Local environments: no TLS and no separate deployment step.
_LOCAL_ENVS: frozenset[str] = frozenset({"dev", "test"})

# The `__Host-` prefix forces the browser to require Secure + Path=/ + NO Domain attribute.
# That closes cookie tossing from a subdomain: a hijacked `blog.example.com` cannot overwrite
# a cookie with this name. It requires HTTPS, so locally (http) we use the bare name.
_HOST_COOKIE_PREFIX = "__Host-"

_MIN_AUTH_SECRET_LENGTH = 32

type ResearcherKind = Literal["catalog", "claude-cli"]
type PaymentsKind = Literal["fake", "wallet"]
type PkpTransportKind = Literal["browser", "http"]
type HoldsMode = Literal["off", "on"]


class Settings(BaseSettings):
    # Order matters: a later file overrides an earlier one.
    # `../.env` = shared file at the repo root, `.env` = backend-local overrides.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: AppEnv = "dev"

    # `directConnection=true`: the database is a single-node replica set (required for
    # transactions) but advertises itself by container name — without this flag a client on
    # the host cannot resolve the address.
    # Port 27018, because 27017 is often taken by a locally installed mongod.
    mongodb_url: str = "mongodb://app:app@localhost:27018/?directConnection=true"
    mongodb_database: str = "app"
    # Short and explicit: PyMongo's default 30 s piles up requests when the database is down.
    mongodb_server_selection_timeout_ms: int = 5_000
    # Budget for the whole operation (CSOT). Registration runs a transaction over four
    # documents, so we do not go below a few seconds.
    mongodb_operation_timeout_ms: int = 10_000
    # Connections per process. PyMongo defaults to 100, which is invisible until it is not:
    # with `--workers 4` that is 400 connections from one instance, and Atlas counts them per
    # project (an M10 allows 1500). The arithmetic that matters is `workers * replicas * pool`.
    mongodb_max_pool_size: int = 50

    # Key signing CSRF tokens. Length-validated on staging/prod — see
    # `_reject_weak_secret_outside_local`.
    auth_secret: str = "change-me"
    cors_origins: str = "http://localhost:3000"

    session_cookie_name: str = "session"
    csrf_cookie_name: str = "csrf_token"
    session_ttl_hours: int = 24 * 14
    # Idle timeout (ASVS V7): a session untouched for this long stops working even if the
    # absolute TTL has not elapsed. A cookie from an abandoned laptop dies after a day rather
    # than after two weeks.
    session_idle_timeout_hours: int = 24
    # Ceiling on active sessions per user. Without it a script staying inside the rate limit
    # mints hundreds of thousands of valid credentials nobody sees and nobody can revoke.
    max_sessions_per_user: int = 10

    # Maximum request body size. FastAPI reads the stream into memory BEFORE validation, so
    # `max_length` on a field protects nothing.
    max_request_body_bytes: int = 1 * 1024 * 1024

    # Ceiling for all routes except the explicitly exempt ones (see app.core.rate_limit).
    global_rate_limit: str = "300/minute"
    # A stricter limit for login and registration.
    login_rate_limit: str = "10/minute"
    # How many of OUR OWN proxies sit in front of the application (nginx, ALB, ingress).
    # 0 = the application is exposed directly and `X-Forwarded-For` is ignored. See
    # `app.core.rate_limit.client_key` — a wrong value either lumps everyone into one bucket
    # or lets the bucket be bypassed.
    trusted_proxy_hops: int = 0
    # Where to keep the counters. Empty = process memory (per-instance limit — fine for tests
    # and single-node). `redis://…` = one shared counter for every replica.
    rate_limit_storage_url: str = ""

    # Who researches trip packages: `catalog` = packages composed deterministically from the
    # enabled suppliers' offers (see `suppliers`); `claude-cli` = the same packages, described
    # by Claude Code in `-p` mode (falls back to the catalogue wording on any failure).
    researcher: ResearcherKind = "catalog"
    research_timeout_s: int = 300
    # Supplier searches of one research run concurrently; one slower than this contributes no
    # offers (it keeps running and fills the cache). Results are cached in-process for
    # `search_cache_ttl_s` (0 = off) so a re-generate on the same route is instant.
    search_supplier_timeout_s: float = Field(default=15.0, gt=0.0)
    search_cache_ttl_s: float = Field(default=300.0, ge=0.0)
    # A feed message per finished supplier search ("PKP Intercity ✓ 2 offers · 2.9 s").
    search_progress_events: bool = True
    # One GET per supplier link at research time (at most ~1.5 s): 404/410 links are dropped
    # and items without photos get the page's og:image.
    link_check: bool = True
    # Who takes the money. `wallet` pays shares from the member's platform wallet (dummy BLIK /
    # card top-ups); `fake` always succeeds without any balance. Stripe plugs in later.
    payments: PaymentsKind = "wallet"
    # How long the dummy bank takes to confirm a wallet top-up.
    wallet_confirm_delay_s: float = Field(default=1.5, ge=0, le=30)
    # The booking agent (see app.agent). Relative paths resolve against `backend/` — the
    # directory the agent subprocess runs in.
    agent_var_dir: str = "var/agent"
    # Optional flat JSON merged into every run's vault (e.g. real passenger names for a demo).
    agent_vault_file: str = ""
    # Show the agent's browser window (local debugging only).
    agent_headful: bool = False
    agent_max_steps: int = 40
    # Demo only: the base URL of THIS backend (e.g. http://localhost:8000). On dev/test it
    # enables the `demo_rail` supplier — our fake rail site under it — so a live demo never
    # drives the agent at a real carrier. Empty = off.
    demo_supplier_url: str = ""
    # The supplier plugins, comma-separated ids (see app.suppliers.providers): the simulators
    # `sim_rail`, `sim_flight`, `sim_bus`, `sim_stay`, `sim_stay_site`, `sim_activity`; the
    # real `pkp_intercity` (search + re-quote against PKP's gateway); `demo_rail`; `liteapi`
    # (real hotels through LiteAPI — needs `liteapi_key`); `duffel` (real flights through the
    # Duffel API — needs `duffel_api_key`).
    suppliers: str = "sim_rail,sim_flight,sim_bus,sim_stay,sim_activity"
    # How `pkp_intercity` reaches PKP's gateway: `browser` = one shared headless Camoufox
    # for the process (PKP sits behind Akamai, which resets plain HTTP); `http` = httpx.
    pkp_transport: PkpTransportKind = "browser"
    # Supplier holds at voting close. `off` (default): nothing is held, every purchase
    # re-quotes right before it starts (a moved price takes the PRICE_CHANGED path) and an
    # API supplier books at the approval. `on`: suppliers that support holds lock the price
    # while the group pays.
    holds: HoldsMode = "off"
    # How far (in percent of the stored amount) a re-quote may move before the group's shares
    # are re-split. 0 = any change re-splits.
    price_tolerance_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    # The `liteapi` stays supplier (app.suppliers.liteapi). A SANDBOX key (`sand_...`) is
    # required; any other key is refused unless `liteapi_allow_live` — real rooms, real money.
    liteapi_key: SecretStr | None = None
    liteapi_allow_live: bool = False
    # The `duffel` flights supplier (app.suppliers.duffel). A TEST key (`duffel_test_...`) is
    # required; a live key is refused unless `duffel_allow_live` — real tickets, real money.
    duffel_api_key: SecretStr | None = None
    duffel_allow_live: bool = False
    # PLN per EUR: Duffel prices in the account's currency, trips are in PLN.
    duffel_fx_eur_pln: float = Field(default=4.30, gt=0.0)
    # Sent as every passenger's contact (TripSplit keeps no per-passenger e-mail or phone).
    duffel_contact_email: str = "trips@tripsplit.example"
    duffel_contact_phone: str = "+48500100200"

    @field_validator("researcher", mode="before")
    @classmethod
    def _read_legacy_researcher(cls, value: object) -> object:
        """`fixture` was the deterministic researcher before suppliers became plugins; an
        existing `.env` keeps working with its successor."""
        return "catalog" if value == "fixture" else value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: str) -> str:
        """`*` with `allow_credentials=True` makes Starlette **reflect** any Origin.

        Effect: a foreign site does `fetch(..., {credentials:'include'})` and reads the signed-in
        user's email and organization list. We reject it outright, because it is the reflex fix
        when "CORS does not work" on a preview environment.
        """
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if any(origin == "*" for origin in origins):
            raise ValueError(
                "CORS_ORIGINS=* is forbidden: with session cookies it means opening the API to "
                "any origin. List the origin(s) explicitly."
            )
        return value

    @model_validator(mode="after")
    def _reject_weak_secret_outside_local(self) -> "Settings":
        """The default secret must not leave dev/test — CSRF signatures stand on it."""
        if self.app_env in _LOCAL_ENVS:
            return self
        if self.auth_secret == "change-me" or len(self.auth_secret) < _MIN_AUTH_SECRET_LENGTH:
            raise ValueError(
                f"AUTH_SECRET must be at least {_MIN_AUTH_SECRET_LENGTH} characters outside "
                "dev/test. Generate one with: openssl rand -hex 32"
            )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cookie_secure(self) -> bool:
        """`Secure` is disabled only on dev/test, where there is no TLS."""
        return self.app_env not in _LOCAL_ENVS

    @property
    def effective_csrf_cookie_name(self) -> str:
        """Over HTTPS we add the `__Host-` prefix; locally over http the browser would reject
        such a cookie."""
        if self.cookie_secure:
            return f"{_HOST_COOKIE_PREFIX}{self.csrf_cookie_name}"
        return self.csrf_cookie_name

    @property
    def create_indexes_on_startup(self) -> bool:
        """Outside dev/test, indexes are created by a deployment step
        (`uv run ensure-indexes`) rather than by application startup — building an index on a
        large collection eats I/O."""
        return self.app_env in _LOCAL_ENVS

    @property
    def expose_api_docs(self) -> bool:
        """Swagger and `/openapi.json` locally only.

        In production they are a ready-made manual: the full HTTP surface, validation limits
        and the error-code catalogue, plus the ability to send POSTs straight from a browser.
        """
        return self.app_env in _LOCAL_ENVS

    @property
    def demo_routes_enabled(self) -> bool:
        """The fake supplier and the disruption trigger exist on dev/test only."""
        return self.app_env in _LOCAL_ENVS

    @property
    def demo_rail_url(self) -> str | None:
        """The base URL the `demo_rail` supplier lives under, or None outside a demo."""
        if not self.demo_supplier_url or not self.demo_routes_enabled:
            return None
        return self.demo_supplier_url.rstrip("/")

    @property
    def holds_enabled(self) -> bool:
        return self.holds == "on"

    @property
    def supplier_ids(self) -> list[str]:
        return [part.strip() for part in self.suppliers.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
