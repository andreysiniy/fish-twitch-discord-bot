from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import settings


engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# NOTE: no MetaData(naming_convention=...) here on purpose. Every constraint in
# the models carries an explicit name, and applying a convention makes Alembic
# autogenerate doubled names for historical migrations (e.g. migration 0010
# re-adds ck_player_modifiers_operation with a convention-prefixed name). The
# stability goal behind a convention is already met by explicit constraint
# names everywhere.
Base = declarative_base()
