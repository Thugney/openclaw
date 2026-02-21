"""Database initialization – create all tables directly from models.

For production, use Alembic migrations.
For dev/docker, this creates tables directly.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import create_async_engine

from .config import load_config
from .db import Base

logger = logging.getLogger("msclaw.db_init")


async def run_migrations() -> None:
    """Create all tables. For docker-compose 'migrate' service."""
    cfg = load_config()
    engine = create_async_engine(cfg.postgres.dsn, echo=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create the append-only trigger
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text("""
                CREATE OR REPLACE FUNCTION audit_entries_immutable()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'audit_entries is append-only: UPDATE and DELETE are forbidden';
                END;
                $$ LANGUAGE plpgsql;
            """)
        )
        await conn.execute(
            __import__("sqlalchemy").text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_entries_immutable'
                    ) THEN
                        CREATE TRIGGER trg_audit_entries_immutable
                        BEFORE UPDATE OR DELETE ON audit_entries
                        FOR EACH ROW EXECUTE FUNCTION audit_entries_immutable();
                    END IF;
                END $$;
            """)
        )

    await engine.dispose()
    logger.info("Database tables created successfully")
    print("Database migrations complete.")
