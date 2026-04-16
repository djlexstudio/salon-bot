import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_CHAT_ID: int
    DOMAIN: str
    WEBHOOK_PATH: str
    WEBAPP_URL: str
    DB_PATH: str
    
    class Config:
        env_file = ".env"

settings = Settings()