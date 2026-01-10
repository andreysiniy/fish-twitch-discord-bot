import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

POSTGRES_USER = os.getenv("DB_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("DB_PASSWORD", "password")
POSTGRES_DB = os.getenv("DB_NAME", "fisher_db")

# В Docker Compose имя хоста = имени сервиса базы данных ("postgres")
# Если запускаете локально без докера, можно поставить "localhost"
POSTGRES_SERVER = os.getenv("DB_HOST", "postgres") 
POSTGRES_PORT = os.getenv("DB_PORT", "5432")


DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_SERVER}:{POSTGRES_PORT}/{POSTGRES_DB}"

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()