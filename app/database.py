# app/database.py

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

# -----------------------
# Database URL
# -----------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/busdb"
)

# -----------------------
# Engine
# -----------------------
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,           # Number of connections in the pool
    max_overflow=10,        # Extra connections if pool is full
    pool_timeout=30,        # Seconds to wait before giving up
    pool_recycle=1800,      # Recycle connections every 30 minutes
    echo=False              # Set True for debugging SQL queries
)

# -----------------------
# Session Local (Async)
# -----------------------
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# -----------------------
# Base Model
# -----------------------
Base = declarative_base()

# -----------------------
# Dependency for FastAPI
# -----------------------
async def get_db():
    """
    Provides an async database session for dependency injection.
    Closes the session after request is done.
    """
    async with AsyncSessionLocal() as session:
        yield session
