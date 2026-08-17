from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str
    ADMIN_WS_TOKEN: str
    ENV: str = "dev"

    # --- Face server distant (ton PC, exposé via tunnel) ---
    FACE_SERVER_URL: str
    FACE_SHARED_SECRET: str


settings = Settings()
