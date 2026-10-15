from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "tickerwise"
    DB_USER: str = "siw_app"
    DB_PASSWORD: str = ""

    # Primary provider: TejHQ
    TEJHQ_BASE_URL: str = "https://api.tejhq.dev"
    TEJHQ_TIMEOUT_SECONDS: float = 30.0
    TEJHQ_MAX_RETRIES: int = 3
    TEJHQ_USER_AGENT: str = "TickerWise/1.0 (+https://tejhq.dev)"

    # Supplementary provider: 0xramm / Indian-Stock-Market-API
    # Disabled by default; requires verified authorization for upstream Yahoo Finance collection
    TICKERWISE_0XRAMM_ENABLED: bool = False
    TICKERWISE_0XRAMM_AUTOMATION_PERMISSION_CONFIRMED: bool = False
    TICKERWISE_0XRAMM_BASE_URL: str | None = None
    TICKERWISE_0XRAMM_TIMEOUT_SECONDS: float = 10.0


    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def _resolve_db_name(self) -> str:
        # If DB_NAME is tickerwise, test if accessible; otherwise fallback to stock_intelligence_workbench
        if self.DB_NAME.lower() in ("tickerwise", "ticker_wise"):
            try:
                import pymysql
                conn = pymysql.connect(
                    host=self.DB_HOST,
                    port=self.DB_PORT,
                    user=self.DB_USER,
                    password=self.DB_PASSWORD,
                    database=self.DB_NAME,
                    connect_timeout=1,
                )
                conn.close()
                return self.DB_NAME
            except Exception:
                return "stock_intelligence_workbench"
        return self.DB_NAME

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self._resolve_db_name(),
            query={"charset": "utf8mb4"},
        )


settings = Settings()