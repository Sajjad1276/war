# ================================================================
# اِکو — game.py
# موتور کامل بازی
# ================================================================
#
# بنویس. بساز. حکومت کن.
#
# مسئولیت این فایل:
#   - پردازش تمام پیام‌های بازی
#   - منطق کار، اکتشاف، مأموریت
#   - سیستم رویداد جمعی
#   - سیستم معدن
#   - سیستم گیلد
#   - سیستم بازار
#   - آموزش تعاملی
#   - پردازش پیام‌های گروه (اِکو خودکار)
#
# این فایل شامل موارد زیر نیست:
#   - هندلر تلگرام
#   - ارسال پیام
#   - رابط کاربری
#   - دکمه
# ================================================================

from __future__ import annotations

import random
import re
import time
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from config import settings, GameConstants
from database import (
    # سِشن
    get_session,
    distributed_lock,

    # Redis
    set_game_session,
    get_game_session,
    clear_game_session,
    set_intent_context,
    get_intent_context,
    clear_intent_context,
    set_cooldown,
    is_on_cooldown,
    cooldown_ttl,
    check_rate_limit,
    increment_daily_counter,
    get_daily_counter,
    set_income_boost,
    has_income_boost,
    set_risk_shield,
    consume_risk_shield,
    get_streak,
    update_streak,
    increment_event_progress,
    get_event_progress,
    set_event_participant,
    get_event_contribution,
    is_event_participant,
    add_contest_score,
    get_contest_leaderboard,
    RedisKeys,

    # مدل‌ها
    User,
    UserStats,
    City,
    CityMember,
    UserWallet,
    UserMine,
    CityEvent,
    Mission,
    MissionProgress,
    Guild,
    GuildMember,

    # اِنام‌ها
    CityMemberRole,
    GuildMemberRole,
    MissionStatus,
    MissionType,
    EventStatus,
    EventType,
    MineLevel,
    JobType,

    # خطاها
    InsufficientFundsError,
    InsufficientEnergyError,
    InsufficientDiamondsError,

    # کوئری‌ها
    get_user,
    get_or_create_user,
    get_user_stats,
    add_xp_and_check_level,
    add_diamonds,
    spend_diamonds,
    get_city_by_chat,
    get_or_restore_city,
    add_bricks_to_city,
    get_city_population,
    get_city_member,
    get_or_create_city_member,
    get_wallet,
    apply_wallet_delta,
    transfer_eco_between_cities,
    get_or_create_mine,
    calculate_mine_production,
    collect_mine,
    get_active_event,
    create_city_event,
    add_event_participation,
    get_city_leaderboard,
    add_city_history,
    get_city_history,
    get_active_missions,
    get_mission_progress,
    update_mission_progress,
)


# ================================================================
# لاگر
# ================================================================

import logging
logger = logging.getLogger("echo.game")


# ================================================================
# ابزار زمان
# ================================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ================================================================
# ۱. اِنام‌های بازی
# ================================================================

class IntentType(str, Enum):
    # دستورات اصلی
    START       = "START"
    HELP        = "HELP"
    PROFILE     = "PROFILE"
    CITY        = "CITY"
    WORK        = "WORK"
    EXPLORE     = "EXPLORE"
    MISSIONS    = "MISSIONS"
    MINE        = "MINE"
    MARKET      = "MARKET"
    GUILD       = "GUILD"
    RANK        = "RANK"
    HISTORY     = "HISTORY"
    TRANSFER    = "TRANSFER"
    DEPOSIT     = "DEPOSIT"
    WITHDRAW    = "WITHDRAW"
    SHOP        = "SHOP"
    TUTORIAL    = "TUTORIAL"
    CITIES      = "CITIES"

    # رویداد جمعی
    PARTICIPATE = "PARTICIPATE"
    DEFEND      = "DEFEND"
    HELP_CITY   = "HELP_CITY"

    # جریان گفتگو
    CONFIRM     = "CONFIRM"
    CANCEL      = "CANCEL"
    NUMERIC     = "NUMERIC"
    NO_INTENT   = "NO_INTENT"


class SessionState(str, Enum):
    IDLE                    = "IDLE"
    WAITING_CHOICE          = "WAITING_CHOICE"
    WAITING_CONFIRM         = "WAITING_CONFIRM"
    WAITING_AMOUNT          = "WAITING_AMOUNT"
    WAITING_TRANSFER_TARGET = "WAITING_TRANSFER_TARGET"
    WAITING_TRANSFER_AMOUNT = "WAITING_TRANSFER_AMOUNT"
    WAITING_CITY_SELECT     = "WAITING_CITY_SELECT"
    TUTORIAL_ACTIVE         = "TUTORIAL_ACTIVE"


class ResponseType(str, Enum):
    PERSONAL        = "PERSONAL"
    PUBLIC          = "PUBLIC"
    PUBLIC_EVENT    = "PUBLIC_EVENT"
    PUBLIC_ANNOUNCE = "PUBLIC_ANNOUNCE"
    ERROR           = "ERROR"
    SILENT          = "SILENT"


class ActionStyle(str, Enum):
    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER  = "danger"


class GameError(str, Enum):
    INVALID_ACTION      = "INVALID_ACTION"
    SESSION_EXPIRED     = "SESSION_EXPIRED"
    NOT_MEMBER          = "NOT_MEMBER"
    INSUFFICIENT_ENERGY = "INSUFFICIENT_ENERGY"
    INSUFFICIENT_FUNDS  = "INSUFFICIENT_FUNDS"
    INSUFFICIENT_DIAMONDS = "INSUFFICIENT_DIAMONDS"
    COOLDOWN            = "COOLDOWN"
    RATE_LIMITED        = "RATE_LIMITED"
    UNKNOWN_INTENT      = "UNKNOWN_INTENT"
    INVALID_INPUT       = "INVALID_INPUT"
    FEATURE_NOT_READY   = "FEATURE_NOT_READY"
    CITY_NOT_FOUND      = "CITY_NOT_FOUND"
    USER_NOT_FOUND      = "USER_NOT_FOUND"
    LEVEL_TOO_LOW       = "LEVEL_TOO_LOW"
    NO_MINE             = "NO_MINE"
    NO_EVENT            = "NO_EVENT"
    ALREADY_PARTICIPANT = "ALREADY_PARTICIPANT"
    EVENT_ENDED         = "EVENT_ENDED"
    DAILY_LIMIT         = "DAILY_LIMIT"
    BANNED              = "BANNED"


# ================================================================
# ۲. قراردادهای داده
# ================================================================

@dataclass
class GameContext:
    """ورودی مستقل از تلگرام."""

    user_id:    int
    city_id:    int
    chat_id:    int
    message_id: int
    text:       str

    is_group:   bool = True
    is_private: bool = False
    username:   str  = ""
    display_name: str = ""

    reply_to_message_id: Optional[int] = None
    session_id:          Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    normalized_text: str = ""
    raw_text:        str = ""

    def __post_init__(self) -> None:
        if not self.raw_text:
            self.raw_text = self.text
        if not self.normalized_text:
            self.normalized_text = normalize_text(self.text)


@dataclass
class ActionButton:
    """متادیتای دکمه — handlers.py دکمه واقعی می‌سازد."""

    action:   str
    label:    str
    style:    ActionStyle         = ActionStyle.PRIMARY
    payload:  dict[str, Any]      = field(default_factory=dict)


@dataclass
class GameResponse:
    """خروجی مستقل از تلگرام."""

    text:          str          = ""
    response_type: ResponseType = ResponseType.PERSONAL
    public:        bool         = False
    edit_preferred: bool        = False
    session_id:    Optional[str] = None
    state:         SessionState  = SessionState.IDLE
    actions:       list[ActionButton] = field(default_factory=list)
    requires_ui:   bool          = False
    metadata:      dict[str, Any] = field(default_factory=dict)
    error:         Optional[GameError] = None
    notification:  Optional[str]  = None

    # اعلامیه عمومی در گروه (جدا از پاسخ شخصی)
    public_announcement: Optional[str] = None

    @property
    def is_silent(self) -> bool:
        return self.response_type == ResponseType.SILENT


# ================================================================
# ۳. نرمال‌سازی متن فارسی
# ================================================================

_CHAR_MAP = {
    "ي": "ی", "ى": "ی", "ك": "ک",
    "\u200c": " ", "\u200b": "",
    "\u200f": "", "\u200e": "",
}

_MULTI_SPACE         = re.compile(r"\s+")
_TRAILING_PUNCTUATION = re.compile(r"[!؟?.,،؛;:]+$")
_NUMERIC_RE          = re.compile(r"^[۰-۹0-9]+$")
_AMOUNT_RE           = re.compile(r"^[۰-۹0-9,،]+$")


def normalize_text(text: str) -> str:

    if not text:
        return ""

    value = text.strip().lower()

    for source, target in _CHAR_MAP.items():
        value = value.replace(source, target)

    value = _TRAILING_PUNCTUATION.sub("", value)
    value = _MULTI_SPACE.sub(" ", value)

    return value.strip()


def normalize_digits(text: str) -> str:

    mapping = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    return text.translate(mapping)


def parse_amount(text: str) -> Optional[int]:
    """
    عدد را از متن فارسی یا انگلیسی استخراج می‌کند.
    کاماها را نادیده می‌گیرد.
    """

    cleaned = normalize_digits(text).replace(",", "").replace("،", "")

    try:
        value = int(cleaned)
        return value if value > 0 else None
    except ValueError:
        return None


# ================================================================
# ۴. فهرست نیت‌ها
# ================================================================

