import os

from sqlalchemy import create_engine, pool

from alembic import context

config = context.config

MIGRATION_URL = os.environ.get(
    "MIGRATION_DATABASE_URL", "postgresql+psycopg://rs_owner:rs_owner@localhost:5432/reporting"
)
config.set_main_option("app_db_role", os.environ.get("APP_DB_ROLE", "rs_app"))


def run_migrations_online() -> None:
    connectable = create_engine(MIGRATION_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
