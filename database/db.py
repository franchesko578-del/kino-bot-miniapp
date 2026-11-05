from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime
from sqlalchemy import func

from config import DATABASE_URL


engine = create_async_engine(DATABASE_URL, echo=False)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    is_vip = Column(Boolean, default=False)
    vip_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    file_id = Column(String(255), nullable=False)
    views = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


async def init_db():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_session():
    async with SessionLocal() as session:
        yield session


class SubscriptionChannel(Base):
    __tablename__ = "subscription_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    invite_link = Column(String(500), nullable=False)
    is_active = Column(Boolean, default=True)