INTENT_ALIASES: dict[IntentType, tuple[str, ...]] = {

    IntentType.START: (
        "/start", "start", "شروع",
    ),

    IntentType.HELP: (
        "/help", "help", "راهنما", "کمک",
        "چطور بازی کنم", "چطور شروع کنم",
    ),

    IntentType.PROFILE: (
        "پروفایل", "وضعیت من", "اطلاعات من",
        "من کی هستم", "مشخصاتم", "profile",
    ),

    IntentType.CITY: (
        "شهر", "شهر ما", "شهرمون",
        "وضعیت شهر", "اوضاع شهر", "city",
    ),

    IntentType.WORK: (
        "کار", "کار کن", "کار کردن",
        "کار امروز", "work",
    ),

    IntentType.EXPLORE: (
        "اکتشاف", "کاوش", "جستجو",
        "بگرد", "منطقه جدید", "explore",
    ),

    IntentType.MISSIONS: (
        "مأموریت", "ماموریت",
        "مأموریت‌ها", "ماموریت ها",
        "مأموریت هام", "وظایف", "missions",
    ),

    IntentType.MINE: (
        "معدن", "معدنم", "برداشت",
        "تولید معدن", "mine",
    ),

    IntentType.MARKET: (
        "بازار", "بازار امروز",
        "خرید و فروش", "market",
    ),

    IntentType.GUILD: (
        "گیلد", "دسته", "تیم",
        "گروه بازی", "guild",
    ),

    IntentType.RANK: (
        "رتبه", "رتبه‌بندی", "رتبه بندی",
        "نفرات برتر", "برترین‌ها", "rank",
    ),

    IntentType.HISTORY: (
        "تاریخ شهر", "تاریخچه",
        "اتفاقات شهر", "history",
    ),

    IntentType.TRANSFER: (
        "انتقال", "انتقال اکو",
        "فرستادن اکو", "transfer",
    ),

    IntentType.DEPOSIT: (
        "واریز", "واریز به بانک",
        "پس انداز", "deposit",
    ),

    IntentType.WITHDRAW: (
        "برداشت از بانک", "برداشت بانک",
        "withdraw",
    ),

    IntentType.SHOP: (
        "فروشگاه", "خرید الماس",
        "پریمیوم", "shop", "store",
    ),

    IntentType.CITIES: (
        "شهرهام", "شهرهای من",
        "لیست شهرها", "cities",
    ),

    IntentType.PARTICIPATE: (
        "شرکت", "شرکت می‌کنم",
        "میام", "هستم", "participate",
    ),

    IntentType.DEFEND: (
        "دفاع", "دفاع می‌کنم",
        "محافظت", "defend",
    ),

    IntentType.HELP_CITY: (
        "کمک", "کمک می‌کنم",
        "واریز به شهر", "help",
    ),

    IntentType.CONFIRM: (
        "بله", "بلی", "آره", "باشه",
        "تأیید", "تایید", "اوکی",
        "ok", "yes", "✓",
    ),

    IntentType.CANCEL: (
        "نه", "خیر", "لغو",
        "انصراف", "بی خیال",
        "بی‌خیال", "no", "cancel",
    ),
}

_ALIAS_MAP: dict[str, IntentType] = {}

for _intent, _aliases in INTENT_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_MAP[normalize_text(_alias)] = _intent


def detect_intent(normalized: str) -> IntentType:

    normalized = normalize_text(normalized)

    exact = _ALIAS_MAP.get(normalized)
    if exact is not None:
        return exact

    if _NUMERIC_RE.fullmatch(normalized):
        return IntentType.NUMERIC

    return IntentType.NO_INTENT


# ================================================================
# ۵. قوانین دسترسی
# ================================================================

@dataclass(frozen=True)
class AccessRule:
    allow_private:   bool
    allow_group:     bool
    requires_member: bool


ACCESS_RULES: dict[IntentType, AccessRule] = {

    IntentType.START:       AccessRule(True,  True,  False),
    IntentType.HELP:        AccessRule(True,  True,  False),
    IntentType.PROFILE:     AccessRule(True,  True,  False),
    IntentType.TUTORIAL:    AccessRule(True,  True,  False),
    IntentType.SHOP:        AccessRule(True,  True,  False),
    IntentType.CITIES:      AccessRule(True,  True,  False),

    IntentType.CITY:        AccessRule(False, True,  True),
    IntentType.WORK:        AccessRule(True,  True,  True),
    IntentType.EXPLORE:     AccessRule(True,  True,  True),
    IntentType.MISSIONS:    AccessRule(True,  True,  True),
    IntentType.MINE:        AccessRule(True,  True,  True),
    IntentType.MARKET:      AccessRule(True,  True,  True),
    IntentType.GUILD:       AccessRule(True,  True,  True),
    IntentType.RANK:        AccessRule(False, True,  True),
    IntentType.HISTORY:     AccessRule(False, True,  True),
    IntentType.TRANSFER:    AccessRule(True,  True,  True),
    IntentType.DEPOSIT:     AccessRule(True,  True,  True),
    IntentType.WITHDRAW:    AccessRule(True,  True,  True),

    IntentType.PARTICIPATE: AccessRule(False, True,  True),
    IntentType.DEFEND:      AccessRule(False, True,  True),
    IntentType.HELP_CITY:   AccessRule(False, True,  True),
}


def check_access(
    intent: IntentType,
    context: GameContext,
) -> Optional[GameError]:

    rule = ACCESS_RULES.get(intent)

    if rule is None:
        return None

    if context.is_private and not rule.allow_private:
        return GameError.INVALID_ACTION

    if context.is_group and not rule.allow_group:
        return GameError.INVALID_ACTION

    return None


# ================================================================
# ۶. پیام‌های خطا
# ================================================================

_ERROR_TEXTS = {
    GameError.INVALID_ACTION:
        "⚠️ این کار در اینجا امکان‌پذیر نیست.",
    GameError.SESSION_EXPIRED:
        "⏱ این مرحله منقضی شده. دوباره شروع کن.",
    GameError.NOT_MEMBER:
        "🏙 هنوز شهروند این شهر نیستی.\nاولین پیامت رو بفرست تا ثبت بشی.",
    GameError.INSUFFICIENT_ENERGY:
        "⚡ انرژی کافی نداری.\nهر ۶ ساعت ۲۵ واحد انرژی شارژ می‌شه.",
    GameError.INSUFFICIENT_FUNDS:
        "💸 موجودی کافی نداری.",
    GameError.INSUFFICIENT_DIAMONDS:
        "💎 الماس کافی نداری.",
    GameError.COOLDOWN:
        "⏳ هنوز زوده. کمی صبر کن.",
    GameError.RATE_LIMITED:
        "🐢 آروم‌تر! کمی صبر کن و دوباره امتحان کن.",
    GameError.UNKNOWN_INTENT:
        "🤔 متوجه نشدم. «راهنما» بنویس.",
    GameError.INVALID_INPUT:
        "❌ ورودی درست نیست.",
    GameError.FEATURE_NOT_READY:
        "🔧 این بخش هنوز در حال توسعه است.",
    GameError.CITY_NOT_FOUND:
        "🏙 شهر پیدا نشد.",
    GameError.USER_NOT_FOUND:
        "👤 حساب کاربری پیدا نشد.",
    GameError.LEVEL_TOO_LOW:
        "📈 سطحت برای این کار کافی نیست.",
    GameError.NO_MINE:
        "⛏ معدن نداری. از فروشگاه یه معدن بخر.",
    GameError.NO_EVENT:
        "📭 الان رویداد فعالی در شهر نیست.",
    GameError.ALREADY_PARTICIPANT:
        "✅ قبلاً در این رویداد شرکت کردی.",
    GameError.EVENT_ENDED:
        "⌛ این رویداد تموم شده.",
    GameError.DAILY_LIMIT:
        "📅 به حد روزانه رسیدی. فردا دوباره امتحان کن.",
    GameError.BANNED:
        "🚫 حساب کاربری تو مسدود شده.",
}


def error_response(
    error: GameError,
    state: SessionState = SessionState.IDLE,
    session_id: Optional[str] = None,
) -> GameResponse:

    return GameResponse(
        text=_ERROR_TEXTS.get(error, "⚠️ یه مشکل پیش اومد."),
        response_type=ResponseType.ERROR,
        state=state,
        session_id=session_id,
        error=error,
    )


# ================================================================
# ۷. کمک‌کننده‌های دیتابیس
# ================================================================

async def get_full_user_data(
    user_id: int,
    city_id: int,
) -> Optional[tuple[User, UserStats, City, CityMember, UserWallet]]:

    async with get_session() as session:

        user_res = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_res.scalar_one_or_none()
        if not user:
            return None

        stats_res = await session.execute(
            select(UserStats).where(UserStats.user_id == user_id)
        )
        stats = stats_res.scalar_one_or_none()
        if not stats:
            return None

        city_res = await session.execute(
            select(City).where(City.id == city_id)
        )
        city = city_res.scalar_one_or_none()
        if not city:
            return None

        member_res = await session.execute(
            select(CityMember).where(
                CityMember.city_id == city_id,
                CityMember.user_id == user_id,
                CityMember.is_active.is_(True),
            )
        )
        member = member_res.scalar_one_or_none()
        if not member:
            return None

        wallet_res = await session.execute(
            select(UserWallet).where(
                UserWallet.user_id == user_id,
                UserWallet.city_id == city_id,
            )
        )
        wallet = wallet_res.scalar_one_or_none()
        if not wallet:
            return None

        return user, stats, city, member, wallet


async def is_city_member(user_id: int, city_id: int) -> bool:

    async with get_session() as session:
        member = await get_city_member(session, city_id, user_id)
        return bool(member and member.is_active)


# ================================================================
# ۸. سِشن بازی
# ================================================================

async def get_active_session(
    user_id: int,
    city_id: int,
) -> Optional[dict[str, Any]]:

    return await get_game_session(user_id, city_id)


async def save_session(
    user_id: int,
    city_id: int,
    state: SessionState,
    payload: Optional[dict[str, Any]] = None,
    ttl: int = 600,
) -> str:

    current = await get_active_session(user_id, city_id)
    session_id = str(uuid.uuid4())

    merged = {}

    if current:
        session_id = current.get("session_id", session_id)
        merged.update(current.get("payload", {}))

    if payload:
        merged.update(payload)

    merged["session_id"] = session_id

    await set_game_session(
        user_id, city_id,
        state.value,
        payload=merged,
        ttl_seconds=ttl,
    )

    return session_id


async def clear_session(user_id: int, city_id: int) -> None:

    await clear_game_session(user_id, city_id)
    await clear_intent_context(user_id, city_id)


# ================================================================
# ۹. ثبت‌کننده اکشن‌ها
# ================================================================

ActionHandler = Callable[
    [GameContext, Optional[dict[str, Any]]],
    Awaitable[GameResponse],
]

_ACTIONS: dict[IntentType, ActionHandler] = {}


def register_action(intent: IntentType):
    def decorator(fn: ActionHandler) -> ActionHandler:
        _ACTIONS[intent] = fn
        return fn
    return decorator


# ================================================================
# ۱۰. شروع و راهنما
# ================================================================

