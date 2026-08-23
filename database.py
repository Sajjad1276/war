# ================================================================
# اِکو — database.py
# دیتابیس، مدل‌ها، Redis و وضعیت پایدار
# ================================================================
#
# بنویس. بساز. حکومت کن.
#
# مسئولیت این فایل:
#   - اتصال PostgreSQL و SQLAlchemy Async
#   - اتصال Redis
#   - تعریف تمام مدل‌های دیتابیس
#   - کوئری‌های کمکی بازی
#   - مدیریت سِشن و تراکنش
#   - قفل توزیع‌شده
#   - کولداون و نرخ‌گذاری
#
# این فایل شامل موارد زیر نیست:
#   - منطق بازی
#   - هندلر تلگرام
#   - رابط کاربری
# ================================================================

from __future__ import annotations

import asyncio
import contextlib
import enum
import json
import logging
import time
import uuid

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import redis.asyncio as aioredis

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
    update,
)

from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from config import settings, GameConstants


# ================================================================
# لاگر
# ================================================================

logger = logging.getLogger("echo.database")


# ================================================================
# ابزارهای عمومی
# ================================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_postgres_url(raw_url: str) -> str:

    if not raw_url:
        raise RuntimeError("DATABASE_URL تعریف نشده است.")

    raw_url = raw_url.strip()

    replacements = {
        "postgresql+asyncpg://": None,
        "postgresql://": "postgresql+asyncpg://",
        "postgres://": "postgresql+asyncpg://",
        "postgresql+psycopg2://": "postgresql+asyncpg://",
    }

    for prefix, replacement in replacements.items():
        if raw_url.startswith(prefix):
            if replacement is None:
                return raw_url
            return replacement + raw_url[len(prefix):]

    return raw_url


# ================================================================
# آدرس‌های اتصال
# ================================================================

DATABASE_URL = normalize_postgres_url(settings.database_url)
REDIS_URL = settings.redis_url


# ================================================================
# پایه دکلاراتیو
# ================================================================

class Base(DeclarativeBase):
    pass


# ================================================================
# موتور SQLAlchemy
# ================================================================

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ================================================================
# مدیریت سِشن
# ================================================================

@contextlib.asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:

    session = AsyncSessionLocal()

    try:
        yield session
        await session.commit()

    except Exception:
        await session.rollback()
        raise

    finally:
        await session.close()


@contextlib.asynccontextmanager
async def transaction(
    session: AsyncSession,
) -> AsyncIterator[AsyncSession]:

    if session.in_transaction():
        async with session.begin_nested():
            yield session
    else:
        async with session.begin():
            yield session


# ================================================================
# مقداردهی اولیه دیتابیس
# ================================================================

async def init_database() -> None:

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if not await database_health():
        raise RuntimeError("بررسی سلامت PostgreSQL شکست خورد.")

    if not await redis_health():
        raise RuntimeError("بررسی سلامت Redis شکست خورد.")

    logger.info("دیتابیس و Redis با موفقیت راه‌اندازی شدند.")


# ================================================================
# سلامت‌سنجی
# ================================================================

async def database_health() -> bool:

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    except Exception as exc:
        logger.warning("database_health شکست خورد: %s", type(exc).__name__)
        return False


# ================================================================
# Redis
# ================================================================

redis_client: aioredis.Redis = aioredis.from_url(
    REDIS_URL,
    decode_responses=True,
    max_connections=settings.redis_max_connections,
)


async def redis_health() -> bool:

    try:
        return bool(await redis_client.ping())

    except Exception as exc:
        logger.warning("redis_health شکست خورد: %s", type(exc).__name__)
        return False


# ================================================================
# فضای نام کلیدهای Redis
# ================================================================

class RedisKeys:

    @staticmethod
    def session(user_id: int, city_id: int) -> str:
        return f"{settings.redis_prefix}session:{user_id}:{city_id}"

    @staticmethod
    def intent(user_id: int, city_id: int) -> str:
        return f"{settings.redis_prefix}intent:{user_id}:{city_id}"

    @staticmethod
    def cooldown(user_id: int, city_id: int, action: str) -> str:
        return f"{settings.redis_prefix}cooldown:{user_id}:{city_id}:{action}"

    @staticmethod
    def rate_limit(user_id: int, scope: str) -> str:
        return f"{settings.redis_prefix}ratelimit:{scope}:{user_id}"

    @staticmethod
    def lock(key: str) -> str:
        return f"{settings.redis_prefix}lock:{key}"

    @staticmethod
    def cache(namespace: str, key: str) -> str:
        return f"{settings.redis_prefix}cache:{namespace}:{key}"

    @staticmethod
    def daily_eco(user_id: int, city_id: int) -> str:
        return f"{settings.redis_prefix}daily_eco:{user_id}:{city_id}"

    @staticmethod
    def daily_work(user_id: int, city_id: int) -> str:
        return f"{settings.redis_prefix}daily_work:{user_id}:{city_id}"

    @staticmethod
    def event_participant(event_id: int, user_id: int) -> str:
        return f"{settings.redis_prefix}event_part:{event_id}:{user_id}"

    @staticmethod
    def event_progress(event_id: int) -> str:
        return f"{settings.redis_prefix}event_prog:{event_id}"

    @staticmethod
    def contest_score(event_id: int, user_id: int) -> str:
        return f"{settings.redis_prefix}contest:{event_id}:{user_id}"

    @staticmethod
    def income_boost(user_id: int) -> str:
        return f"{settings.redis_prefix}boost:income:{user_id}"

    @staticmethod
    def risk_shield(user_id: int) -> str:
        return f"{settings.redis_prefix}shield:{user_id}"

    @staticmethod
    def streak(user_id: int) -> str:
        return f"{settings.redis_prefix}streak:{user_id}"

    @staticmethod
    def transfer_code(code: str) -> str:
        return f"{settings.redis_prefix}transfer:{code}"

    @staticmethod
    def mine_last_collect(user_id: int) -> str:
        return f"{settings.redis_prefix}mine_collect:{user_id}"


# ================================================================
# سِشن بازی در Redis
# ================================================================

