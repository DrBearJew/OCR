from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dok OCR"
    environment: str = "dev"
    debug: bool = True

    database_url: str = "postgresql+psycopg://dokocr:dokocr@postgres:5432/dokocr"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_always_eager: bool = False
    celery_worker_prefetch_multiplier: int = 1
    ocr_worker_concurrency: int = 1
    ocr_task_soft_time_limit: int = 600
    ocr_task_time_limit: int = 660
    ocr_task_hard_time_limit_grace_seconds: int = 120
    ocr_task_lease_grace_seconds: int = 300
    # Portable CPU-only OCR timeout budgets. These are kill ceilings, not target
    # throughput numbers. The estimator scales long PaddleOCR-VL PDFs by 4-page
    # OCR chunks so normal invoices keep the existing 600s floor while books
    # receive enough runtime. Operators can raise these after benchmarking slower
    # CPUs or lower them after benchmarking faster hosts.
    ocr_task_base_overhead_seconds: int = 300
    ocr_task_paddle_vl_seconds_per_chunk: int = 180
    ocr_task_glm_seconds_per_page: int = 180
    ocr_task_ppocrv6_seconds_per_page: int = 30
    ocr_task_fake_seconds_per_page: int = 5
    ocr_max_retries: int = 2
    task_lease_seconds: int = 420

    storage_root: Path = Field(
        default=Path("/data/storage"),
        validation_alias=AliasChoices("storage_root", "STORAGE_ROOT", "STORAGE_PATH"),
    )
    max_upload_file_size_mb: int = Field(default=200, validation_alias=AliasChoices("max_upload_file_size_mb", "MAX_UPLOAD_FILE_SIZE_MB", "MAX_UPLOAD_MB"))
    max_upload_batch_size_mb: int = Field(default=500, validation_alias=AliasChoices("max_upload_batch_size_mb", "MAX_UPLOAD_BATCH_SIZE_MB"))
    max_upload_files_per_batch: int = Field(default=50, validation_alias=AliasChoices("max_upload_files_per_batch", "MAX_UPLOAD_FILES_PER_BATCH"))
    allowed_upload_extensions: str = Field(
        default="pdf,png,jpg,jpeg,webp,tif,tiff,txt,doc,docx,xls,xlsx,ppt,pptx,odt,ods,odp,rtf,eml,msg",
        validation_alias=AliasChoices("allowed_upload_extensions", "ALLOWED_EXTENSIONS", "ALLOWED_UPLOAD_EXTENSIONS"),
    )
    allowed_upload_mime_types: str = Field(
        default=(
        "application/pdf,image/png,image/jpeg,image/webp,image/tiff,text/plain,"
        "application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,"
        "application/vnd.oasis.opendocument.text,application/vnd.oasis.opendocument.spreadsheet,"
        "application/vnd.oasis.opendocument.presentation,application/rtf,message/rfc822,application/vnd.ms-outlook"
        ),
        validation_alias=AliasChoices("allowed_upload_mime_types", "ALLOWED_MIME_TYPES", "ALLOWED_UPLOAD_MIME_TYPES"),
    )
    max_pdf_pages: int = Field(default=100, validation_alias=AliasChoices("max_pdf_pages", "MAX_PDF_PAGES"))
    thumbnail_size: int = 420
    stuck_document_minutes: int = 30

    admin_username: str = "admin"
    admin_password: str = "admin"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60
    jwt_issuer: str = "dokocr"
    jwt_audience: str = "dokocr-admin"
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300

    ocr_provider: str = Field(default="fake", pattern="^(fake|glm|paddle_vl|ppocrv6)$")
    glm_llamacpp_base_url: str = "http://glm-llama:8080"
    glm_model_path: str = "/llm-models/glm.gguf"
    glm_mmproj_path: str = "/llm-models/glm-mmproj.gguf"

    paddle_vl_llamacpp_base_url: str = "http://smart-proxy:8081/v1"
    paddle_vl_model_path: str = "paddleocr-vl"
    paddle_vl_mmproj_path: str = "/llm-models/paddleocr-vl-mmproj.gguf"

    ppocrv6_tier: str = Field(default="medium", pattern="^(tiny|small|medium)$")
    ppocrv6_engine: str = "onnxruntime"
    ppocrv6_device: str = "cpu"

    qwen_llamacpp_base_url: str = "http://qwen-llama:8080"
    qwen_model_path: str = "/llm-models/qwen.gguf"

    llm_request_timeout_seconds: float = 120.0
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.0
    llm_metadata_refinement_enabled: bool = False

    ocr_max_pages_per_doc: int = 50
    ocr_image_dpi: int = 200
    ocr_concurrency: int = 1
    ocr_mode: str = "redo"
    ocr_language: str = "deu+eng"
    ocr_cleanup_mode: str = "none"
    ocr_deskew: bool = True
    ocr_rotate_pages: bool = True
    ocr_rotate_threshold: float = 12.0
    ocr_output_type: str = "pdfa"
    ocr_max_image_pixels: int = 40_000_000

    consume_path: Path = Path("/data/consume")
    ingestion_poll_interval_seconds: int = 300
    converters_enabled: bool = False
    tika_base_url: str = "http://tika:9998"
    gotenberg_base_url: str = "http://gotenberg:3000"

    prompt_dir: Path = Path(__file__).resolve().parents[1] / "prompts"
    rules_dir: Path = Path(__file__).resolve().parent

    frontend_origin: str = "http://localhost:3001"
    public_base_url: str = "http://localhost:3001"
    api_base_url: str = "/api"
    cookie_secure: bool = False
    trusted_proxy_headers: bool = True
    cors_origins: str = "http://localhost:3001,http://localhost:3000,http://localhost:5173"
    command_hooks_enabled: bool = False
    command_hooks_allowed_commands: str = "python,python3"
    hook_webhook_allowed_hosts: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    def _model_name_from_config(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return text
        if text.startswith("/") or text.lower().endswith(".gguf") or "\\" in text:
            return Path(text).name
        return text

    @property
    def glm_model_name(self) -> str:
        return self._model_name_from_config(self.glm_model_path)

    @property
    def qwen_model_name(self) -> str:
        return self._model_name_from_config(self.qwen_model_path)

    @property
    def paddle_vl_model_name(self) -> str:
        return self._model_name_from_config(self.paddle_vl_model_path)

    @property
    def allowed_extensions_set(self) -> set[str]:
        return {item.strip().lower().lstrip(".") for item in self.allowed_upload_extensions.split(",") if item.strip()}

    @property
    def allowed_mime_types_set(self) -> set[str]:
        return {item.strip().lower() for item in self.allowed_upload_mime_types.split(",") if item.strip()}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_file_size_mb * 1024 * 1024

    @property
    def max_upload_batch_bytes(self) -> int:
        return self.max_upload_batch_size_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        values = [self.frontend_origin]
        if not self.is_production:
            values.extend(["http://localhost:3000", "http://localhost:5173"])
        values.extend(item.strip() for item in self.cors_origins.split(",") if item.strip())
        return sorted(set(values))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def hook_webhook_allowed_hosts_set(self) -> set[str]:
        return {item.strip().lower() for item in self.hook_webhook_allowed_hosts.split(",") if item.strip()}

    @property
    def command_hooks_allowed_commands_set(self) -> set[str]:
        return {item.strip().lower() for item in self.command_hooks_allowed_commands.split(",") if item.strip()}


DEFAULT_SECRET_KEYS = {"change-me-in-production", "change-me-before-real-use"}


def validate_production_settings(settings: Settings) -> None:
    if not settings.is_production:
        return
    if settings.admin_password == "admin":
        raise RuntimeError("ADMIN_PASSWORD must be changed outside development")
    if settings.secret_key in DEFAULT_SECRET_KEYS:
        raise RuntimeError("SECRET_KEY must be changed outside development")
    if len(settings.secret_key) < 32 or len(set(settings.secret_key)) < 12:
        raise RuntimeError("SECRET_KEY must be at least 32 characters with reasonable entropy outside development")
    localhost_origins = [
        origin
        for origin in settings.cors_origins_list
        if "localhost" in origin or "127.0.0.1" in origin
    ]
    if localhost_origins:
        raise RuntimeError(f"Production CORS origins must not include localhost: {localhost_origins}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
