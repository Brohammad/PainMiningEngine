"""Explicit SQLAlchemy engine and session construction."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseSettings(BaseSettings):
    """Database configuration loaded from ``DATABASE_*`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DATABASE_",
        extra="ignore",
    )

    url: str = Field(min_length=1)
    echo: bool = False
    pool_pre_ping: bool = True


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Create an engine without storing it as a global singleton."""

    return create_engine(
        settings.url,
        echo=settings.echo,
        pool_pre_ping=settings.pool_pre_ping,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create an explicit synchronous session factory."""

    return sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
