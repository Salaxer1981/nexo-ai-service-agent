"""PostgreSQL connections. One short-lived connection per operation keeps the
foundation simple; pooling can be added when load requires it."""
import psycopg

from app.config import Settings

CONNECT_TIMEOUT_SECONDS = 3


def connect(settings: Settings, **kwargs) -> psycopg.Connection:
    # Keyword arguments instead of a DSN string, so no credential-bearing URL is ever built or logged.
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        application_name="nexo-backend",
        **kwargs,
    )