async def set_game_session(
    user_id: int,
    city_id: int,
    state: str,
    payload: Optional[dict[str, Any]] = None,
    ttl_seconds: int = 600,
) -> None:

    key = RedisKeys.session(user_id, city_id)

    data = {
        "state": state,
        "payload": payload or {},
        "updated_at": utcnow().isoformat(),
    }

    await redis_client.set(
        key,
        json.dumps(data, ensure_ascii=False),
        ex=ttl_seconds,
    )


async def get_game_session(
    user_id: int,
    city_id: int,
) -> Optional[dict[str, Any]]:

    key = RedisKeys.session(user_id, city_id)
    raw = await redis_client.get(key)

    if raw is None:
        return None

    return json.loads(raw)


async def clear_game_session(
    user_id: int,
    city_id: int,
) -> None:

    await redis_client.delete(
        RedisKeys.session(user_id, city_id)
    )


# ================================================================
# نیت (Intent) در Redis
# ================================================================

async def set_intent_context(
    user_id: int,
    city_id: int,
    current_intent: str,
    current_state: str,
    context_payload: Optional[dict[str, Any]] = None,
    ttl_seconds: int = 300,
) -> None:

    key = RedisKeys.intent(user_id, city_id)

    data = {
        "current_intent": current_intent,
        "current_state": current_state,
        "context_payload": context_payload or {},
        "updated_at": utcnow().isoformat(),
    }

    await redis_client.set(
        key,
        json.dumps(data, ensure_ascii=False),
        ex=ttl_seconds,
    )


async def get_intent_context(
    user_id: int,
    city_id: int,
) -> Optional[dict[str, Any]]:

    key = RedisKeys.intent(user_id, city_id)
    raw = await redis_client.get(key)

    if raw is None:
        return None

    return json.loads(raw)


async def clear_intent_context(
    user_id: int,
    city_id: int,
) -> None:

    await redis_client.delete(
        RedisKeys.intent(user_id, city_id)
    )


# ================================================================
# کولداون
# ================================================================

async def set_cooldown(
    user_id: int,
    city_id: int,
    action: str,
    seconds: int,
) -> None:

    await redis_client.set(
        RedisKeys.cooldown(user_id, city_id, action),
        "1",
        ex=seconds,
    )


async def is_on_cooldown(
    user_id: int,
    city_id: int,
    action: str,
) -> bool:

    return bool(
        await redis_client.exists(
            RedisKeys.cooldown(user_id, city_id, action)
        )
    )


async def cooldown_ttl(
    user_id: int,
    city_id: int,
    action: str,
) -> int:

    ttl = await redis_client.ttl(
        RedisKeys.cooldown(user_id, city_id, action)
    )

    return max(ttl, 0)


# ================================================================
# محدودیت روزانه
# ================================================================

async def increment_daily_counter(
    key: str,
    max_value: int,
) -> tuple[bool, int]:
    """
    شمارنده روزانه را یک واحد افزایش می‌دهد.
    اگر از حداکثر تجاوز کرده باشد، False برمی‌گرداند.
    مقدار فعلی هم برگردانده می‌شود.
    """

    current = await redis_client.get(key)
    current_int = int(current) if current else 0

    if current_int >= max_value:
        return False, current_int

    pipe = redis_client.pipeline()
    pipe.incr(key)

    # TTL تا پایان روز (به صورت تقریبی ۲۴ ساعت)
    pipe.expire(key, 86_400)
    await pipe.execute()

    return True, current_int + 1


async def get_daily_counter(key: str) -> int:

    value = await redis_client.get(key)
    return int(value) if value else 0


async def reset_daily_counter(key: str) -> None:

    await redis_client.delete(key)


# ================================================================
# بوست درآمد
# ================================================================

async def set_income_boost(
    user_id: int,
    ttl_seconds: int = 86_400,
) -> None:

    await redis_client.set(
        RedisKeys.income_boost(user_id),
        "1",
        ex=ttl_seconds,
    )


async def has_income_boost(user_id: int) -> bool:

    return bool(
        await redis_client.exists(
            RedisKeys.income_boost(user_id)
        )
    )


# ================================================================
# سپر ریسک
# ================================================================

async def set_risk_shield(user_id: int) -> None:

    await redis_client.set(
        RedisKeys.risk_shield(user_id),
        "1",
    )


async def consume_risk_shield(user_id: int) -> bool:
    """
    اگر سپر وجود داشت، مصرف می‌کند و True برمی‌گرداند.
    """

    key = RedisKeys.risk_shield(user_id)
    result = await redis_client.delete(key)
    return bool(result)


# ================================================================
# استریک روزانه
# ================================================================

async def get_streak(user_id: int) -> dict[str, Any]:

    key = RedisKeys.streak(user_id)
    raw = await redis_client.get(key)

    if raw is None:
        return {"days": 0, "last_date": ""}

    return json.loads(raw)


async def update_streak(user_id: int) -> dict[str, Any]:
    """
    استریک را به‌روز می‌کند.
    اگر دیروز فعال بوده، استریک ادامه می‌یابد.
    اگر بیشتر از یک روز گذشته باشد، از صفر شروع می‌شود.
    """

    from datetime import date, timedelta

    key = RedisKeys.streak(user_id)
    today = date.today().isoformat()

    current = await get_streak(user_id)
    last_date = current.get("last_date", "")
    days = current.get("days", 0)

    if last_date == today:
        return current

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    if last_date == yesterday:
        days = min(days + 1, settings.streak_max_days)
    else:
        days = 1

    data = {"days": days, "last_date": today}

    await redis_client.set(
        key,
        json.dumps(data),
        ex=172_800,  # ۴۸ ساعت
    )

    return data


# ================================================================
# پیشرفت رویداد جمعی
# ================================================================

async def increment_event_progress(
    event_id: int,
    amount: int = 1,
) -> int:

    key = RedisKeys.event_progress(event_id)
    result = await redis_client.incrbyfloat(key, amount)
    return int(result)


async def get_event_progress(event_id: int) -> int:

    key = RedisKeys.event_progress(event_id)
    value = await redis_client.get(key)
    return int(float(value)) if value else 0


async def set_event_participant(
    event_id: int,
    user_id: int,
    contribution: int,
    ttl_seconds: int = 86_400,
) -> None:

    key = RedisKeys.event_participant(event_id, user_id)
    await redis_client.set(key, str(contribution), ex=ttl_seconds)


async def get_event_contribution(
    event_id: int,
    user_id: int,
) -> int:

    key = RedisKeys.event_participant(event_id, user_id)
    value = await redis_client.get(key)
    return int(value) if value else 0


