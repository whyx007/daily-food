from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    amap_key: str = ""
    amap_js_key: str = ""
    amap_security_code: str = ""
    default_lat: float = 39.90923
    default_lng: float = 116.397428
    daily_call_limit: int = 500
    radius_options: str = "500,1000,2000,3000"
    site_name: str = "今天吃啥"
    admin_token: str = ""
    db_path: str = "daily-food.db"
    qps: int = 3
    rate_limit_per_min: int = 120

    @property
    def radius_list(self) -> list[int]:
        return [int(x.strip()) for x in self.radius_options.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
