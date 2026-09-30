from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Modulo a Farfalla"
    secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./touchline.db"
    storage_root: Path = Path("./storage")
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    cookie_secure: bool = False
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "admin12345"
    max_upload_gb: int = 20
    media_acceleration: str = "auto"
    vaapi_device: Path = Path("/dev/dri/renderD128")
    nvenc_device: str = "/dev/nvidia0"
    nvidia_visible_devices: str = "all"
    force_hardware: str = ""
    ffmpeg_threads: int = 2
    background_workers: int = 1
    worker_nice: int = 10
    ai_enabled: bool = True
    ai_python: str = ""
    ai_device: str = "auto"
    ai_batch_size: int = 1

    @property
    def origins(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


settings = Settings()