async def is_event_participant(
    event_id: int,
    user_id: int,
) -> bool:

    return bool(
        await redis_client.exists(
            RedisKeys.event_participant(event_id, user_id)
        )
    )


# ================================================================
# امتیاز رقابت
# ================================================================

async def add_contest_score(
    event_id: int,
    user_id: int,
    score: int,
) -> int:

    key = RedisKeys.contest_score(event_id, user_id)
    return int(await redis_client.incrbyfloat(key, score))


async def get_contest_leaderboard(
    event_id: int,
    top_n: int = 10,
) -> list[tuple[int, int]]:
    """
    لیست برترین شرکت‌کنندگان رقابت.
    هر عنصر: (user_id, score)
    """

    pattern = f"{settings.redis_prefix}contest:{event_id}:*"
    keys = await redis_client.keys(pattern)

    if not keys:
        return []

    scores = []
    for key in keys:
        value = await redis_client.get(key)
        if value:
            user_id = int(key.split(":")[-1])
            scores.append((user_id, int(float(value))))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_n]


# ================================================================
# کد انتقال اکانت
# ================================================================

async def set_transfer_code(
    code: str,
    user_id: int,
    declared_value: int,
) -> None:

    key = RedisKeys.transfer_code(code)

    data = {
        "user_id": user_id,
        "declared_value": declared_value,
        "created_at": utcnow().isoformat(),
    }

    await redis_client.set(
        key,
        json.dumps(data),
        ex=settings.account_transfer_code_ttl,
    )


async def get_transfer_code(
    code: str,
) -> Optional[dict[str, Any]]:

    key = RedisKeys.transfer_code(code)
    raw = await redis_client.get(key)

    if raw is None:
        return None

    return json.loads(raw)


async def delete_transfer_code(code: str) -> None:

    await redis_client.delete(
        RedisKeys.transfer_code(code)
    )


# ================================================================
# قفل توزیع‌شده
# ================================================================

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def acquire_lock(
    key: str,
    ttl_seconds: int = 10,
) -> Optional[str]:

    token = uuid.uuid4().hex
    full_key = RedisKeys.lock(key)

    acquired = await redis_client.set(
        full_key,
        token,
        nx=True,
        ex=ttl_seconds,
    )

    return token if acquired else None


async def release_lock(key: str, token: str) -> bool:

    full_key = RedisKeys.lock(key)

    result = await redis_client.eval(
        _RELEASE_LOCK_SCRIPT,
        1,
        full_key,
        token,
    )

    return bool(result)


@contextlib.asynccontextmanager
async def distributed_lock(
    key: str,
    ttl_seconds: int = 10,
    wait_seconds: float = 5.0,
    retry_interval: float = 0.1,
) -> AsyncIterator[bool]:

    deadline = time.monotonic() + wait_seconds
    token: Optional[str] = None

    while True:
        token = await acquire_lock(key, ttl_seconds=ttl_seconds)

        if token:
            break

        if time.monotonic() >= deadline:
            break

        await asyncio.sleep(retry_interval)

    try:
        yield token is not None

    finally:
        if token:
            await release_lock(key, token)


# ================================================================
# شمارنده نرخ‌گذاری
# ================================================================

async def check_rate_limit(
    user_id: int,
    scope: str = "global",
) -> bool:
    """
    بررسی محدودیت نرخ پیام.
    True یعنی مجاز است. False یعنی محدود شده.
    """

    key = RedisKeys.rate_limit(user_id, scope)
    now = time.time()
    window = settings.rate_limit_window_seconds

    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window * 2)

    results = await pipe.execute()
    count = results[1]

    return count < settings.rate_limit_messages


# ================================================================
# اِنام‌ها (Enums)
# ================================================================

class CityMemberRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class GuildMemberRole(str, enum.Enum):
    FOUNDER = "founder"
    OFFICER = "officer"
    MEMBER = "member"


class MissionStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class MissionType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    SPECIAL = "special"


class EventType(str, enum.Enum):
    CRISIS = "crisis"
    ATTACK = "attack"
    FESTIVAL = "festival"
    CONTEST = "contest"
    EXPLORE = "explore"


class EventStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"


class MineLevel(str, enum.Enum):
    DIRT = "dirt"
    STONE = "stone"
    IRON = "iron"
    GOLD = "gold"
    CRYSTAL = "crystal"


class JobType(str, enum.Enum):
    LABORER = "laborer"
    TRADER = "trader"
    DETECTIVE = "detective"
    HACKER = "hacker"


class TransactionType(str, enum.Enum):
    WORK = "work"
    EXPLORE = "explore"
    MISSION = "mission"
    EVENT = "event"
    TRANSFER = "transfer"
    MARKET = "market"
    MINE = "mine"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    PURCHASE = "purchase"
    PENALTY = "penalty"
    BONUS = "bonus"
    STREAK = "streak"
    CITY_TAX = "city_tax"


class SubscriptionType(str, enum.Enum):
    GOLD = "gold"
    ADMIN_PLAN = "admin_plan"


# ================================================================
# مدل: کاربر
# ================================================================

class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
    )

    username: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    display_name: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # الماس (پریمیوم)
    diamonds: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
    )

    # اشتراک طلایی
    gold_subscription_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # مسدود شده؟
    is_banned: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # روابط
    stats: Mapped["UserStats"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    memberships: Mapped[list["CityMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    wallets: Mapped[list["UserWallet"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    mine: Mapped[Optional["UserMine"]] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_users_username", "username"),
    )


# ================================================================
# مدل: آمار جهانی کاربر
# ================================================================

class UserStats(Base):

    __tablename__ = "user_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # سطح و تجربه جهانی
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # شهرت جهانی
    fame: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # مجموع اِکوی کسب‌شده در طول عمر
    total_eco_earned: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # مجموع کارهای انجام‌شده
    total_works: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # مجموع اکتشاف‌ها
    total_explores: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # مجموع مأموریت‌های تکمیل‌شده
    total_missions_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # مجموع رویدادهای شرکت‌کرده
    total_events_participated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # استریک فعلی (روز)
    current_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # بیشترین استریک
    max_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # کشف‌های ویژه
    special_discoveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # کشف‌های افسانه‌ای
    legendary_discoveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="stats")


