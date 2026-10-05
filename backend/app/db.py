import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://datalens:local-development-only@localhost:5432/datalens",
)
STORAGE = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)
