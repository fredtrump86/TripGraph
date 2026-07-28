from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LiveModeConfigurationError(RuntimeError):
    """实时模式缺少必要配置。"""


class Settings(BaseSettings):
    """应用配置；默认演示模式可零密钥启动。"""

    app_name: str = "TripGraph"
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False
    demo_mode: bool = True

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_timeout: float = Field(default=90, gt=0)

    amap_api_key: str = ""
    amap_mcp_url: str = "https://mcp.amap.com/mcp"
    amap_js_key: str = ""
    amap_js_security_code: str = ""
    unsplash_access_key: str = ""
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_deepseek(self) -> bool:
        return (urlsplit(self.llm_base_url).hostname or "").lower() == "api.deepseek.com"

    @property
    def llm_extra_body(self) -> dict[str, object] | None:
        if self.is_deepseek:
            return {"thinking": {"type": "disabled"}}
        return None

    @property
    def llm_structured_method(self) -> Literal["function_calling", "json_mode"]:
        return "json_mode" if self.is_deepseek else "function_calling"

    def validate_live_mode(self) -> None:
        missing: list[str] = []
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.amap_api_key:
            missing.append("AMAP_API_KEY")
        if missing:
            joined = "、".join(missing)
            raise LiveModeConfigurationError(f"实时模式缺少配置：{joined}。请配置 .env 或启用 DEMO_MODE=true。")


@lru_cache
def get_settings() -> Settings:
    return Settings()