# ================================================================
# مدل: شهر
# ================================================================

class City(Base):

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)

    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # کد منحصربه‌فرد شهر
    city_code: Mapped[Optional[str]] = mapped_column(
        String(32),
        unique=True,
        nullable=True,
    )

    # نام سفارشی (توسط پلن ادمین)
    custom_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # سطح شهر
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # مجموع آجرهای ساخته‌شده
    total_bricks: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # خزانه شهر
    treasury: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # مالک
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # پلن ادمین فعال است؟
    has_admin_plan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    admin_plan_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # آخرین رویداد جمعی
    last_event_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    # روابط
    members: Mapped[list["CityMember"]] = relationship(
        back_populates="city",
        cascade="all, delete-orphan",
    )

    wallets: Mapped[list["UserWallet"]] = relationship(
        back_populates="city",
        cascade="all, delete-orphan",
    )

    events: Mapped[list["CityEvent"]] = relationship(
        back_populates="city",
        cascade="all, delete-orphan",
    )

    history: Mapped[list["CityHistory"]] = relationship(
        back_populates="city",
        cascade="all, delete-orphan",
    )

    missions: Mapped[list["Mission"]] = relationship(
        back_populates="city",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_cities_telegram_chat_id", "telegram_chat_id"),
    )


# ================================================================
# مدل: عضو شهر
# ================================================================

class CityMember(Base):

    __tablename__ = "city_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    city_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(16),
        default=CityMemberRole.MEMBER.value,
        nullable=False,
    )

    # انرژی (محلی — برای هر شهر جداست)
    energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # شهرت محلی
    city_reputation: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # مشارکت کل
    contribution: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # آجرهای ساخته‌شده توسط این کاربر در این شهر
    bricks_contributed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # شغل فعلی
    current_job: Mapped[str] = mapped_column(
        String(16),
        default=JobType.LABORER.value,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # روابط
    city: Mapped["City"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("city_id", "user_id", name="uq_citymember_city_user"),
        Index("ix_citymembers_city_id", "city_id"),
        Index("ix_citymembers_user_id", "user_id"),
    )


# ================================================================
# مدل: کیف پول کاربر در شهر
# ================================================================

class UserWallet(Base):

    __tablename__ = "user_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    city_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )

    # پول نقد
    cash: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # بانک (امن)
    bank: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="wallets")
    city: Mapped["City"] = relationship(back_populates="wallets")

    __table_args__ = (
        UniqueConstraint("user_id", "city_id", name="uq_wallet_user_city"),
        Index("ix_wallets_user_id", "user_id"),
        Index("ix_wallets_city_id", "city_id"),
    )


# ================================================================
# مدل: معدن کاربر (جهانی)
# ================================================================

class UserMine(Base):

    __tablename__ = "user_mines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    level: Mapped[str] = mapped_column(
        String(16),
        default=MineLevel.DIRT.value,
        nullable=False,
    )

    # اِکوی جمع‌شده در معدن (هنوز برداشت نشده)
    accumulated_eco: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # آخرین بار که تولید محاسبه شد
    last_calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    # آخرین بار که برداشت شد
    last_collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="mine")


# ================================================================
# مدل: رویداد جمعی شهر
# ================================================================

class CityEvent(Base):

    __tablename__ = "city_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    city_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String(16), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        default=EventStatus.PENDING.value,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(128), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # هدف عددی رویداد (مثلاً مقدار اِکو یا تعداد شرکت‌کننده)
    target_value: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # پیشرفت فعلی
    current_value: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # شناسه پیام تلگرام (برای به‌روزرسانی)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # اطلاعات اضافه
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    city: Mapped["City"] = relationship(back_populates="events")

    participants: Mapped[list["EventParticipant"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_cityevents_city_id", "city_id"),
        Index("ix_cityevents_status", "status"),
        Index("ix_cityevents_ends_at", "ends_at"),
    )


# ================================================================
# مدل: شرکت‌کننده رویداد
# ================================================================

class EventParticipant(Base):

    __tablename__ = "event_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("city_events.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    contribution: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    rewarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    event: Mapped["CityEvent"] = relationship(back_populates="participants")

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_eventpart_event_user"),
        Index("ix_eventparticipants_event_id", "event_id"),
    )


# ================================================================
# مدل: مأموریت
# ================================================================

class Mission(Base):

    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    city_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=True,
    )

    mission_type: Mapped[str] = mapped_column(
        String(16),
        default=MissionType.DAILY.value,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(128), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # نوع هدف (work_count, eco_amount, explore_count, event_participate)
    goal_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # مقدار هدف
    goal_value: Mapped[int] = mapped_column(Integer, nullable=False)

    reward_eco: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reward_xp: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reward_diamonds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    energy_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    difficulty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    city: Mapped[Optional["City"]] = relationship(back_populates="missions")

    progress_records: Mapped[list["MissionProgress"]] = relationship(
        back_populates="mission",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_missions_city_id", "city_id"),
        Index("ix_missions_type", "mission_type"),
    )


# ================================================================
# مدل: پیشرفت مأموریت
# ================================================================

class MissionProgress(Base):

    __tablename__ = "mission_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    city_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )

    mission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )

    current_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        default=MissionStatus.IN_PROGRESS.value,
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mission: Mapped["Mission"] = relationship(back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "city_id", "mission_id",
            name="uq_missionprogress_user_city_mission",
        ),
        Index("ix_missionprogress_user_city", "user_id", "city_id"),
    )


# ================================================================
# مدل: گیلد
# ================================================================

class Guild(Base):

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    city_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    founder_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    treasury: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    max_members: Mapped[int] = mapped_column(
        Integer,
        default=settings.guild_max_members,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    members: Mapped[list["GuildMember"]] = relationship(
        back_populates="guild",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("city_id", "name", name="uq_guild_city_name"),
        Index("ix_guilds_city_id", "city_id"),
    )


# ================================================================
# مدل: عضو گیلد
# ================================================================

class GuildMember(Base):

    __tablename__ = "guild_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    guild_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(16),
        default=GuildMemberRole.MEMBER.value,
        nullable=False,
    )

    contribution: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    guild: Mapped["Guild"] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_guildmember_guild_user"),
        Index("ix_guildmembers_user_id", "user_id"),
    )


