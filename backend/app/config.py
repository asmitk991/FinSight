from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    app_name: str = "FinSight API"
    api_prefix: str = "/api"
    data_file: Path = DATA_DIR / "transactions.json"
    ingest_preview_file: Path = DATA_DIR / "previews.json"
    image_jobs_file: Path = DATA_DIR / "image_jobs.json"
    merchant_registry_file: Path = DATA_DIR / "merchant_registry.json"
    merchant_profiles_file: Path = DATA_DIR / "merchant_profiles.json"
    chroma_dir: Path = DATA_DIR / "chroma"
    chroma_collection: str = "finsight-transactions"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    google_gemini_model: str = "gemini-1.5-flash"
    layoutlm_model_name: str | None = None
    gemini_api_key: str | None = None
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    hf_api_token: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    use_celery_for_images: bool = False
    usd_to_inr: float = 92.37
    aed_to_inr: float = 25.10
    eur_to_inr: float = 106.53
    gbp_to_inr: float = 123.48
    skip_heavy_models: bool = False
    cors_origins: str | list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("cors_origins", mode="before")
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
