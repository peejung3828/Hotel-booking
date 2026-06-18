from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_URL: str = "http://localhost:8000"
    APP_NAME: str = "Hotel Booking System"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/hotel_booking"
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    LINE_CHANNEL_SECRET: str = ""
    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    LIFF_ID: str = ""

    UPLOAD_DIR: str = "backend/static/uploads"
    MAX_IMAGE_WIDTH: int = 1200
    MAX_IMAGE_HEIGHT: int = 800

    # Omise payment
    OMISE_PUBLIC_KEY: str = ""
    OMISE_SECRET_KEY: str = ""

    # LINE Pay
    LINE_PAY_CHANNEL_ID: str = ""
    LINE_PAY_CHANNEL_SECRET: str = ""
    LINE_PAY_SANDBOX: bool = True

    # Email (SMTP) for monthly reports
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_FROM: str = ""
    REPORT_EMAIL: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