# ================================================================
# مدل: تاریخچه شهر
# ================================================================

class CityHistory(Base):

    __tablename__ = "city_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    city_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    history_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    city: Mapped["City"] = relationship(
        back_populates="history",
    )

    __table_args__ = (
        Index("ix_cityhistory_city_id", "city_id"),
        Index("ix_cityhistory_created_at", "created_at"),
    )

# ================================================================
# مدل: تراکنش مالی
# ================================================================

class Transaction(Base):

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    city_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="SET NULL"),
        nullable=True,
    )

    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)

    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)

    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)

    description: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_transactions_user_id", "user_id"),
        Index("ix_transactions_city_id", "city_id"),
        Index("ix_transactions_created_at", "created_at"),
    )


# ================================================================
# مدل: اشتراک
# ================================================================

class UserSubscription(Base):

    __tablename__ = "user_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    subscription_type: Mapped[str] = mapped_column(String(32), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    amount_paid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="subscriptions")

    __table_args__ = (
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_expires_at", "expires_at"),
    )


# ================================================================
# خطاهای سفارشی
# ================================================================

class InsufficientFundsError(Exception):
    """موجودی کافی نیست."""
    pass


class InsufficientEnergyError(Exception):
    """انرژی کافی نیست."""
    pass


class InsufficientDiamondsError(Exception):
    """الماس کافی نیست."""
    pass


# ================================================================
# کوئری: کاربر
# ================================================================

async def get_user(
    session: AsyncSession,
    user_id: int,
) -> Optional[User]:

    result = await session.execute(
        select(User).where(User.id == user_id)
    )

    return result.scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str] = None,
    display_name: Optional[str] = None,
) -> tuple[User, bool]:
    """
    کاربر را پیدا یا ایجاد می‌کند.
    مقدار دوم True یعنی تازه ایجاد شده.
    """

    user = await get_user(session, user_id)

    if user is not None:

        changed = False

        if username is not None and user.username != username:
            user.username = username
            changed = True

        if display_name and user.display_name != display_name:
            user.display_name = display_name[:64]
            changed = True

        if changed:
            user.last_active_at = utcnow()
            await session.flush()

        return user, False

    # ساخت کاربر جدید
    user = User(
        id=user_id,
        username=username,
        display_name=display_name[:64] if display_name else None,
        is_active=True,
        diamonds=0,
    )

    session.add(user)
    await session.flush()

    # آمار اولیه
    stats = UserStats(
        user_id=user_id,
        level=1,
        xp=0,
        fame=0,
    )

    session.add(stats)
    await session.flush()

    return user, True


async def get_user_stats(
    session: AsyncSession,
    user_id: int,
) -> Optional[UserStats]:

    result = await session.execute(
        select(UserStats).where(UserStats.user_id == user_id)
    )

    return result.scalar_one_or_none()


async def add_xp_and_check_level(
    session: AsyncSession,
    user_id: int,
    xp_amount: int,
) -> dict[str, Any]:
    """
    XP اضافه می‌کند و سطح را بررسی می‌کند.
    نتیجه شامل: xp_added, new_xp, old_level, new_level, leveled_up
    """

    result = await session.execute(
        select(UserStats)
        .where(UserStats.user_id == user_id)
        .with_for_update()
    )

    stats = result.scalar_one_or_none()

    if stats is None:
        return {
            "xp_added": 0,
            "new_xp": 0,
            "old_level": 1,
            "new_level": 1,
            "leveled_up": False,
        }

    old_level = stats.level
    stats.xp += xp_amount

    # بررسی لول‌آپ
    new_level = old_level

    while new_level < settings.max_level:

        xp_needed = settings.xp_required_for_level(new_level + 1)

        if stats.xp >= settings.total_xp_for_level(new_level + 1):
            new_level += 1
        else:
            break

    stats.level = new_level
    stats.updated_at = utcnow()

    await session.flush()

    return {
        "xp_added": xp_amount,
        "new_xp": stats.xp,
        "old_level": old_level,
        "new_level": new_level,
        "leveled_up": new_level > old_level,
    }


async def add_diamonds(
    session: AsyncSession,
    user_id: int,
    amount: int,
) -> int:
    """
    الماس اضافه می‌کند و مقدار جدید برمی‌گرداند.
    """

    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
    )

    user = result.scalar_one_or_none()

    if user is None:
        return 0

    user.diamonds += amount
    await session.flush()

    return user.diamonds


async def spend_diamonds(
    session: AsyncSession,
    user_id: int,
    amount: int,
) -> int:
    """
    الماس کم می‌کند. اگر کافی نباشد خطا می‌دهد.
    """

    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
    )

    user = result.scalar_one_or_none()

    if user is None or user.diamonds < amount:
        raise InsufficientDiamondsError(
            f"الماس کافی نیست. موجودی: {user.diamonds if user else 0}"
        )

    user.diamonds -= amount
    await session.flush()

    return user.diamonds


# ================================================================
# کوئری: شهر
# ================================================================

async def get_city_by_chat(
    session: AsyncSession,
    telegram_chat_id: int,
) -> Optional[City]:

    result = await session.execute(
        select(City).where(City.telegram_chat_id == telegram_chat_id)
    )

    return result.scalar_one_or_none()


async def get_or_restore_city(
    session: AsyncSession,
    telegram_chat_id: int,
    name: str,
    username: Optional[str] = None,
    owner_user_id: Optional[int] = None,
) -> City:
    """
    شهر را پیدا یا ایجاد می‌کند.
    اگر وجود داشته باشد، اطلاعاتش را به‌روز می‌کند.
    """

    city = await get_city_by_chat(session, telegram_chat_id)

    if city is not None:

        city.is_active = True
        city.name = name or city.name
        city.username = username
        city.updated_at = utcnow()

        if owner_user_id and city.owner_user_id is None:
            city.owner_user_id = owner_user_id

        await session.flush()
        return city

    # ساخت شهر جدید
    city = City(
        telegram_chat_id=telegram_chat_id,
        city_code="EC-" + uuid.uuid4().hex[:8].upper(),
        name=name or "شهر اِکو",
        username=username,
        owner_user_id=owner_user_id,
        is_active=True,
        level=1,
        total_bricks=0,
        treasury=0,
    )

    session.add(city)
    await session.flush()

    return city


