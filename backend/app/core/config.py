from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict, BaseSettings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8"
    )
    
    database_url: str
        
    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


    llm_base_url: str | None = None
    llm_model: str | None = None
    # Ollama needs no key; Hugging Face needs an access token.
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 500
    llm_temperature: float = 0.2

    @property
    def llm_configured(self) -> bool:
        """True when a model and an endpoint are set (the key is optional)."""
        return bool(self.llm_base_url and self.llm_model)


settings = Settings()