import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    app_name: str = "Personal Finance & Budget Advisor Agent"
    database_url: Optional[str] = os.getenv("DATABASE_URL")
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    gemini_model_name: str = os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash-lite")
    gemini_base_url: str = os.getenv("GEMINI_BASE_URL", "")
    exchange_rate_api_key: Optional[str] = os.getenv("EXCHANGE_RATE_API_KEY")
    auth0_domain: str = os.getenv("AUTH0_DOMAIN", "")
    auth0_client_id: str = os.getenv("AUTH0_CLIENT_ID", "")
    auth0_client_secret: str = os.getenv("AUTH0_CLIENT_SECRET", "")
    auth0_audience: str = os.getenv("AUTH0_AUDIENCE", "")
    auth0_management_client_id: str = os.getenv("AUTH0_MANAGEMENT_CLIENT_ID", "")
    auth0_management_client_secret: str = os.getenv("AUTH0_MANAGEMENT_CLIENT_SECRET", "")
    langfuse_secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    @property
    def auth0_enabled(self) -> bool:
        return bool(self.auth0_domain and self.auth0_client_id and self.auth0_audience)

    @property
    def auth0_management_enabled(self) -> bool:
        return bool(
            self.auth0_domain
            and self.auth0_management_client_id
            and self.auth0_management_client_secret
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