async def deactivate_city(
    session: AsyncSession,
    telegram_chat_id: int,
) -> None:

    city = await get_city_by_chat(session, telegram_chat_id)

    if city:
        city.is_active = False
        city.updated_at = utcnow()
        await session.flush()


async def add_bricks_to_city(
    session: AsyncSession,
    city_id: int,
    user_id: int,
    bricks: int,
) -> dict[str, Any]:
    """
    آجر به شهر اضافه می‌کند و سطح را بررسی می‌کند.
    """

    city_result = await session.execute(
        select(City)
        .where(City.id == city_id)
        .with_for_update()
    )

    city = city_result.scalar_one_or_none()

    if city is None:
        return {"leveled_up": False, "new_level": 1}

    old_level = city.level
    city.total_bricks += bricks

    # بررسی لول‌آپ شهر
    new_level = old_level

    while new_level < settings.city_max_level:

        bricks_needed = settings.city_bricks_for_level(new_level + 1)

        if city.total_bricks >= bricks_needed:
            new_level += 1
        else:
            break

    city.level = new_level
    city.updated_at = utcnow()

    # ثبت مشارکت عضو
    member_result = await session.execute(
        select(CityMember)
        .where(
            CityMember.city_id == city_id,
            CityMember.user_id == user_id,
        )
    )

    member = member_result.scalar_one_or_none()

    if member:
        member.bricks_contributed += bricks
        member.contribution += bricks

    await session.flush()

    return {
        "leveled_up": new_level > old_level,
        "old_level": old_level,
        "new_level": new_level,
        "total_bricks": city.total_bricks,
        "bricks_for_next": settings.city_bricks_for_level(new_level + 1),
    }


# ================================================================
# کوئری: عضویت
# ================================================================

async def get_city_member(
    session: AsyncSession,
    city_id: int,
    user_id: int,
) -> Optional[CityMember]:

    result = await session.execute(
        select(CityMember).where(
            CityMember.city_id == city_id,
            CityMember.user_id == user_id,
        )
    )

    return result.scalar_one_or_none()


async def get_or_create_city_member(
    session: AsyncSession,
    city_id: int,
    user_id: int,
    role: str = CityMemberRole.MEMBER.value,
) -> tuple[CityMember, bool]:
    """
    عضویت را پیدا یا ایجاد می‌کند.
    کیف پول هم به صورت خودکار ایجاد می‌شود.
    مقدار دوم True یعنی تازه ایجاد شده.
    """

    member = await get_city_member(session, city_id, user_id)

    if member is not None:
        member.is_active = True
        member.last_active_at = utcnow()
        await session.flush()

        # اطمینان از وجود کیف پول
        wallet = await get_wallet(session, user_id, city_id)
        if wallet is None:
            wallet = UserWallet(user_id=user_id, city_id=city_id, cash=0, bank=0)
            session.add(wallet)
            await session.flush()

        return member, False

    # عضویت جدید
    member = CityMember(
        city_id=city_id,
        user_id=user_id,
        role=role,
        energy=settings.max_energy,
        city_reputation=0,
        contribution=0,
        bricks_contributed=0,
        current_job=JobType.LABORER.value,
        is_active=True,
    )

    session.add(member)
    await session.flush()

    # کیف پول اولیه
    wallet = UserWallet(
        user_id=user_id,
        city_id=city_id,
        cash=settings.starting_eco,
        bank=0,
    )

    session.add(wallet)
    await session.flush()

    return member, True


async def restore_energy_for_city(
    session: AsyncSession,
    city_id: int,
    amount: int,
) -> int:
    """
    انرژی همه اعضای فعال یک شهر را بازیابی می‌کند.
    تعداد اعضای به‌روزشده برمی‌گردد.
    """

    result = await session.execute(
        select(CityMember).where(
            CityMember.city_id == city_id,
            CityMember.is_active.is_(True),
            CityMember.energy < settings.max_energy,
        )
    )

    members = result.scalars().all()
    count = 0

    for member in members:
        member.energy = min(
            member.energy + amount,
            settings.max_energy,
        )
        count += 1

    if count > 0:
        await session.flush()

    return count


# ================================================================
# کوئری: کیف پول
# ================================================================

async def get_wallet(
    session: AsyncSession,
    user_id: int,
    city_id: int,
) -> Optional[UserWallet]:

    result = await session.execute(
        select(UserWallet).where(
            UserWallet.user_id == user_id,
            UserWallet.city_id == city_id,
        )
    )

    return result.scalar_one_or_none()


async def apply_wallet_delta(
    session: AsyncSession,
    user_id: int,
    city_id: int,
    cash_delta: int = 0,
    bank_delta: int = 0,
    allow_negative: bool = False,
) -> UserWallet:
    """
    کیف پول را با قفل به‌روز می‌کند.
    """

    result = await session.execute(
        select(UserWallet)
        .where(
            UserWallet.user_id == user_id,
            UserWallet.city_id == city_id,
        )
        .with_for_update()
    )

    wallet = result.scalar_one_or_none()

    if wallet is None:
        wallet = UserWallet(user_id=user_id, city_id=city_id, cash=0, bank=0)
        session.add(wallet)
        await session.flush()

    new_cash = wallet.cash + cash_delta
    new_bank = wallet.bank + bank_delta

    if not allow_negative and (new_cash < 0 or new_bank < 0):
        raise InsufficientFundsError(
            f"موجودی کافی نیست. نقد: {wallet.cash} | بانک: {wallet.bank}"
        )

    wallet.cash = new_cash
    wallet.bank = new_bank
    wallet.updated_at = utcnow()

    await session.flush()

    # ثبت در آمار کلی
    if cash_delta > 0 or bank_delta > 0:
        total_earned = max(cash_delta, 0) + max(bank_delta, 0)
        await session.execute(
            update(UserStats)
            .where(UserStats.user_id == user_id)
            .values(total_eco_earned=UserStats.total_eco_earned + total_earned)
        )

    return wallet


