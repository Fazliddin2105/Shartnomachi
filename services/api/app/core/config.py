"""Application settings.

All configuration is read from environment variables (or `.env`), validated
once at startup and exposed through the cached `get_settings()` accessor.
"""

from __future__ import annotations

import base64
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class StorageBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class SmsBackend(StrEnum):
    CONSOLE = "console"
    ESKIZ = "eskiz"


class AnchorBackend(StrEnum):
    DISABLED = "disabled"
    EVM = "evm"  # Polygon (Amoy testnet / mainnet) or any EVM chain


class LLMProvider(StrEnum):
    NONE = "none"
    OPENAI_COMPATIBLE = "openai_compatible"  # Ollama (Qwen), vLLM, LM Studio, DeepSeek


class SchedulerMode(StrEnum):
    """Where the reminder dispatcher runs.

    * `inprocess` - an asyncio loop inside the API process (dev / single node).
    * `worker`    - a dedicated ARQ worker (`python -m app.workers.main`).
    * `off`       - disabled (tests).
    """

    INPROCESS = "inprocess"
    WORKER = "worker"
    OFF = "off"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # --- general -----------------------------------------------------------
    app_name: str = "LexLab API"
    environment: Environment = Environment.DEV
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    timezone: str = "Asia/Tashkent"
    log_level: str = "INFO"
    log_json: bool = False

    # --- database ----------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/lexlab.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    redis_url: str | None = None

    # --- security ----------------------------------------------------------
    jwt_secret: str = "change-me-in-production-please-32b+"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "lexlab"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # 32-byte master key (base64). Used as KEK for envelope encryption.
    master_encryption_key: str = Field(
        default="ZGV2LW9ubHktbWFzdGVyLWtleS0zMi1ieXRlcyEhISE=",
        description="base64-encoded 32 byte key",
    )
    otp_ttl_seconds: int = 120
    otp_length: int = 6
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_hourly_limit: int = 5
    otp_ip_hourly_limit: int = 20
    otp_dev_fixed_code: str | None = Field(default=None, description="Dev/test only: fixed OTP code instead of random")
    totp_issuer: str = "LexLab"

    # --- storage -----------------------------------------------------------
    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_local_root: str = "./data/storage"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "lexlab"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    max_upload_mb: int = 25

    # --- integrations ------------------------------------------------------
    sms_backend: SmsBackend = SmsBackend.CONSOLE
    eskiz_email: str | None = None
    eskiz_password: str | None = None
    eskiz_from: str = "4546"
    eskiz_base_url: str = "https://notify.eskiz.uz/api"

    oneid_client_id: str | None = None
    oneid_client_secret: str | None = None
    oneid_redirect_uri: str | None = None
    oneid_base_url: str = "https://sso.egov.uz/sso/oauth/Authorization.do"

    # E-IMZO-SERVER (official component, deployed in our private network; /backend/* must not be public)
    eimzo_server_url: str | None = Field(default=None, description="e.g. http://127.0.0.1:8080")
    eimzo_site_host: str | None = Field(default=None, description="Our public domain, sent as Host header")
    eimzo_timeout_seconds: float = 20.0
    eimzo_require_timestamp: bool = True

    # --- blockchain anchoring (only Merkle roots go on-chain; data stays in UZ) ---
    anchor_backend: AnchorBackend = AnchorBackend.DISABLED
    anchor_network: str = "polygon-amoy"
    evm_rpc_url: str | None = Field(default=None, description="e.g. https://rpc-amoy.polygon.technology")
    evm_chain_id: int = 80002  # Polygon Amoy testnet
    anchor_contract_address: str | None = None
    relayer_private_key: str | None = Field(default=None, description="Gas-paying backend wallet (secret!)")
    anchor_confirmations: int = 3
    anchor_batch_max_leaves: int = 500
    anchor_explorer_tx_url: str = "https://amoy.polygonscan.com/tx/{tx}"

    telegram_bot_token: str | None = None

    soffice_path: str | None = Field(default=None, description="LibreOffice binary for DOCX->PDF (headless)")
    tesseract_cmd: str | None = None
    tesseract_langs: str = "uzb+uzb_cyrl+rus"

    # --- workers / reminders ----------------------------------------------
    scheduler_mode: SchedulerMode = SchedulerMode.INPROCESS
    scheduler_interval_seconds: int = 60
    reminder_offsets_days: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [6, 3, 2, 1, 0])
    reminder_send_hour: int = 9
    reminder_max_attempts: int = 3
    work_week_days: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4], description="Mon=0 ... Sun=6"
    )

    # --- AI (LLM) — OpenAI-compatible API: local Qwen via Ollama/vLLM, or DeepSeek for dev ---
    llm_provider: LLMProvider = LLMProvider.NONE
    llm_base_url: str = "http://127.0.0.1:11434/v1"  # Ollama; DeepSeek: https://api.deepseek.com
    llm_api_key: str | None = Field(default=None, description="Secret; not needed for local Ollama")
    llm_model: str = "qwen2.5:7b-instruct"  # DeepSeek: deepseek-chat
    llm_is_local: bool = Field(
        default=True, description="False => data leaves the server: PII is masked, prod is blocked"
    )
    llm_timeout_seconds: float = 90.0
    llm_max_tokens: int = 4000
    llm_temperature: float = 0.1
    llm_min_confidence: float = 0.6  # below => "yurist bilan maslahatlashing"

    # --- lex.uz (official legislation database: template import + change monitoring) ---
    lexuz_base_url: str = "https://lex.uz"

    # --- web frontend (served by the API in dev / single-node deployments) ---
    frontend_dir: str | None = Field(default=None, description="Folder with index.html to serve at /")

    # --- rules -------------------------------------------------------------
    legal_content_dir: str = "../../packages/legal-content"

    @field_validator("cors_origins", "reminder_offsets_days", "work_week_days", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            items = [x.strip() for x in v.split(",") if x.strip()]
            return items
        return v

    @model_validator(mode="after")
    def _validate_prod(self) -> Settings:
        key = self.master_key_bytes
        if len(key) != 32:
            raise ValueError("MASTER_ENCRYPTION_KEY must decode to exactly 32 bytes")
        if self.environment in (Environment.PROD, Environment.STAGING):
            if self.jwt_secret.startswith("change-me") or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a strong value outside dev")
            if self.master_encryption_key == Settings.model_fields["master_encryption_key"].default:
                raise ValueError("MASTER_ENCRYPTION_KEY must be overridden outside dev")
            if self.llm_provider != LLMProvider.NONE and not self.llm_is_local:
                # Personal-data localisation law: contract texts must not leave Uzbekistan in production.
                raise ValueError("External LLM (llm_is_local=false) is forbidden outside dev; use a local Qwen")
            if self.otp_dev_fixed_code:
                raise ValueError("OTP_DEV_FIXED_CODE is forbidden outside dev/test")
        self.reminder_offsets_days = sorted(set(self.reminder_offsets_days), reverse=True)
        return self

    @property
    def master_key_bytes(self) -> bytes:
        return base64.b64decode(self.master_encryption_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_dev(self) -> bool:
        return self.environment in (Environment.DEV, Environment.TEST)


@lru_cache
def get_settings() -> Settings:
    return Settings()
