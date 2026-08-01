from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from infrastructure.database import engine


ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"


def get_schema_revisions() -> tuple[str | None, str | None]:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    scripts = ScriptDirectory.from_config(config)
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current, scripts.get_current_head()