async def transfer_eco_between_cities(
    session: AsyncSession,
    user_id: int,
    from_city_id: int,
    to_city_id: int,
    amount: int,
) -> dict[str, Any]:
    """
    انتقال اِکو بین دو شهر با کسر مالیات.
    """

    tax = int(amount * settings.city_transfer_tax / 100)
    net_amount = amount - tax

    # کسر از شهر مبدأ
    await apply_wallet_delta(
        session,
        user_id,
        from_city_id,
        cash_delta=-amount,
    )

    # افزودن به شهر مقصد
    await apply_wallet_delta(
        session,
        user_id,
        to_city_id,
        cash_delta=net_amount,
    )

    # مالیات به خزانه شهر مبدأ
    if tax > 0:
        city_result = await session.execute(
            select(City)
            .where(City.id == from_city_id)
            .with_for_update()
        )

        city = city_result.scalar_one_or_none()

        if city:
            city.treasury += tax
            await session.flush()

    return {
        "amount": amount,
        "tax": tax,
        "net_amount": net_amount,
    }


# ================================================================
# کوئری: معدن
# ================================================================

async def get_or_create_mine(
    session: AsyncSession,
    user_id: int,
) -> Optional[UserMine]:

    result = await session.execute(
        select(UserMine).where(UserMine.user_id == user_id)
    )

    return result.scalar_one_or_none()


async def calculate_mine_production(
    session: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    """
    تولید معدن را از آخرین محاسبه تا الان حساب می‌کند.
    """

    result = await session.execute(
        select(UserMine)
        .where(UserMine.user_id == user_id)
        .with_for_update()
    )

    mine = result.scalar_one_or_none()

    if mine is None:
        return {"produced": 0, "accumulated": 0}

    now = utcnow()
    hours_elapsed = (
        now - mine.last_calculated_at
    ).total_seconds() / 3600

    hourly = settings.mine_hourly_production(mine.level)
    max_storage = hourly * settings.mine_max_storage_hours

    produced = int(hours_elapsed * hourly)
    mine.accumulated_eco = min(
        mine.accumulated_eco + produced,
        max_storage,
    )

    mine.last_calculated_at = now
    await session.flush()

    return {
        "produced": produced,
        "accumulated": mine.accumulated_eco,
        "hourly_rate": hourly,
        "max_storage": max_storage,
        "level": mine.level,
    }


async def collect_mine(
    session: AsyncSession,
    user_id: int,
    city_id: int,
) -> dict[str, Any]:
    """
    اِکوی انباشته‌شده معدن را برداشت می‌کند.
    """

    production = await calculate_mine_production(session, user_id)

    result = await session.execute(
        select(UserMine)
        .where(UserMine.user_id == user_id)
        .with_for_update()
    )

    mine = result.scalar_one_or_none()

    if mine is None or mine.accumulated_eco <= 0:
        return {"collected": 0, "accumulated": 0}

    amount = mine.accumulated_eco
    mine.accumulated_eco = 0
    mine.last_collected_at = utcnow()

    await apply_wallet_delta(session, user_id, city_id, cash_delta=amount)

    return {
        "collected": amount,
        "accumulated": 0,
        "level": mine.level,
    }


# ================================================================
# کوئری: رویداد جمعی
# ================================================================

async def get_active_event(
    session: AsyncSession,
    city_id: int,
) -> Optional[CityEvent]:

    now = utcnow()

    result = await session.execute(
        select(CityEvent).where(
            CityEvent.city_id == city_id,
            CityEvent.status == EventStatus.ACTIVE.value,
            CityEvent.ends_at > now,
        )
    )

    return result.scalar_one_or_none()


async def create_city_event(
    session: AsyncSession,
    city_id: int,
    event_type: str,
    title: str,
    description: str,
    target_value: int,
    duration_seconds: int,
    payload: Optional[dict[str, Any]] = None,
) -> CityEvent:

    from datetime import timedelta

    now = utcnow()

    event = CityEvent(
        city_id=city_id,
        event_type=event_type,
        status=EventStatus.ACTIVE.value,
        title=title,
        description=description,
        target_value=target_value,
        current_value=0,
        payload=payload or {},
        starts_at=now,
        ends_at=now + timedelta(seconds=duration_seconds),
    )

    session.add(event)
    await session.flush()

    # به‌روزرسانی آخرین رویداد شهر
    city_result = await session.execute(
        select(City).where(City.id == city_id)
    )

    city = city_result.scalar_one_or_none()

    if city:
        city.last_event_at = now
        await session.flush()

    return event


async def add_event_participation(
    session: AsyncSession,
    event_id: int,
    user_id: int,
    contribution: int,
) -> tuple[EventParticipant, bool]:
    """
    شرکت در رویداد را ثبت می‌کند.
    مقدار دوم True یعنی اولین بار شرکت کرده.
    """

    result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == user_id,
        )
    )

    participant = result.scalar_one_or_none()
    is_new = False

    if participant is None:
        participant = EventParticipant(
            event_id=event_id,
            user_id=user_id,
            contribution=contribution,
        )
        session.add(participant)
        is_new = True
    else:
        participant.contribution += contribution

    # به‌روزرسانی مقدار فعلی رویداد
    event_result = await session.execute(
        select(CityEvent)
        .where(CityEvent.id == event_id)
        .with_for_update()
    )

    event = event_result.scalar_one_or_none()

    if event:
        event.current_value += contribution

        # بررسی رسیدن به هدف
        if event.current_value >= event.target_value:
            event.status = EventStatus.SUCCESS.value

    await session.flush()

    return participant, is_new


# ================================================================
# کوئری: رتبه‌بندی
# ================================================================

