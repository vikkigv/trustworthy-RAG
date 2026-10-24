from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-secret"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "trust_rag"
    postgres_password: str = "trust_rag_dev"
    postgres_db: str = "trust_rag"

    redis_host: str = "localhost"
    redis_port: int = 6379

    openai_api_key: str = ""
    generation_model: str = "gpt-4o-mini"
    verification_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # --- Documents / storage ---
    data_dir: str = "./data"  # local storage root; S3 backend swaps this out in prod
    max_upload_mb: int = 25
    allowed_mime_types: tuple[str, ...] = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/markdown",
        "text/plain",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
