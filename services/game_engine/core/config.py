import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str = "postgres" 
    DB_PORT: str = "5432"
    REDIS_URL: str = "redis://redis:6379/0"

    SECRET_KEY: str # (openssl rand -hex 32)
    ENCRYPTION_KEY: str | None = None
    BOT_API_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # from dev.twitch.tv
    TWITCH_CLIENT_ID: str
    TWITCH_CLIENT_SECRET: str    

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    class Config:
        env_file = ".env" 

settings = Settings()