async def get_city_leaderboard(
    session: AsyncSession,
    city_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:

    result = await session.execute(
        select(
            User,
            UserStats,
            UserWallet,
            CityMember,
        )
        .join(CityMember, CityMember.user_id == User.id)
        .join(UserStats, UserStats.user_id == User.id)
        .join(
            UserWallet,
            (UserWallet.user_id == User.id)
            & (UserWallet.city_id == city_id),
        )
        .where(
            CityMember.city_id == city_id,
            CityMember.is_active.is_(True),
        )
        .order_by(
            UserStats.level.desc(),
            UserStats.xp.desc(),
            CityMember.city_reputation.desc(),
        )
        .limit(limit)
    )

    rows = result.all()

    return [
        {
            "user": user,
            "stats": stats,
            "wallet": wallet,
            "member": member,
            "total_eco": wallet.cash + wallet.bank,
        }
        for user, stats, wallet, member in rows
    ]


async def get_city_population(
    session: AsyncSession,
    city_id: int,
) -> int:

    result = await session.execute(
        select(func.count(CityMember.id)).where(
            CityMember.city_id == city_id,
            CityMember.is_active.is_(True),
        )
    )

    return int(result.scalar_one() or 0)


# ================================================================
# کوئری: تاریخچه شهر
# ================================================================

async def add_city_history(
    session: AsyncSession,
    city_id: int,
    event_type: str,
    title: str,
    actor_user_id: Optional[int] = None,
    description: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> CityHistory:

    record = CityHistory(
        city_id=city_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        title=title,
        description=description,
        metadata=metadata or {},
    )

    session.add(record)
    await session.flush()

    return record


async def get_city_history(
    session: AsyncSession,
    city_id: int,
    limit: int = 20,
) -> list[CityHistory]:

    result = await session.execute(
        select(CityHistory)
        .where(CityHistory.city_id == city_id)
        .order_by(CityHistory.created_at.desc())
        .limit(limit)
    )

    return list(result.scalars().all())


# ================================================================
# کوئری: مأموریت
# ================================================================

async def get_active_missions(
    session: AsyncSession,
    city_id: int,
    mission_type: str,
) -> list[Mission]:

    now = utcnow()

    result = await session.execute(
        select(Mission).where(
            Mission.is_active.is_(True),
            Mission.mission_type == mission_type,
            (Mission.city_id == city_id) | (Mission.city_id.is_(None)),
            (Mission.expires_at.is_(None)) | (Mission.expires_at > now),
        )
        .order_by(Mission.difficulty.asc())
        .limit(5)
    )

    return list(result.scalars().all())


async def get_mission_progress(
    session: AsyncSession,
    user_id: int,
    city_id: int,
    mission_id: int,
) -> Optional[MissionProgress]:

    result = await session.execute(
        select(MissionProgress).where(
            MissionProgress.user_id == user_id,
            MissionProgress.city_id == city_id,
            MissionProgress.mission_id == mission_id,
        )
    )

    return result.scalar_one_or_none()


async def update_mission_progress(
    session: AsyncSession,
    user_id: int,
    city_id: int,
    goal_type: str,
    increment: int = 1,
) -> list[dict[str, Any]]:
    """
    پیشرفت مأموریت‌های مرتبط را به‌روز می‌کند.
    مأموریت‌های تکمیل‌شده را برمی‌گرداند.
    """

    completed = []

    result = await session.execute(
        select(MissionProgress, Mission)
        .join(Mission, Mission.id == MissionProgress.mission_id)
        .where(
            MissionProgress.user_id == user_id,
            MissionProgress.city_id == city_id,
            MissionProgress.status == MissionStatus.IN_PROGRESS.value,
            Mission.goal_type == goal_type,
        )
    )

    rows = result.all()

    for progress, mission in rows:

        progress.current_value += increment

        if progress.current_value >= mission.goal_value:
            progress.status = MissionStatus.COMPLETED.value
            progress.completed_at = utcnow()
            completed.append({
                "mission": mission,
                "progress": progress,
            })

    if rows:
        await session.flush()

    return completed


# ================================================================
# چرخه عمر
# ================================================================

async def close_database() -> None:
    await engine.dispose()


async def close_redis() -> None:
    await redis_client.aclose()


async def shutdown() -> None:
    await close_redis()
    await close_database()


# ================================================================
# صادرات
# ================================================================

__all__ = [

    # هسته
    "Base",
    "engine",
    "AsyncSessionLocal",
    "get_session",
    "transaction",

    # راه‌اندازی
    "init_database",

    # چرخه عمر
    "close_database",
    "close_redis",
    "shutdown",

    # سلامت‌سنجی
    "database_health",
    "redis_health",

    # Redis
    "redis_client",
    "RedisKeys",
    "set_game_session",
    "get_game_session",
    "clear_game_session",
    "set_intent_context",
    "get_intent_context",
    "clear_intent_context",
    "set_cooldown",
    "is_on_cooldown",
    "cooldown_ttl",
    "check_rate_limit",
    "increment_daily_counter",
    "get_daily_counter",
    "reset_daily_counter",
    "set_income_boost",
    "has_income_boost",
    "set_risk_shield",
    "consume_risk_shield",
    "get_streak",
    "update_streak",
    "increment_event_progress",
    "get_event_progress",
    "set_event_participant",
    "get_event_contribution",
    "is_event_participant",
    "add_contest_score",
    "get_contest_leaderboard",
    "set_transfer_code",
    "get_transfer_code",
    "delete_transfer_code",
    "acquire_lock",
    "release_lock",
    "distributed_lock",

    # مدل‌ها
    "User",
    "UserStats",
    "City",
    "CityMember",
    "UserWallet",
    "UserMine",
    "CityEvent",
    "EventParticipant",
    "Mission",
    "MissionProgress",
    "Guild",
    "GuildMember",
    "CityHistory",
    "Transaction",
    "UserSubscription",

    # اِنام‌ها
    "CityMemberRole",
    "GuildMemberRole",
    "MissionStatus",
    "MissionType",
    "EventType",
    "EventStatus",
    "MineLevel",
    "JobType",
    "TransactionType",
    "SubscriptionType",

    # خطاها
    "InsufficientFundsError",
    "InsufficientEnergyError",
    "InsufficientDiamondsError",

    # کوئری: کاربر
    "get_user",
    "get_or_create_user",
    "get_user_stats",
    "add_xp_and_check_level",
    "add_diamonds",
    "spend_diamonds",

    # کوئری: شهر
    "get_city_by_chat",
    "get_or_restore_city",
    "deactivate_city",
    "add_bricks_to_city",
    "get_city_population",

    # کوئری: عضویت
    "get_city_member",
    "get_or_create_city_member",
    "restore_energy_for_city",

    # کوئری: کیف پول
    "get_wallet",
    "apply_wallet_delta",
    "transfer_eco_between_cities",

    # کوئری: معدن
    "get_or_create_mine",
    "calculate_mine_production",
    "collect_mine",

    # کوئری: رویداد
    "get_active_event",
    "create_city_event",
    "add_event_participation",

    # کوئری: رتبه‌بندی
    "get_city_leaderboard",

    # کوئری: تاریخچه
    "add_city_history",
    "get_city_history",

    # کوئری: مأموریت
    "get_active_missions",
    "get_mission_progress",
    "update_mission_progress",
]