@register_action(IntentType.START)
async def handle_start(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    return GameResponse(
        text=(
            "〰️ <b>اِکو</b>\n\n"
            "بنویس. بساز. حکومت کن.\n\n"
            "اِکو یه بازی دسته‌جمعی متنیه.\n"
            "هر گروه یه شهره.\n"
            "هر پیام یه آجر.\n"
            "با هم یه شهر می‌سازیم.\n\n"
            "برای شروع آموزش بنویس: <b>آموزش</b>\n"
            "یا مستقیم بنویس: <b>کار</b>"
        ),
        response_type=ResponseType.PERSONAL,
    )


@register_action(IntentType.HELP)
async def handle_help(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    return GameResponse(
        text=(
            "📖 <b>راهنمای اِکو</b>\n\n"

            "━━━ <b>دستورات اصلی</b> ━━━\n\n"

            "💼 <b>کار</b>\n"
            "درآمد کسب کن — انرژی خرج کن\n\n"

            "🧭 <b>اکتشاف</b>\n"
            "ماجراجویی کن — نتیجه‌ش غیرقابل پیش‌بینیه\n\n"

            "🎯 <b>مأموریت</b>\n"
            "هدف روزانه داشته باش — جایزه بگیر\n\n"

            "⛏ <b>معدن</b>\n"
            "تولید خودکار اِکو — هر ساعت\n\n"

            "🏙 <b>شهر</b>\n"
            "وضعیت شهرت رو ببین\n\n"

            "👤 <b>پروفایل</b>\n"
            "آمار کاملت رو ببین\n\n"

            "🏆 <b>رتبه</b>\n"
            "جایگاهت رو در شهر ببین\n\n"

            "📜 <b>تاریخ شهر</b>\n"
            "رویدادهای مهم شهر\n\n"

            "💰 <b>واریز / برداشت بانک</b>\n"
            "مدیریت پول نقد و بانک\n\n"

            "↔️ <b>انتقال</b>\n"
            "اِکو رو به بازیکن دیگه‌ای بده\n\n"

            "━━━ <b>رویداد جمعی</b> ━━━\n\n"

            "وقتی شهر رویداد داره:\n"
            "⚔️ <b>دفاع</b> — برای رویداد حمله\n"
            "💰 <b>کمک</b> — برای رویداد بحران\n"
            "🎉 <b>شرکت</b> — برای جشن و کشف\n\n"

            "━━━━━━━━━━━━━━━\n"
            "برای آموزش کامل: <b>آموزش</b>"
        ),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۱۱. آموزش تعاملی
# ================================================================

TUTORIAL_STEPS = [
    {
        "step": 0,
        "title": "خوش اومدی به اِکو! 👋",
        "text": (
            "〰️ <b>اِکو چیه؟</b>\n\n"
            "اِکو یه بازی دسته‌جمعیه که داخل همین گروه اجرا می‌شه.\n\n"
            "هر گروه یه <b>شهر</b> مستقله.\n"
            "هر پیامی که می‌فرستی یه <b>آجر</b> به شهر اضافه می‌کنه.\n"
            "با هم شهر رو می‌سازیم و رشد می‌دیم.\n\n"
            "بریم اول یه درآمد ساده داشته باشیم؟"
        ),
        "action": "کار کن",
        "action_intent": "WORK_TUTORIAL",
    },
    {
        "step": 1,
        "title": "اولین درآمد 💼",
        "text": (
            "✅ <b>عالی بود!</b>\n\n"
            "کار کردی و درآمد داشتی.\n"
            "این ساده‌ترین روش کسب درآمد توی اِکوئه.\n\n"
            "حالا یه چیز هیجان‌انگیزتر:\n"
            "<b>اکتشاف</b> — نمی‌دونی چی پیدا می‌کنی!\n\n"
            "ممکنه گنج پیدا کنی، ممکنه نه. آماده‌ای؟"
        ),
        "action": "اکتشاف کن",
        "action_intent": "EXPLORE_TUTORIAL",
    },
    {
        "step": 2,
        "title": "اکتشاف 🧭",
        "text": (
            "〰️ <b>پروفایلت</b>\n\n"
            "الان بذار وضعیتت رو ببینی.\n"
            "هر چیزی که کسب کردی اینجا ثبت شده.\n\n"
            "سطح، تجربه، انرژی، اِکو...\n"
            "همه اینا با فعالیت بیشتر رشد می‌کنن."
        ),
        "action": "پروفایلم",
        "action_intent": "PROFILE_TUTORIAL",
    },
    {
        "step": 3,
        "title": "رویداد جمعی ⚔️",
        "text": (
            "🏆 <b>مهم‌ترین بخش اِکو</b>\n\n"
            "هر چند ساعت یه بار، ربات توی گروه یه <b>رویداد جمعی</b> اعلام می‌کنه.\n\n"
            "مثلاً:\n"
            "«شهر تحت حمله است! به ۵۰۰ واحد دفاع نیاز داریم.»\n\n"
            "همه شهروندا با هم باید کمک کنن.\n"
            "اگه شهر نجات پیدا کنه، همه جایزه می‌گیرن.\n\n"
            "دفعه بعد که رویداد اومد، «دفاع» یا «شرکت» بنویس."
        ),
        "action": "فهمیدم ✓",
        "action_intent": "DONE_TUTORIAL",
    },
]


@register_action(IntentType.TUTORIAL)
async def handle_tutorial(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    step_data = TUTORIAL_STEPS[0]

    await save_session(
        context.user_id,
        context.city_id,
        SessionState.TUTORIAL_ACTIVE,
        {"tutorial_step": 0},
        ttl=1800,
    )

    return GameResponse(
        text=step_data["text"],
        response_type=ResponseType.PERSONAL,
        state=SessionState.TUTORIAL_ACTIVE,
        actions=[
            ActionButton(
                action=f"tutorial_step_0",
                label=step_data["action"],
                style=ActionStyle.SUCCESS,
            )
        ],
        requires_ui=True,
    )


# ================================================================
# ۱۲. پروفایل
# ================================================================

@register_action(IntentType.PROFILE)
async def handle_profile(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    data = await get_full_user_data(context.user_id, context.city_id)

    if data is None:

        async with get_session() as session:
            user = await get_user(session, context.user_id)

        if user is None:
            return error_response(GameError.USER_NOT_FOUND)

        return error_response(GameError.NOT_MEMBER)

    user, stats, city, member, wallet = data

    name = f"@{user.username}" if user.username else user.display_name or str(user.id)

    role_name = GameConstants.CITY_ROLES.get(member.role, "شهروند")

    # محاسبه XP تا سطح بعد
    next_level_xp = settings.total_xp_for_level(stats.level + 1)
    current_level_xp = settings.total_xp_for_level(stats.level)
    progress_xp = stats.xp - current_level_xp
    needed_xp = next_level_xp - current_level_xp

    # نوار پیشرفت XP
    if needed_xp > 0:
        filled = int((progress_xp / needed_xp) * 10)
        xp_bar = "█" * filled + "░" * (10 - filled)
    else:
        xp_bar = "██████████"

    # اشتراک طلایی
    gold_status = ""
    if user.gold_subscription_until and user.gold_subscription_until > utcnow():
        days_left = (user.gold_subscription_until - utcnow()).days
        gold_status = f"\n✨ شهروند طلایی — {days_left} روز مانده"

    text = (
        f"👤 <b>{name}</b>{gold_status}\n\n"

        f"━━━ <b>پیشرفت جهانی</b> ━━━\n"
        f"📊 سطح: {stats.level}\n"
        f"⭐ تجربه: {stats.xp:,}\n"
        f"[{xp_bar}] {progress_xp:,}/{needed_xp:,}\n"
        f"🏅 شهرت: {stats.fame:,}\n\n"

        f"━━━ <b>در {city.name}</b> ━━━\n"
        f"👑 نقش: {role_name}\n"
        f"⚡ انرژی: {member.energy}/{settings.max_energy}\n"
        f"⭐ اعتبار: {member.city_reputation:,}\n"
        f"🧱 آجر: {member.bricks_contributed:,}\n\n"

        f"━━━ <b>کیف پول</b> ━━━\n"
        f"💵 نقد: ◈ {wallet.cash:,}\n"
        f"🏦 بانک: ◈ {wallet.bank:,}\n"
        f"💎 الماس: {user.diamonds:,}\n\n"

        f"━━━ <b>آمار کلی</b> ━━━\n"
        f"💼 کارها: {stats.total_works:,}\n"
        f"🧭 اکتشاف‌ها: {stats.total_explores:,}\n"
        f"🎯 مأموریت‌های تموم‌شده: {stats.total_missions_completed:,}\n"
        f"🔥 استریک: {stats.current_streak} روز"
    )

    return GameResponse(
        text=text,
        response_type=ResponseType.PERSONAL,
        metadata={
            "user_id": user.id,
            "city_id": city.id,
            "level": stats.level,
            "energy": member.energy,
        },
    )


# ================================================================
# ۱۳. وضعیت شهر
# ================================================================

@register_action(IntentType.CITY)
async def handle_city(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    async with get_session() as session:

        city_res = await session.execute(
            select(City).where(City.id == context.city_id)
        )
        city = city_res.scalar_one_or_none()

        if city is None:
            return error_response(GameError.CITY_NOT_FOUND)

        population = await get_city_population(session, city.id)

        # رویداد فعال
        event = await get_active_event(session, city.id)

    # محاسبه پیشرفت سطح شهر
    next_level_bricks = settings.city_bricks_for_level(city.level + 1)
    current_level_bricks = settings.city_bricks_for_level(city.level)
    progress_bricks = city.total_bricks - current_level_bricks
    needed_bricks = next_level_bricks - current_level_bricks

    if needed_bricks > 0:
        filled = int((progress_bricks / needed_bricks) * 10)
        brick_bar = "█" * min(filled, 10) + "░" * max(0, 10 - filled)
    else:
        brick_bar = "██████████"

    activity = (
        "🔴 کم" if population < 10
        else "🟡 متوسط" if population < 30
        else "🟢 زیاد"
    )

    event_text = ""
    if event:
        progress_pct = int((event.current_value / max(event.target_value, 1)) * 100)
        event_text = (
            f"\n⚡ <b>رویداد فعال: {event.title}</b>\n"
            f"پیشرفت: {progress_pct}٪ "
            f"({event.current_value:,}/{event.target_value:,})"
        )

    text = (
        f"🏙 <b>{city.name}</b>\n\n"

        f"━━━ <b>وضعیت کلی</b> ━━━\n"
        f"⭐ سطح: {city.level}\n"
        f"👥 جمعیت: {population:,}\n"
        f"💰 خزانه: ◈ {city.treasury:,}\n"
        f"📊 فعالیت: {activity}\n\n"

        f"━━━ <b>پیشرفت شهر</b> ━━━\n"
        f"🧱 آجر کل: {city.total_bricks:,}\n"
        f"[{brick_bar}] {progress_bricks:,}/{needed_bricks:,}\n"
        f"🎯 تا سطح {city.level + 1}: "
        f"{max(0, needed_bricks - progress_bricks):,} آجر"
        f"{event_text}\n\n"

        f"🏷 کد شهر: <code>{city.city_code or '-'}</code>"
    )

    return GameResponse(
        text=text,
        response_type=ResponseType.PERSONAL,
        metadata={"city_id": city.id, "population": population},
    )


# ================================================================
# ۱۴. کار
# ================================================================

JOB_CONFIG = {
    JobType.LABORER.value: {
        "name": "کارگر ساده",
        "icon": "🔨",
        "min": settings.work_laborer_min,
        "max": settings.work_laborer_max,
        "energy": settings.work_laborer_energy,
        "xp": settings.work_laborer_xp,
        "min_level": settings.work_laborer_min_level,
        "fail_chance": settings.work_laborer_fail_chance,
        "penalty_min": 0,
        "penalty_max": 0,
    },
    JobType.TRADER.value: {
        "name": "تاجر",
        "icon": "📦",
        "min": settings.work_trader_min,
        "max": settings.work_trader_max,
        "energy": settings.work_trader_energy,
        "xp": settings.work_trader_xp,
        "min_level": settings.work_trader_min_level,
        "fail_chance": settings.work_trader_fail_chance,
        "penalty_min": 0,
        "penalty_max": 0,
    },
    JobType.DETECTIVE.value: {
        "name": "کارآگاه",
        "icon": "🔍",
        "min": settings.work_detective_min,
        "max": settings.work_detective_max,
        "energy": settings.work_detective_energy,
        "xp": settings.work_detective_xp,
        "min_level": settings.work_detective_min_level,
        "fail_chance": settings.work_detective_fail_chance,
        "penalty_min": 0,
        "penalty_max": 0,
    },
    JobType.HACKER.value: {
        "name": "هکر",
        "icon": "💻",
        "min": settings.work_hacker_min,
        "max": settings.work_hacker_max,
        "energy": settings.work_hacker_energy,
        "xp": settings.work_hacker_xp,
        "min_level": settings.work_hacker_min_level,
        "fail_chance": settings.work_hacker_fail_chance,
        "penalty_min": settings.work_hacker_penalty_min,
        "penalty_max": settings.work_hacker_penalty_max,
    },
}


@register_action(IntentType.WORK)
async def handle_work(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    # کولداون
    if await is_on_cooldown(context.user_id, context.city_id, "work"):
        ttl = await cooldown_ttl(context.user_id, context.city_id, "work")
        minutes = ttl // 60
        seconds = ttl % 60
        return GameResponse(
            text=(
                f"⏳ <b>کولداون کار</b>\n\n"
                f"باید {minutes} دقیقه و {seconds} ثانیه صبر کنی."
            ),
            response_type=ResponseType.PERSONAL,
            error=GameError.COOLDOWN,
        )

    # بررسی حد روزانه
    daily_key = RedisKeys.daily_work(context.user_id, context.city_id)
    allowed, current_count = await increment_daily_counter(
        daily_key,
        settings.work_max_daily,
    )

    if not allowed:
        return error_response(GameError.DAILY_LIMIT)

    async with distributed_lock(
        f"work:{context.user_id}:{context.city_id}",
        ttl_seconds=10,
        wait_seconds=3,
    ) as acquired:

        if not acquired:
            return error_response(GameError.COOLDOWN)

        async with get_session() as session:

            # اطلاعات کاربر
            member_res = await session.execute(
                select(CityMember).where(
                    CityMember.city_id == context.city_id,
                    CityMember.user_id == context.user_id,
                    CityMember.is_active.is_(True),
                )
            )
            member = member_res.scalar_one_or_none()

            if not member:
                return error_response(GameError.NOT_MEMBER)

            stats_res = await session.execute(
                select(UserStats).where(UserStats.user_id == context.user_id)
            )
            stats = stats_res.scalar_one_or_none()

            job_key = member.current_job
            job = JOB_CONFIG.get(job_key, JOB_CONFIG[JobType.LABORER.value])

            # بررسی سطح
            if stats and stats.level < job["min_level"]:
                job_key = JobType.LABORER.value
                job = JOB_CONFIG[job_key]

            # بررسی انرژی
            if member.energy < job["energy"]:
                return error_response(GameError.INSUFFICIENT_ENERGY)

            # محاسبه نتیجه
            failed = random.randint(1, 100) <= job["fail_chance"]

            if failed and job.get("penalty_max", 0) > 0:

                penalty = random.randint(
                    job["penalty_min"],
                    job["penalty_max"],
                )

                member.energy -= job["energy"]
                member.last_active_at = utcnow()

                await apply_wallet_delta(
                    session,
                    context.user_id,
                    context.city_id,
                    cash_delta=-penalty,
                    allow_negative=False,
                )

                await session.flush()

                text = (
                    f"💻 <b>هک شکست خورد!</b>\n\n"
                    f"عملیات لو رفت.\n"
                    f"◈ {penalty:,} جریمه شدی.\n"
                    f"⚡ {job['energy']} انرژی مصرف شد."
                )

            elif failed:

                member.energy -= job["energy"]
                member.last_active_at = utcnow()
                await session.flush()

                text = (
                    f"{job['icon']} <b>این دفعه نشد</b>\n\n"
                    f"مأموریت {job['name']} شکست خورد.\n"
                    f"⚡ {job['energy']} انرژی مصرف شد.\n"
                    f"دفعه بعد موفق‌تری!"
                )

            else:

                # درآمد
                income = random.randint(job["min"], job["max"])

                # بونوس اشتراک طلایی
                user_res = await session.execute(
                    select(User).where(User.id == context.user_id)
                )
                user = user_res.scalar_one_or_none()

                if (
                    user
                    and user.gold_subscription_until
                    and user.gold_subscription_until > utcnow()
                ):
                    income = int(income * (1 + settings.gold_subscription_income_bonus / 100))

                # بونوس بوست درآمد
                if await has_income_boost(context.user_id):
                    income = int(income * 2)

                member.energy -= job["energy"]
                member.last_active_at = utcnow()
                stats.total_works += 1

                await apply_wallet_delta(
                    session,
                    context.user_id,
                    context.city_id,
                    cash_delta=income,
                )

                # آجر به شهر
                bricks = max(1, income // 1000)
                await add_bricks_to_city(
                    session,
                    context.city_id,
                    context.user_id,
                    bricks,
                )

                await session.flush()

                # XP
                xp_result = await add_xp_and_check_level(
                    session,
                    context.user_id,
                    job["xp"],
                )

                # پیشرفت مأموریت
                completed_missions = await update_mission_progress(
                    session,
                    context.user_id,
                    context.city_id,
                    "work_count",
                    increment=1,
                )

                await update_mission_progress(
                    session,
                    context.user_id,
                    context.city_id,
                    "eco_amount",
                    increment=income,
                )

                # پیشرفت رقابت (اگه رویداد فعال بود)
                event = await get_active_event(session, context.city_id)
                if event and event.event_type == EventType.CONTEST.value:
                    await add_contest_score(event.id, context.user_id, job["xp"])

                level_up_text = ""
                if xp_result.get("leveled_up"):
                    level_up_text = (
                        f"\n\n🎉 <b>لول‌آپ!</b> "
                        f"به سطح {xp_result['new_level']} رسیدی!"
                    )

                mission_text = ""
                if completed_missions:
                    names = [m["mission"].title for m in completed_missions]
                    mission_text = (
                        f"\n\n✅ <b>مأموریت تکمیل شد:</b>\n"
                        + "\n".join(f"• {n}" for n in names)
                    )

                text = (
                    f"{job['icon']} <b>{job['name']}</b>\n\n"
                    f"◈ {income:,} اکو به دست آوردی.\n"
                    f"⚡ {job['energy']} انرژی مصرف شد.\n"
                    f"⭐ {job['xp']} XP کسب کردی.\n"
                    f"🧱 {bricks} آجر به شهر اضافه شد."
                    f"{level_up_text}"
                    f"{mission_text}"
                )

    # کولداون
    await set_cooldown(
        context.user_id,
        context.city_id,
        "work",
        settings.work_cooldown_seconds,
    )

    return GameResponse(
        text=text,
        response_type=ResponseType.PERSONAL,
        metadata={"job": job_key},
    )


# ================================================================
# ۱۵. انتخاب شغل
# ================================================================

async def handle_job_select(
    context: GameContext,
    session_payload: dict[str, Any],
) -> GameResponse:

    choice_str = normalize_digits(context.normalized_text)

    if not choice_str.isdigit():
        return GameResponse(
            text="شماره شغل رو بفرست (مثلاً ۱):",
            response_type=ResponseType.PERSONAL,
            state=SessionState.WAITING_CHOICE,
        )

    choice = int(choice_str)
    jobs_list = [
        JobType.LABORER.value,
        JobType.TRADER.value,
        JobType.DETECTIVE.value,
        JobType.HACKER.value,
    ]

    if choice < 1 or choice > len(jobs_list):
        return GameResponse(
            text=f"عدد بین ۱ تا {len(jobs_list)} وارد کن.",
            response_type=ResponseType.PERSONAL,
            state=SessionState.WAITING_CHOICE,
        )

    selected_job = jobs_list[choice - 1]
    job_config = JOB_CONFIG[selected_job]

    async with get_session() as session:

        stats_res = await session.execute(
            select(UserStats).where(UserStats.user_id == context.user_id)
        )
        stats = stats_res.scalar_one_or_none()

        if stats and stats.level < job_config["min_level"]:
            return GameResponse(
                text=(
                    f"⛔ برای شغل {job_config['name']} باید "
                    f"حداقل سطح {job_config['min_level']} باشی.\n"
                    f"سطح فعلی: {stats.level}"
                ),
                response_type=ResponseType.PERSONAL,
                error=GameError.LEVEL_TOO_LOW,
            )

        member_res = await session.execute(
            select(CityMember).where(
                CityMember.city_id == context.city_id,
                CityMember.user_id == context.user_id,
            )
        )
        member = member_res.scalar_one_or_none()

        if member:
            member.current_job = selected_job
            await session.flush()

    await clear_session(context.user_id, context.city_id)

    return GameResponse(
        text=(
            f"✅ شغل تغییر کرد.\n\n"
            f"{job_config['icon']} <b>{job_config['name']}</b>\n"
            f"درآمد: ◈ {job_config['min']:,} تا {job_config['max']:,}\n"
            f"انرژی: {job_config['energy']}\n"
            f"XP: {job_config['xp']}\n\n"
            f"برای کار کردن، «کار» بنویس."
        ),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۱۶. اکتشاف
# ================================================================

@register_action(IntentType.EXPLORE)
async def handle_explore(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    # کولداون
    if await is_on_cooldown(context.user_id, context.city_id, "explore"):
        ttl = await cooldown_ttl(context.user_id, context.city_id, "explore")
        hours = ttl // 3600
        minutes = (ttl % 3600) // 60
        return GameResponse(
            text=(
                f"⏳ <b>کولداون اکتشاف</b>\n\n"
                f"باید {hours} ساعت و {minutes} دقیقه صبر کنی."
            ),
            response_type=ResponseType.PERSONAL,
            error=GameError.COOLDOWN,
        )

    async with distributed_lock(
        f"explore:{context.user_id}:{context.city_id}",
        ttl_seconds=10,
        wait_seconds=3,
    ) as acquired:

        if not acquired:
            return error_response(GameError.COOLDOWN)

        async with get_session() as session:

            member_res = await session.execute(
                select(CityMember).where(
                    CityMember.city_id == context.city_id,
                    CityMember.user_id == context.user_id,
                    CityMember.is_active.is_(True),
                )
            )
            member = member_res.scalar_one_or_none()

            if not member:
                return error_response(GameError.NOT_MEMBER)

            if member.energy < settings.explore_energy_cost:
                return error_response(GameError.INSUFFICIENT_ENERGY)

            member.energy -= settings.explore_energy_cost
            member.last_active_at = utcnow()

            # تعیین نتیجه
            roll = random.randint(1, 100)
            cumulative = 0

            result_type = "nothing"

            cumulative += settings.explore_chance_nothing
            if roll <= cumulative:
                result_type = "nothing"
            else:
                cumulative += settings.explore_chance_money
                if roll <= cumulative:
                    result_type = "money"
                else:
                    cumulative += settings.explore_chance_trap
                    if roll <= cumulative:
                        result_type = "trap"
                    else:
                        cumulative += settings.explore_chance_special
                        if roll <= cumulative:
                            result_type = "special"
                        else:
                            result_type = "legendary"

            stats_res = await session.execute(
                select(UserStats).where(UserStats.user_id == context.user_id)
            )
            stats = stats_res.scalar_one_or_none()
            if stats:
                stats.total_explores += 1

            public_announcement = None
            text = ""
            xp_bonus = settings.explore_base_xp

            if result_type == "nothing":

                text = (
                    "🧭 <b>اکتشاف</b>\n\n"
                    "منطقه خالی بود.\n"
                    "چیزی پیدا نشد.\n\n"
                    f"⚡ {settings.explore_energy_cost} انرژی مصرف شد."
                )

            elif result_type == "money":

                amount = random.randint(
                    settings.explore_money_min,
                    settings.explore_money_max,
                )

                await apply_wallet_delta(
                    session,
                    context.user_id,
                    context.city_id,
                    cash_delta=amount,
                )

                text = (
                    "🧭 <b>اکتشاف — موفق!</b>\n\n"
                    "یه گاوصندوق قدیمی پیدا کردی!\n\n"
                    f"◈ {amount:,} اکو به دست آوردی.\n"
                    f"⚡ {settings.explore_energy_cost} انرژی مصرف شد."
                )

            elif result_type == "trap":

                trap_energy = random.randint(
                    settings.explore_trap_energy_min,
                    settings.explore_trap_energy_max,
                )

                member.energy = max(0, member.energy - trap_energy)

                text = (
                    "🧭 <b>اکتشاف — تله!</b>\n\n"
                    "منطقه ناامن بود. تله افتادی!\n\n"
                    f"⚡ {settings.explore_energy_cost + trap_energy} انرژی از دست دادی.\n"
                    "دفعه بعد احتیاط کن!"
                )

            elif result_type == "special":

                discovery = random.choice(GameConstants.SPECIAL_DISCOVERIES)
                xp_bonus += settings.explore_special_xp_bonus

                if stats:
                    stats.special_discoveries += 1

                await add_city_history(
                    session,
                    context.city_id,
                    "special_discovery",
                    f"{context.display_name or context.username or str(context.user_id)} «{discovery}» رو کشف کرد",
                    actor_user_id=context.user_id,
                )

                text = (
                    "🧭 <b>کشف ویژه!</b>\n\n"
                    f"«{discovery}» پیدا کردی!\n\n"
                    f"⭐ {xp_bonus} XP کسب کردی.\n"
                    f"📜 این کشف در تاریخ شهر ثبت شد.\n"
                    f"⚡ {settings.explore_energy_cost} انرژی مصرف شد."
                )

            else:  # legendary

                discovery = random.choice(GameConstants.LEGENDARY_DISCOVERIES)
                xp_bonus += settings.explore_legendary_xp
                eco_reward = settings.explore_legendary_eco

                await apply_wallet_delta(
                    session,
                    context.user_id,
                    context.city_id,
                    cash_delta=eco_reward,
                )

                if stats:
                    stats.legendary_discoveries += 1
                    stats.fame += 500

                name = context.display_name or context.username or str(context.user_id)

                await add_city_history(
                    session,
                    context.city_id,
                    "legendary_discovery",
                    f"💎 {name} اولین کسی بود که «{discovery}» رو کشف کرد!",
                    actor_user_id=context.user_id,
                    metadata={"discovery": discovery},
                )

                public_announcement = (
                    f"💎 <b>کشف افسانه‌ای!</b>\n\n"
                    f"{name} اولین کسی بود که\n"
                    f"«{discovery}» رو کشف کرد!\n\n"
                    f"این لحظه در تاریخ شهر ثبت شد."
                )

                text = (
                    "💎 <b>کشف افسانه‌ای!</b>\n\n"
                    f"«{discovery}» — اولین کشف از این نوع در شهر!\n\n"
                    f"◈ {eco_reward:,} اکو جایزه گرفتی.\n"
                    f"⭐ {xp_bonus} XP کسب کردی.\n"
                    f"🏅 ۵۰۰ امتیاز شهرت اضافه شد.\n"
                    f"📜 نامت در تاریخ شهر ثبت شد!"
                )

            await add_bricks_to_city(
                session, context.city_id, context.user_id, 2
            )

            await session.flush()

            # XP
            await add_xp_and_check_level(session, context.user_id, xp_bonus)

            # پیشرفت مأموریت
            await update_mission_progress(
                session, context.user_id, context.city_id,
                "explore_count", increment=1,
            )

    await set_cooldown(
        context.user_id, context.city_id,
        "explore", settings.explore_cooldown_seconds,
    )

    return GameResponse(
        text=text,
        response_type=ResponseType.PERSONAL,
        public_announcement=public_announcement,
    )


# ================================================================
# ۱۷. مأموریت‌ها
# ================================================================

@register_action(IntentType.MISSIONS)
async def handle_missions(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    async with get_session() as session:

        daily_missions = await get_active_missions(
            session, context.city_id, MissionType.DAILY.value
        )
        weekly_missions = await get_active_missions(
            session, context.city_id, MissionType.WEEKLY.value
        )

        # وضعیت پیشرفت هر مأموریت
        all_missions = daily_missions + weekly_missions
        progress_map = {}

        for mission in all_missions:
            progress = await get_mission_progress(
                session,
                context.user_id,
                context.city_id,
                mission.id,
            )
            progress_map[mission.id] = progress

    lines = ["🎯 <b>مأموریت‌های تو</b>\n"]

    if daily_missions:
        lines.append("━━━ <b>روزانه</b> ━━━")
        for m in daily_missions:
            progress = progress_map.get(m.id)
            if progress and progress.status == MissionStatus.COMPLETED.value:
                status_icon = "✅"
                progress_text = "تکمیل شده"
            elif progress:
                pct = int((progress.current_value / max(m.goal_value, 1)) * 10)
                bar = "█" * pct + "░" * (10 - pct)
                progress_text = f"[{bar}] {progress.current_value}/{m.goal_value}"
                status_icon = "🔄"
            else:
                status_icon = "⭕"
                progress_text = f"۰/{m.goal_value}"

            lines.append(
                f"\n{status_icon} <b>{m.title}</b>\n"
                f"   {progress_text}\n"
                f"   🏆 ◈ {m.reward_eco:,} | ⭐ {m.reward_xp:,} XP"
            )

    if weekly_missions:
        lines.append("\n━━━ <b>هفتگی</b> ━━━")
        for m in weekly_missions:
            progress = progress_map.get(m.id)
            if progress and progress.status == MissionStatus.COMPLETED.value:
                status_icon = "✅"
                progress_text = "تکمیل شده"
            elif progress:
                pct = int((progress.current_value / max(m.goal_value, 1)) * 10)
                bar = "█" * pct + "░" * (10 - pct)
                progress_text = f"[{bar}] {progress.current_value}/{m.goal_value}"
                status_icon = "🔄"
            else:
                status_icon = "⭕"
                progress_text = f"۰/{m.goal_value}"

            lines.append(
                f"\n{status_icon} <b>{m.title}</b>\n"
                f"   {progress_text}\n"
                f"   🏆 ◈ {m.reward_eco:,} | ⭐ {m.reward_xp:,} XP"
            )

    if not daily_missions and not weekly_missions:
        lines.append("\nهنوز مأموریتی تعریف نشده.\nبه زودی مأموریت‌های جدید میان!")

    return GameResponse(
        text="\n".join(lines),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۱۸. معدن
# ================================================================

@register_action(IntentType.MINE)
async def handle_mine(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    async with get_session() as session:

        mine = await get_or_create_mine(session, context.user_id)

        if mine is None:
            return error_response(GameError.NO_MINE)

        production = await calculate_mine_production(session, context.user_id)

    mine_name = GameConstants.MINE_LEVELS.get(production["level"], "معدن")
    hourly = production["hourly_rate"]
    accumulated = production["accumulated"]
    max_storage = production["max_storage"]

    fill_pct = int((accumulated / max(max_storage, 1)) * 10)
    storage_bar = "█" * fill_pct + "░" * (10 - fill_pct)

    text = (
        f"⛏ <b>معدن تو — {mine_name}</b>\n\n"
        f"📦 ذخیره: [{storage_bar}]\n"
        f"   ◈ {accumulated:,} / {max_storage:,}\n\n"
        f"⚡ تولید: ◈ {hourly:,} در ساعت\n\n"
    )

    if accumulated > 0:
        text += "برای برداشت، «برداشت از معدن» بنویس."

        return GameResponse(
            text=text,
            response_type=ResponseType.PERSONAL,
            actions=[
                ActionButton(
                    action="mine_collect",
                    label=f"برداشت ◈ {accumulated:,}",
                    style=ActionStyle.SUCCESS,
                )
            ],
            requires_ui=True,
        )

    text += "معدنت هنوز در حال تولیده.\nبعداً برگرد و برداشت کن."

    return GameResponse(
        text=text,
        response_type=ResponseType.PERSONAL,
    )


async def handle_mine_collect(
    context: GameContext,
) -> GameResponse:

    async with get_session() as session:

        mine = await get_or_create_mine(session, context.user_id)

        if not mine:
            return error_response(GameError.NO_MINE)

        result = await collect_mine(
            session,
            context.user_id,
            context.city_id,
        )

    if result["collected"] <= 0:
        return GameResponse(
            text="⛏ معدنت هنوز خالیه. بعداً برگرد.",
            response_type=ResponseType.PERSONAL,
        )

    return GameResponse(
        text=(
            f"⛏ <b>برداشت معدن</b>\n\n"
            f"◈ {result['collected']:,} اکو برداشت کردی.\n\n"
            f"معدن دوباره شروع کرد به کار."
        ),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۱۹. رویداد جمعی
# ================================================================

@register_action(IntentType.PARTICIPATE)
async def handle_participate(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:
    return await _join_event(context, "participate")


@register_action(IntentType.DEFEND)
async def handle_defend(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:
    return await _join_event(context, "defend")


@register_action(IntentType.HELP_CITY)
async def handle_help_city(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:
    return await _join_event(context, "help")


async def _join_event(
    context: GameContext,
    action_type: str,
) -> GameResponse:

    async with get_session() as session:

        event = await get_active_event(session, context.city_id)

        if not event:
            return error_response(GameError.NO_EVENT)

        now = utcnow()
        if event.ends_at <= now:
            return error_response(GameError.EVENT_ENDED)

        # بررسی شرکت قبلی
        already = await is_event_participant(event.id, context.user_id)
        if already and event.event_type not in (
            EventType.CRISIS.value, EventType.ATTACK.value
        ):
            return error_response(GameError.ALREADY_PARTICIPANT)

        member_res = await session.execute(
            select(CityMember).where(
                CityMember.city_id == context.city_id,
                CityMember.user_id == context.user_id,
                CityMember.is_active.is_(True),
            )
        )
        member = member_res.scalar_one_or_none()

        if not member:
            return error_response(GameError.NOT_MEMBER)

        # تعیین کمک بر اساس نوع رویداد
        contribution = 0
        cost_text = ""

        if event.event_type == EventType.ATTACK.value:

            energy_cost = 20
            if member.energy < energy_cost:
                return error_response(GameError.INSUFFICIENT_ENERGY)

            member.energy -= energy_cost
            contribution = energy_cost
            cost_text = f"⚡ {energy_cost} انرژی مصرف شد."

        elif event.event_type == EventType.CRISIS.value:

            # بعداً با منوی مبلغ انجام می‌شه
            # فعلاً ۱۰۰۰ اکو پیش‌فرض
            eco_cost = 1_000
            wallet = await get_wallet(session, context.user_id, context.city_id)

            if not wallet or wallet.cash < eco_cost:
                return error_response(GameError.INSUFFICIENT_FUNDS)

            await apply_wallet_delta(
                session,
                context.user_id,
                context.city_id,
                cash_delta=-eco_cost,
            )

            contribution = eco_cost
            cost_text = f"◈ {eco_cost:,} اکو کمک کردی."

        elif event.event_type in (
            EventType.FESTIVAL.value,
            EventType.EXPLORE.value,
        ):
            contribution = 1
            cost_text = "شرکت ثبت شد."

        # ثبت شرکت
        participant, is_new = await add_event_participation(
            session, event.id, context.user_id, contribution
        )

        # آپدیت Redis
        await set_event_participant(
            event.id, context.user_id, contribution, ttl_seconds=86_400
        )

        progress = await get_event_progress(event.id)

        remaining = max(0, event.target_value - event.current_value)
        progress_pct = int(
            (event.current_value / max(event.target_value, 1)) * 100
        )

        fill = int(progress_pct / 10)
        progress_bar = "█" * fill + "░" * (10 - fill)

    return GameResponse(
        text=(
            f"✅ <b>شرکت در رویداد</b>\n\n"
            f"{event.title}\n\n"
            f"{cost_text}\n\n"
            f"پیشرفت: [{progress_bar}] {progress_pct}٪\n"
            f"({event.current_value:,}/{event.target_value:,})\n\n"
            + (
                f"✅ هدف رسید! جوایز به زودی توزیع می‌شه."
                if event.current_value >= event.target_value
                else f"تا رسیدن به هدف: {remaining:,} مانده"
            )
        ),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۲۰. رتبه‌بندی
# ================================================================

@register_action(IntentType.RANK)
async def handle_rank(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    async with get_session() as session:
        rows = await get_city_leaderboard(session, context.city_id, limit=10)

    if not rows:
        return GameResponse(
            text="🏆 هنوز کسی در رتبه‌بندی نیست.",
            response_type=ResponseType.PERSONAL,
        )

    lines = ["🏆 <b>رتبه‌بندی شهر</b>\n"]

    medals = GameConstants.RANK_MEDALS

    for i, row in enumerate(rows):
        user = row["user"]
        stats = row["stats"]
        total = row["total_eco"]

        medal = medals[i] if i < len(medals) else f"{i + 1}."
        name = f"@{user.username}" if user.username else user.display_name or str(user.id)

        # نشان‌دهنده کاربر فعلی
        me = " 👈" if user.id == context.user_id else ""

        lines.append(
            f"{medal} <b>{name}</b>{me}\n"
            f"   سطح {stats.level} | ◈ {total:,}"
        )

    return GameResponse(
        text="\n".join(lines),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۲۱. تاریخچه شهر
# ================================================================

@register_action(IntentType.HISTORY)
async def handle_history(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    async with get_session() as session:
        records = await get_city_history(session, context.city_id, limit=15)

    if not records:
        return GameResponse(
            text="📜 تاریخ شهر هنوز خالیه.\nاولین رویداد رو تو رقم بزن!",
            response_type=ResponseType.PERSONAL,
        )

    lines = ["📜 <b>تاریخ شهر</b>\n"]

    for record in records:
        date_str = record.created_at.strftime("%d/%m %H:%M")
        lines.append(f"• [{date_str}] {record.title}")

    return GameResponse(
        text="\n".join(lines),
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۲۲. واریز به بانک
# ================================================================

@register_action(IntentType.DEPOSIT)
async def handle_deposit(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    amount = parse_amount(context.normalized_text.replace("واریز", "").strip())

    if amount is None:

        await save_session(
            context.user_id,
            context.city_id,
            SessionState.WAITING_AMOUNT,
            {"action": "deposit"},
        )

        async with get_session() as session:
            wallet = await get_wallet(session, context.user_id, context.city_id)

        cash = wallet.cash if wallet else 0

        return GameResponse(
            text=(
                f"🏦 <b>واریز به بانک</b>\n\n"
                f"موجودی نقد: ◈ {cash:,}\n\n"
                f"چقدر می‌خوای واریز کنی؟\n"
                f"(حداقل ◈ {GameConstants.MIN_BANK_DEPOSIT:,})"
            ),
            response_type=ResponseType.PERSONAL,
            state=SessionState.WAITING_AMOUNT,
        )

    if amount < GameConstants.MIN_BANK_DEPOSIT:
        return GameResponse(
            text=f"⚠️ حداقل مقدار واریز ◈ {GameConstants.MIN_BANK_DEPOSIT:,} است.",
            response_type=ResponseType.PERSONAL,
        )

    async with get_session() as session:
        try:
            wallet = await apply_wallet_delta(
                session,
                context.user_id,
                context.city_id,
                cash_delta=-amount,
                bank_delta=amount,
            )

            await clear_session(context.user_id, context.city_id)

            return GameResponse(
                text=(
                    f"🏦 <b>واریز موفق</b>\n\n"
                    f"◈ {amount:,} به بانک واریز شد.\n\n"
                    f"💵 نقد: ◈ {wallet.cash:,}\n"
                    f"🏦 بانک: ◈ {wallet.bank:,}"
                ),
                response_type=ResponseType.PERSONAL,
            )

        except InsufficientFundsError:
            return error_response(GameError.INSUFFICIENT_FUNDS)


# ================================================================
# ۲۳. برداشت از بانک
# ================================================================

@register_action(IntentType.WITHDRAW)
async def handle_withdraw(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    amount = parse_amount(
        context.normalized_text.replace("برداشت از بانک", "")
        .replace("برداشت بانک", "").strip()
    )

    if amount is None:

        await save_session(
            context.user_id,
            context.city_id,
            SessionState.WAITING_AMOUNT,
            {"action": "withdraw"},
        )

        async with get_session() as session:
            wallet = await get_wallet(session, context.user_id, context.city_id)

        bank = wallet.bank if wallet else 0

        return GameResponse(
            text=(
                f"🏦 <b>برداشت از بانک</b>\n\n"
                f"موجودی بانک: ◈ {bank:,}\n\n"
                f"چقدر می‌خوای برداشت کنی؟"
            ),
            response_type=ResponseType.PERSONAL,
            state=SessionState.WAITING_AMOUNT,
        )

    async with get_session() as session:
        try:
            wallet = await apply_wallet_delta(
                session,
                context.user_id,
                context.city_id,
                cash_delta=amount,
                bank_delta=-amount,
            )

            await clear_session(context.user_id, context.city_id)

            return GameResponse(
                text=(
                    f"🏦 <b>برداشت موفق</b>\n\n"
                    f"◈ {amount:,} از بانک برداشت شد.\n\n"
                    f"💵 نقد: ◈ {wallet.cash:,}\n"
                    f"🏦 بانک: ◈ {wallet.bank:,}"
                ),
                response_type=ResponseType.PERSONAL,
            )

        except InsufficientFundsError:
            return error_response(GameError.INSUFFICIENT_FUNDS)


# ================================================================
# ۲۴. فروشگاه
# ================================================================

@register_action(IntentType.SHOP)
async def handle_shop(
    context: GameContext,
    _session: Optional[dict[str, Any]],
) -> GameResponse:

    async with get_session() as session:
        user_res = await session.execute(
            select(User).where(User.id == context.user_id)
        )
        user = user_res.scalar_one_or_none()

    diamonds = user.diamonds if user else 0

    text = (
        f"💎 <b>فروشگاه اِکو</b>\n\n"
        f"الماس فعلی: 💎 {diamonds:,}\n\n"

        f"━━━ <b>بسته‌های الماس</b> ━━━\n\n"

        f"1️⃣ {settings.diamond_pack_small} الماس\n"
        f"   {settings.diamond_pack_small_price:,} تومان\n\n"

        f"2️⃣ {settings.diamond_pack_medium} الماس (+۱۰٪ بونوس)\n"
        f"   {settings.diamond_pack_medium_price:,} تومان\n\n"

        f"3️⃣ {settings.diamond_pack_large} الماس (+۲۰٪ بونوس)\n"
        f"   {settings.diamond_pack_large_price:,} تومان\n\n"

        f"4️⃣ {settings.diamond_pack_xlarge} الماس (+۳۵٪ بونوس)\n"
        f"   {settings.diamond_pack_xlarge_price:,} تومان\n\n"

        f"━━━ <b>آیتم‌های الماسی</b> ━━━\n\n"

        f"⚡ شارژ فوری انرژی — 💎 {settings.diamond_energy_refill}\n"
        f"📈 ۲x درآمد (۲۴ ساعت) — 💎 {settings.diamond_income_boost_24h}\n"
        f"🛡 سپر ریسک — 💎 {settings.diamond_risk_shield}\n"
        f"⛏ معدن خاک — 💎 {settings.mine_buy_cost_diamonds}\n\n"

        f"━━━ <b>اشتراک طلایی</b> ━━━\n\n"

        f"✨ شهروند طلایی — {settings.gold_subscription_price:,} تومان/ماه\n"
        f"   • {settings.gold_subscription_daily_diamonds} الماس رایگان روزانه\n"
        f"   • {settings.gold_subscription_income_bonus}٪ درآمد بیشتر\n"
        f"   • شارژ انرژی روزانه رایگان\n"
        f"   • نشان ویژه ✨\n\n"

        f"برای خرید با پشتیبانی تماس بگیر."
    )

    return GameResponse(
        text=text,
        response_type=ResponseType.PERSONAL,
    )


# ================================================================
# ۲۵. پردازش پیام گروه (اِکوی خودکار)
# ================================================================

async def process_group_message(
    context: GameContext,
) -> GameResponse:
    """
    هر پیام در گروه → اِکو + آجر خودکار.
    بدون نیاز به دستور خاص.
    """

    # نرخ‌گذاری
    allowed = await check_rate_limit(context.user_id, "group")
    if not allowed:
        return GameResponse(response_type=ResponseType.SILENT)

    # بررسی حد روزانه اِکو از پیام
    daily_key = RedisKeys.daily_eco(context.user_id, context.city_id)
    eco_allowed, current_eco = await increment_daily_counter(
        daily_key,
        settings.max_eco_from_messages_daily // settings.eco_per_message,
    )

    if not eco_allowed:
        return GameResponse(response_type=ResponseType.SILENT)

    async with get_session() as session:

        # ثبت خودکار کاربر و عضویت
        user, is_new_user = await get_or_create_user(
            session,
            context.user_id,
            username=context.username or None,
            display_name=context.display_name or None,
        )

        if user.is_banned:
            return GameResponse(response_type=ResponseType.SILENT)

        member, is_new_member = await get_or_create_city_member(
            session,
            context.city_id,
            context.user_id,
        )

        # اِکو از پیام
        eco = settings.eco_per_message
        xp = settings.xp_per_message

        await apply_wallet_delta(
            session,
            context.user_id,
            context.city_id,
            cash_delta=eco,
        )

        # آجر به شهر
        city_result = await add_bricks_to_city(
            session,
            context.city_id,
            context.user_id,
            1,
        )

        # XP
        xp_result = await add_xp_and_check_level(
            session,
            context.user_id,
            xp,
        )

        # پیشرفت رقابت
        event = await get_active_event(session, context.city_id)
        if event and event.event_type == EventType.CONTEST.value:
            await add_contest_score(event.id, context.user_id, xp)

        # به‌روزرسانی آخرین فعالیت
        member.last_active_at = utcnow()
        user.last_active_at = utcnow()
        await session.flush()

    # اعلامیه‌های مهم
    announcement = None

    if is_new_member:
        name = context.display_name or context.username or str(context.user_id)
        announcement = (
            f"〰️ <b>{name}</b> به شهر پیوست!\n"
            f"◈ {settings.starting_eco:,} اکو به عنوان خوش‌آمدگویی دریافت کرد."
        )

    elif xp_result.get("leveled_up"):
        name = context.display_name or context.username or str(context.user_id)
        announcement = (
            f"🎉 <b>{name}</b> به سطح "
            f"{xp_result['new_level']} رسید!"
        )

    elif city_result.get("leveled_up"):
        announcement = (
            f"🏙 <b>شهر به سطح {city_result['new_level']} رسید!</b>\n"
            f"تبریک به همه شهروندان! 🎊"
        )

    # واکنش تصادفی ربات (گاهی)
    if (
        not announcement
        and random.randint(1, 100) <= settings.random_reaction_chance
    ):
        name = context.display_name or context.username or str(context.user_id)
        reaction = random.choice(GameConstants.RANDOM_REACTIONS)
        announcement = reaction.format(name=name)

    if announcement:
        return GameResponse(
            text=announcement,
            response_type=ResponseType.PUBLIC,
            public=True,
        )

    return GameResponse(response_type=ResponseType.SILENT)


# ================================================================
# ۲۶. پردازش ورودی سِشن فعال
# ================================================================

async def handle_session_input(
    context: GameContext,
    session_data: dict[str, Any],
) -> GameResponse:

    state_value = session_data.get("state", SessionState.IDLE.value)
    payload = session_data.get("payload", {})

    try:
        state = SessionState(state_value)
    except ValueError:
        await clear_session(context.user_id, context.city_id)
        return error_response(GameError.SESSION_EXPIRED)

    normalized = context.normalized_text

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # آموزش
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if state == SessionState.TUTORIAL_ACTIVE:

        step = payload.get("tutorial_step", 0)

        if step < len(TUTORIAL_STEPS) - 1:
            next_step = step + 1
            step_data = TUTORIAL_STEPS[next_step]

            await save_session(
                context.user_id,
                context.city_id,
                SessionState.TUTORIAL_ACTIVE,
                {"tutorial_step": next_step},
            )

            return GameResponse(
                text=step_data["text"],
                response_type=ResponseType.PERSONAL,
                state=SessionState.TUTORIAL_ACTIVE,
                actions=[
                    ActionButton(
                        action=f"tutorial_step_{next_step}",
                        label=step_data["action"],
                        style=ActionStyle.SUCCESS,
                    )
                ],
                requires_ui=True,
            )

        else:
            await clear_session(context.user_id, context.city_id)

            return GameResponse(
                text=(
                    "🎉 <b>آموزش تموم شد!</b>\n\n"
                    "الان یه شهروند کامل اِکو هستی.\n\n"
                    "برو توی گروه و شروع کن:\n"
                    "💼 «کار» — برای درآمد\n"
                    "🧭 «اکتشاف» — برای ماجراجویی\n"
                    "🎯 «مأموریت» — برای هدف‌گذاری\n\n"
                    "شهر منتظرته! 〰️"
                ),
                response_type=ResponseType.PERSONAL,
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # انتظار مبلغ
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if state == SessionState.WAITING_AMOUNT:

        intent = detect_intent(normalized)

        if intent == IntentType.CANCEL:
            await clear_session(context.user_id, context.city_id)
            return GameResponse(
                text="❌ لغو شد.",
                response_type=ResponseType.PERSONAL,
            )

        amount = parse_amount(normalized)

        if amount is None:
            return GameResponse(
                text="⚠️ عدد معتبر وارد کن.\nمثلاً: ۱۰۰۰",
                response_type=ResponseType.PERSONAL,
                state=state,
            )

        action = payload.get("action")

        if action == "deposit":
            new_context = GameContext(
                user_id=context.user_id,
                city_id=context.city_id,
                chat_id=context.chat_id,
                message_id=context.message_id,
                text=f"واریز {amount}",
                is_group=context.is_group,
                is_private=context.is_private,
                username=context.username,
            )
            await clear_session(context.user_id, context.city_id)
            return await handle_deposit(new_context, None)

        elif action == "withdraw":
            new_context = GameContext(
                user_id=context.user_id,
                city_id=context.city_id,
                chat_id=context.chat_id,
                message_id=context.message_id,
                text=f"برداشت بانک {amount}",
                is_group=context.is_group,
                is_private=context.is_private,
                username=context.username,
            )
            await clear_session(context.user_id, context.city_id)
            return await handle_withdraw(new_context, None)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # انتخاب شغل
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if state == SessionState.WAITING_CHOICE:

        action = payload.get("action")

        if action == "job_select":
            return await handle_job_select(context, payload)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # سِشن ناشناس
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    await clear_session(context.user_id, context.city_id)
    return error_response(GameError.SESSION_EXPIRED)


# ================================================================
# ۲۷. پردازشگر مرکزی پیام
# ================================================================

async def process_message(
    context: GameContext,
) -> GameResponse:
    """
    خط اصلی پردازش بازی اِکو.
    """

    # ━━━ ورودی خالی ━━━
    if not context.normalized_text:
        return GameResponse(response_type=ResponseType.SILENT)

    # ━━━ نرخ‌گذاری ━━━
    allowed = await check_rate_limit(context.user_id, "message")
    if not allowed:
        return error_response(GameError.RATE_LIMITED)

    # ━━━ سِشن فعال ━━━
    session = await get_active_session(context.user_id, context.city_id)

    if session:
        # اگه کاربر دستور صریح زده، سِشن رو ببند
        intent = detect_intent(context.normalized_text)

        if intent not in (
            IntentType.NO_INTENT,
            IntentType.NUMERIC,
            IntentType.CONFIRM,
            IntentType.CANCEL,
        ) and intent not in (
            IntentType.PARTICIPATE,
            IntentType.DEFEND,
            IntentType.HELP_CITY,
        ):
            await clear_session(context.user_id, context.city_id)
        else:
            return await handle_session_input(context, session)

    # ━━━ تشخیص نیت ━━━
    intent = detect_intent(context.normalized_text)

    # ━━━ چت معمولی ━━━
    if intent == IntentType.NO_INTENT:
        return GameResponse(response_type=ResponseType.SILENT)

    # ━━━ عدد بدون سِشن ━━━
    if intent == IntentType.NUMERIC:
        return GameResponse(response_type=ResponseType.SILENT)

    # ━━━ تأیید/لغو بدون سِشن ━━━
    if intent in (IntentType.CONFIRM, IntentType.CANCEL):
        return GameResponse(response_type=ResponseType.SILENT)

    # ━━━ بررسی دسترسی ━━━
    access_error = check_access(intent, context)
    if access_error:
        return error_response(access_error)

    # ━━━ بررسی عضویت ━━━
    rule = ACCESS_RULES.get(intent)
    if rule and rule.requires_member:
        if not await is_city_member(context.user_id, context.city_id):
            # ثبت خودکار
            async with get_session() as session:
                await get_or_create_user(
                    session,
                    context.user_id,
                    username=context.username or None,
                    display_name=context.display_name or None,
                )
                await get_or_create_city_member(
                    session,
                    context.city_id,
                    context.user_id,
                )

    # ━━━ اجرای اکشن ━━━
    action = _ACTIONS.get(intent)

    if action is None:
        return error_response(GameError.UNKNOWN_INTENT)

    return await action(context, None)


# ================================================================
# ۲۸. ساخت رویداد جمعی (برای تسک پس‌زمینه)
# ================================================================

async def create_random_city_event(
    city_id: int,
    population: int,
) -> Optional[dict[str, Any]]:
    """
    یه رویداد تصادفی برای شهر می‌سازد.
    اطلاعات رویداد برای ارسال پیام برمی‌گردد.
    """

    if population < GameConstants.MIN_POPULATION_FOR_EVENTS:
        return None

    # انتخاب نوع رویداد
    event_types = [
        EventType.CRISIS.value,
        EventType.ATTACK.value,
        EventType.FESTIVAL.value,
        EventType.CONTEST.value,
        EventType.EXPLORE.value,
    ]

    # وزن‌دهی
    weights = [20, 25, 30, 15, 10]
    event_type = random.choices(event_types, weights=weights, k=1)[0]

    configs = {
        EventType.CRISIS.value: {
            "title": "⚠️ بحران اقتصادی",
            "description": (
                "خزانه شهر در بحران است!\n"
                "شهروندان باید کمک کنند."
            ),
            "target": population * 1_000,
            "duration": settings.event_crisis_duration,
            "action_hint": "برای کمک «کمک» بنویس.",
        },
        EventType.ATTACK.value: {
            "title": "⚔️ حمله به شهر",
            "description": (
                "شهر تحت حمله است!\n"
                "همه باید دفاع کنند."
            ),
            "target": population * 20,
            "duration": settings.event_attack_duration,
            "action_hint": "برای دفاع «دفاع» بنویس.",
        },
        EventType.FESTIVAL.value: {
            "title": "🎉 جشن شهر",
            "description": (
                "امشب جشنه!\n"
                "همه ۲x XP می‌گیرن."
            ),
            "target": population,
            "duration": settings.event_festival_duration,
            "action_hint": "برای شرکت «شرکت» بنویس.",
        },
        EventType.CONTEST.value: {
            "title": "🏆 رقابت بزرگ",
            "description": (
                "رقابت ۲۴ ساعته شروع شد!\n"
                f"جایزه اول: ◈ {settings.event_contest_first_prize:,}"
            ),
            "target": 1,
            "duration": settings.event_contest_duration,
            "action_hint": "فعال باش و بیشترین XP رو جمع کن.",
        },
        EventType.EXPLORE.value: {
            "title": "🗺 کشف مشترک",
            "description": (
                f"یه منطقه ناشناخته پیدا شد!\n"
                f"{settings.event_explore_min_participants} نفر باید اکتشاف کنن."
            ),
            "target": settings.event_explore_min_participants,
            "duration": settings.event_explore_duration,
            "action_hint": "برای شرکت «شرکت» بنویس.",
        },
    }

    config = configs[event_type]
    hours = config["duration"] // 3600

    async with get_session() as session:

        event = await create_city_event(
            session,
            city_id=city_id,
            event_type=event_type,
            title=config["title"],
            description=config["description"],
            target_value=config["target"],
            duration_seconds=config["duration"],
        )

        event_id = event.id

    return {
        "event_id": event_id,
        "event_type": event_type,
        "title": config["title"],
        "description": config["description"],
        "target": config["target"],
        "duration_hours": hours,
        "action_hint": config["action_hint"],
        "message": (
            f"{config['title']}\n\n"
            f"{config['description']}\n\n"
            f"⏰ مهلت: {hours} ساعت\n"
            f"🎯 هدف: {config['target']:,}\n\n"
            f"{config['action_hint']}"
        ),
    }


# ================================================================
# ۲۹. پایان رویداد و توزیع جوایز
# ================================================================

async def finalize_event(
    event_id: int,
    city_id: int,
) -> Optional[dict[str, Any]]:
    """
    رویداد را پایان می‌دهد و جوایز را توزیع می‌کند.
    نتیجه برای اعلام عمومی برمی‌گردد.
    """

    async with get_session() as session:

        event_res = await session.execute(
            select(CityEvent).where(CityEvent.id == event_id)
        )
        event = event_res.scalar_one_or_none()

        if not event:
            return None

        if event.status not in (
            EventStatus.ACTIVE.value,
            EventStatus.SUCCESS.value,
        ):
            return None

        success = event.current_value >= event.target_value

        if not success:
            event.status = EventStatus.FAILED.value

            # پنالتی شکست
            if event.event_type == EventType.CRISIS.value:

                city_res = await session.execute(
                    select(City).where(City.id == city_id)
                )
                city = city_res.scalar_one_or_none()

                if city:
                    penalty = int(
                        city.treasury
                        * settings.event_crisis_fail_penalty / 100
                    )
                    city.treasury = max(0, city.treasury - penalty)

            await session.flush()

            return {
                "success": False,
                "event_type": event.event_type,
                "title": event.title,
                "message": (
                    f"⌛ <b>رویداد پایان یافت</b>\n\n"
                    f"{event.title}\n\n"
                    f"❌ شهر به هدف نرسید.\n"
                    f"({event.current_value:,}/{event.target_value:,})\n\n"
                    f"دفعه بعد با هم بهتر عمل می‌کنیم."
                ),
            }

        # رویداد موفق
        event.status = EventStatus.SUCCESS.value

        # توزیع جوایز
        participants_res = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.rewarded.is_(False),
            )
        )
        participants = participants_res.scalars().all()

        reward_eco = 0
        reward_text = ""

        if event.event_type == EventType.ATTACK.value:

            reward_eco = settings.event_attack_reward_eco

            for p in participants:
                await apply_wallet_delta(
                    session,
                    p.user_id,
                    city_id,
                    cash_delta=reward_eco,
                )
                p.rewarded = True

            reward_text = f"◈ {reward_eco:,} اکو به هر شرکت‌کننده"

        elif event.event_type == EventType.CRISIS.value:

            for p in participants:

                returned = int(
                    p.contribution
                    * settings.event_crisis_reward_multiplier
                )

                await apply_wallet_delta(
                    session,
                    p.user_id,
                    city_id,
                    cash_delta=returned,
                )

                p.rewarded = True

            reward_text = f"{settings.event_crisis_reward_multiplier}x برگشت کمک‌ها"

        elif event.event_type == EventType.CONTEST.value:

            leaderboard = await get_contest_leaderboard(event_id, top_n=3)

            prizes = [
                settings.event_contest_first_prize,
                settings.event_contest_second_prize,
                settings.event_contest_third_prize,
            ]

            for i, (user_id, score) in enumerate(leaderboard):
                if i < len(prizes):
                    await apply_wallet_delta(
                        session, user_id, city_id,
                        cash_delta=prizes[i],
                    )

            reward_text = (
                f"🥇 ◈ {prizes[0]:,} | "
                f"🥈 ◈ {prizes[1]:,} | "
                f"🥉 ◈ {prizes[2]:,}"
            )

        await add_city_history(
            session,
            city_id,
            "event_success",
            f"✅ {event.title} با موفقیت به پایان رسید",
        )

        await session.flush()

    return {
        "success": True,
        "event_type": event.event_type,
        "title": event.title,
        "participants": len(participants),
        "message": (
            f"✅ <b>رویداد موفق!</b>\n\n"
            f"{event.title}\n\n"
            f"👥 {len(participants):,} نفر شرکت کردن.\n"
            f"🏆 جایزه: {reward_text}\n\n"
            f"ممنون از همه شهروندان!"
        ),
    }


# ================================================================
# ۳۰. موتور بازی (نمای عمومی)
# ================================================================

class GameEngine:
    """نمای عمومی موتور بازی اِکو."""

    async def process_message(
        self,
        context: GameContext,
    ) -> GameResponse:
        return await process_message(context)

    async def process_group_message(
        self,
        context: GameContext,
    ) -> GameResponse:
        return await process_group_message(context)

    async def detect_intent(
        self,
        text: str,
    ) -> IntentType:
        return detect_intent(normalize_text(text))

    async def create_random_event(
        self,
        city_id: int,
        population: int,
    ) -> Optional[dict[str, Any]]:
        return await create_random_city_event(city_id, population)

    async def finalize_event(
        self,
        event_id: int,
        city_id: int,
    ) -> Optional[dict[str, Any]]:
        return await finalize_event(event_id, city_id)

    async def handle_mine_collect(
        self,
        context: GameContext,
    ) -> GameResponse:
        return await handle_mine_collect(context)


# ================================================================
# ۳۱. نمونه تنها (Singleton)
# ================================================================

_engine: Optional[GameEngine] = None


def get_game_engine() -> GameEngine:

    global _engine

    if _engine is None:
        _engine = GameEngine()

    return _engine


# ================================================================
# صادرات
# ================================================================

__all__ = [
    "IntentType",
    "SessionState",
    "ResponseType",
    "ActionStyle",
    "GameError",
    "GameContext",
    "ActionButton",
    "GameResponse",
    "normalize_text",
    "normalize_digits",
    "parse_amount",
    "detect_intent",
    "process_message",
    "process_group_message",
    "create_random_city_event",
    "finalize_event",
    "GameEngine",
    "get_game_engine",
    "TUTORIAL_STEPS",
    "JOB_CONFIG",
]
