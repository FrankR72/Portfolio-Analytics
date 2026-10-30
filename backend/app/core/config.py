from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict, BaseSettings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8"
    )
    
    database_url: str #postgresql
    
    # Optional: with no REDIS_URL the price cache is off and every lookup
    # goes to yfinance, as before (CI and the tests run this way).
    redis_url: str | None = None
    ttl_price_cache_current_prices_seconds: int = 60 * 5 # 5 minutes
    ttl_price_cache_historical_prices_seconds: int = 60 * 60 # 1 hour
        
       
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
    # Reasoning models "think" before answering, and that thinking counts
    # against llm_max_tokens, so a summary can come back empty. A summary
    # doesn't need it. Sent as OpenRouter's `reasoning` option; set False
    # for a provider that rejects unknown options.
    llm_disable_reasoning: bool = True

    @property
    def llm_configured(self) -> bool:
        """True when a model and an endpoint are set (the key is optional)."""
        return bool(self.llm_base_url and self.llm_model)


settings = Settings()