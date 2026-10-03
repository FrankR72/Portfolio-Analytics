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
    

settings = Settings()
