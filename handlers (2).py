# ================================================================
# اِکو — handlers.py
# هندلرهای تلگرام و رابط کاربری
# ================================================================
#
# بنویس. بساز. حکومت کن.
#
# مسئولیت این فایل:
#   - دریافت آپدیت‌های تلگرام
#   - ساخت دکمه‌ها و کیبوردها
#   - رندر پاسخ‌های بازی
#   - مدیریت کال‌بک‌ها
#   - هندلر گروه و ربات خصوصی
#
# این فایل شامل موارد زیر نیست:
#   - منطق بازی
#   - کوئری دیتابیس مستقیم
#   - محاسبات بازی
# ================================================================

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from sqlalchemy import select

from config import settings, GameConstants
from database import (
    City,
    CityMember,
    User,
    UserStats,
    UserWallet,
    UserMine,
    CityEvent,
    EventStatus,
    CityMemberRole,
    JobType,
    MineLevel,
    get_session,
    get_city_by_chat,
    get_or_restore_city,
    get_or_create_user,
    get_or_create_city_member,
    get_city_member,
    get_wallet,
    get_active_event,
    deactivate_city,
    get_city_population,
    get_or_create_mine,
    spend_diamonds,
    set_income_boost,
    set_risk_shield,
    add_diamonds,
    restore_energy_for_city,
    InsufficientDiamondsError,
)

from game import (
    ActionButton,
    ActionStyle,
    GameContext,
    GameResponse,
    GameError,
    ResponseType,
    SessionState,
    IntentType,
    get_game_engine,
    process_message,
    process_group_message,
    normalize_text,
    detect_intent,
    TUTORIAL_STEPS,
    JOB_CONFIG,
)


# ================================================================
# لاگر
# ================================================================

logger = logging.getLogger("echo.handlers")


# ================================================================
# روترها
# ================================================================

private_router = Router(name="echo_private")
group_router   = Router(name="echo_group")

private_router.message.filter(
    F.chat.type == ChatType.PRIVATE
)
private_router.callback_query.filter(
    F.message.chat.type == ChatType.PRIVATE
)

group_router.message.filter(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
)
group_router.callback_query.filter(
    F.message.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
)


# ================================================================
# ساخت دکمه
# ================================================================

def btn(
    label: str,
    data: str,
    style: str = "primary",
) -> InlineKeyboardButton:
    """دکمه اینلاین ساده."""
    return InlineKeyboardButton(
        text=label,
        callback_data=data,
    )


def url_btn(
    label: str,
    url: str,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label,
        url=url,
    )


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    """ساخت کیبورد از ردیف‌های دکمه."""
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


# ━━━ دکمه‌های پرکاربرد ━━━

def back_btn(to: str = "menu:main") -> InlineKeyboardButton:
    return btn("🔙 بازگشت", to)


def close_btn() -> InlineKeyboardButton:
    return btn("✖️ بستن", "ui:close")


def confirm_btn(data: str) -> InlineKeyboardButton:
    return btn("✅ تأیید", data)


def cancel_btn(data: str = "ui:cancel") -> InlineKeyboardButton:
    return btn("❌ لغو", data)


# ================================================================
# کیبوردهای اصلی
# ================================================================

def main_menu_kb(
    has_mine: bool = False,
    city_name: str = "شهر",
) -> InlineKeyboardMarkup:
    """منوی اصلی ربات."""

    rows = [
        [
            btn("💼 کار", "action:work"),
            btn("🧭 اکتشاف", "action:explore"),
        ],
        [
            btn("🎯 مأموریت‌ها", "action:missions"),
            btn("👤 پروفایل", "action:profile"),
        ],
        [
            btn(f"🏙 {city_name}", "action:city"),
            btn("🏆 رتبه‌بندی", "action:rank"),
        ],
        [
            btn("⛏ معدن" + (" ✨" if has_mine else ""), "action:mine"),
            btn("🏪 بازار", "action:market"),
        ],
        [
            btn("⚔️ گیلد", "action:guild"),
            btn("📜 تاریخ شهر", "action:history"),
        ],
        [
            btn("💰 بانک", "menu:bank"),
            btn("↔️ انتقال", "action:transfer"),
        ],
        [
            btn("💎 فروشگاه", "menu:shop"),
            btn("❓ راهنما", "menu:help"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def bank_menu_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("🏦 واریز به بانک", "action:deposit")],
        [btn("💵 برداشت از بانک", "action:withdraw")],
        [back_btn("menu:main")],
    )


def shop_menu_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("💎 خرید الماس", "shop:diamonds")],
        [btn("✨ اشتراک طلایی", "shop:gold")],
        [btn("⛏ خرید معدن", "shop:mine")],
        [btn("🛒 آیتم‌های ویژه", "shop:items")],
        [back_btn("menu:main")],
    )


def diamond_packs_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn(
            f"💎 {settings.diamond_pack_small} الماس — {settings.diamond_pack_small_price:,} تومان",
            "buy:diamonds:small",
        )],
        [btn(
            f"💎 {settings.diamond_pack_medium} الماس (+۱۰٪) — {settings.diamond_pack_medium_price:,} تومان",
            "buy:diamonds:medium",
        )],
        [btn(
            f"💎 {settings.diamond_pack_large} الماس (+۲۰٪) — {settings.diamond_pack_large_price:,} تومان",
            "buy:diamonds:large",
        )],
        [btn(
            f"💎 {settings.diamond_pack_xlarge} الماس (+۳۵٪) — {settings.diamond_pack_xlarge_price:,} تومان",
            "buy:diamonds:xlarge",
        )],
        [back_btn("menu:shop")],
    )


def shop_items_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn(
            f"⚡ شارژ فوری انرژی — 💎 {settings.diamond_energy_refill}",
            "buy:item:energy",
        )],
        [btn(
            f"📈 ۲x درآمد ۲۴ ساعت — 💎 {settings.diamond_income_boost_24h}",
            "buy:item:boost",
        )],
        [btn(
            f"🛡 سپر ریسک — 💎 {settings.diamond_risk_shield}",
            "buy:item:shield",
        )],
        [btn(
            f"⏩ ریست کولداون کار — 💎 {settings.diamond_work_reset}",
            "buy:item:work_reset",
        )],
        [btn(
            f"⏩ ریست کولداون اکتشاف — 💎 {settings.diamond_explore_reset}",
            "buy:item:explore_reset",
        )],
        [back_btn("menu:shop")],
    )


def mine_shop_kb(has_mine: bool = False) -> InlineKeyboardMarkup:

    if has_mine:
        rows = [
            [btn(
                f"🪨 ارتقا به معدن سنگ — 💎 {settings.mine_stone_upgrade_diamonds}",
                "buy:mine:stone",
            )],
            [btn(
                f"🔩 ارتقا به معدن آهن — 💎 {settings.mine_iron_upgrade_diamonds}",
                "buy:mine:iron",
            )],
            [btn(
                f"🥇 ارتقا به معدن طلا — 💎 {settings.mine_gold_upgrade_diamonds}",
                "buy:mine:gold",
            )],
            [btn(
                f"💎 ارتقا به معدن کریستال — 💎 {settings.mine_crystal_upgrade_diamonds}",
                "buy:mine:crystal",
            )],
            [back_btn("menu:shop")],
        ]
    else:
        rows = [
            [btn(
                f"⛏ خرید معدن خاک — 💎 {settings.mine_buy_cost_diamonds}",
                "buy:mine:new",
            )],
            [back_btn("menu:shop")],
        ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_menu_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("🎮 شروع بازی", "help:start")],
        [btn("💼 کار و درآمد", "help:work")],
        [btn("🧭 اکتشاف", "help:explore")],
        [btn("🎯 مأموریت‌ها", "help:missions")],
        [btn("⛏ معدن", "help:mine")],
        [btn("⚔️ رویداد جمعی", "help:events")],
        [btn("💎 الماس و پریمیوم", "help:premium")],
        [btn("↔️ انتقال اِکو", "help:transfer")],
        [back_btn("menu:main")],
    )


def job_select_kb(current_level: int) -> InlineKeyboardMarkup:
    """انتخاب شغل با نمایش قفل برای سطوح پایین."""

    rows = []

    for key, config in JOB_CONFIG.items():
        locked = current_level < config["min_level"]
        label = (
            f"{config['icon']} {config['name']}"
            f" — ◈ {config['min']:,}-{config['max']:,}"
            + (f" 🔒 سطح {config['min_level']}" if locked else "")
        )
        rows.append([btn(label, f"job:select:{key}")])

    rows.append([cancel_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_action_kb(event_type: str) -> InlineKeyboardMarkup:
    """دکمه شرکت در رویداد بر اساس نوع."""

    action_map = {
        "crisis":  ("💰 کمک می‌کنم", "event:join:help"),
        "attack":  ("⚔️ دفاع می‌کنم", "event:join:defend"),
        "festival": ("🎉 شرکت می‌کنم", "event:join:participate"),
        "contest": ("🏆 شرکت می‌کنم", "event:join:participate"),
        "explore": ("🗺 اکتشاف می‌کنم", "event:join:participate"),
    }

    label, data = action_map.get(
        event_type,
        ("✅ شرکت می‌کنم", "event:join:participate"),
    )

    return kb(
        [btn(label, data)],
        [btn("📊 وضعیت رویداد", "event:status")],
    )


def transfer_confirm_kb(
    target_username: str,
    amount: int,
) -> InlineKeyboardMarkup:
    return kb(
        [confirm_btn(f"transfer:confirm:{target_username}:{amount}")],
        [cancel_btn()],
    )


def account_transfer_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("🔑 دریافت کد انتقال", "account:get_code")],
        [btn("📥 وارد کردن کد", "account:enter_code")],
        [back_btn("menu:main")],
    )


# ================================================================
# متون راهنما
# ================================================================

HELP_TEXTS = {
    "start": (
        "🎮 <b>شروع بازی</b>\n\n"
        "اِکو یه بازی دسته‌جمعی متنیه.\n"
        "هر گروه تلگرامی یه <b>شهر</b> مستقله.\n\n"
        "<b>چطور شروع کنم؟</b>\n"
        "۱. ربات رو به گروهت اضافه کن\n"
        "۲. اولین پیام رو بفرست — خودکار شهروند می‌شی\n"
        "۳. «کار» بنویس و اولین درآمدت رو بگیر\n\n"
        "<b>مهم‌ترین دستورات:</b>\n"
        "💼 کار — درآمد و XP\n"
        "🧭 اکتشاف — ماجراجویی تصادفی\n"
        "🎯 مأموریت — هدف‌های روزانه\n"
        "⛏ معدن — درآمد خودکار"
    ),

    "work": (
        "💼 <b>کار و درآمد</b>\n\n"
        "<b>چهار شغل موجود:</b>\n\n"
        "🔨 <b>کارگر ساده</b> (از سطح ۱)\n"
        f"درآمد: ◈ {settings.work_laborer_min:,}–{settings.work_laborer_max:,}\n"
        f"انرژی: {settings.work_laborer_energy} | بدون ریسک\n\n"
        "📦 <b>تاجر</b> (از سطح ۳)\n"
        f"درآمد: ◈ {settings.work_trader_min:,}–{settings.work_trader_max:,}\n"
        f"انرژی: {settings.work_trader_energy} | ریسک کم\n\n"
        "🔍 <b>کارآگاه</b> (از سطح ۵)\n"
        f"درآمد: ◈ {settings.work_detective_min:,}–{settings.work_detective_max:,}\n"
        f"انرژی: {settings.work_detective_energy} | ریسک متوسط\n\n"
        "💻 <b>هکر</b> (از سطح ۱۰)\n"
        f"درآمد: ◈ {settings.work_hacker_min:,}–{settings.work_hacker_max:,}\n"
        f"انرژی: {settings.work_hacker_energy} | ریسک بالا\n\n"
        f"<b>کولداون:</b> {settings.work_cooldown_seconds // 3600} ساعت\n"
        f"<b>حد روزانه:</b> {settings.work_max_daily} بار"
    ),

    "explore": (
        "🧭 <b>اکتشاف</b>\n\n"
        "هر اکتشاف یه ماجراجوییه — نمی‌دونی چی پیدا می‌کنی!\n\n"
        "<b>نتایج ممکن:</b>\n"
        f"😔 هیچی ({settings.explore_chance_nothing}٪)\n"
        f"💰 پول ({settings.explore_chance_money}٪)\n"
        f"⚠️ تله ({settings.explore_chance_trap}٪)\n"
        f"✨ کشف ویژه ({settings.explore_chance_special}٪)\n"
        f"💎 کشف افسانه‌ای ({settings.explore_chance_legendary}٪)\n\n"
        f"<b>انرژی:</b> {settings.explore_energy_cost}\n"
        f"<b>کولداون:</b> {settings.explore_cooldown_seconds // 3600} ساعت\n\n"
        "کشف‌های ویژه و افسانه‌ای در تاریخ شهر ثبت می‌شن!"
    ),

    "missions": (
        "🎯 <b>مأموریت‌ها</b>\n\n"
        "مأموریت‌ها هدف‌های مشخصی هستن که با انجامشون جایزه می‌گیری.\n\n"
        "<b>انواع مأموریت:</b>\n\n"
        "📅 <b>روزانه</b>\n"
        "هر روز تازه می‌شن — جایزه کوچیک ولی مطمئن\n\n"
        "📆 <b>هفتگی</b>\n"
        "هر هفته تازه می‌شن — جایزه بزرگ‌تر\n\n"
        "⚡ <b>ویژه</b>\n"
        "در رویدادهای خاص — جایزه استثنایی\n\n"
        "برای دیدن مأموریت‌هات «مأموریت» بنویس."
    ),

    "mine": (
        "⛏ <b>معدن</b>\n\n"
        "معدن هر ساعت اِکو تولید می‌کنه — حتی وقتی آنلاین نیستی!\n\n"
        "<b>سطوح معدن:</b>\n\n"
        f"🪨 معدن خاک — ◈ {settings.mine_dirt_hourly}/ساعت\n"
        f"   خرید: 💎 {settings.mine_buy_cost_diamonds}\n\n"
        f"🪨 معدن سنگ — ◈ {settings.mine_stone_hourly}/ساعت\n"
        f"   ارتقا: 💎 {settings.mine_stone_upgrade_diamonds}\n\n"
        f"🔩 معدن آهن — ◈ {settings.mine_iron_hourly}/ساعت\n"
        f"   ارتقا: 💎 {settings.mine_iron_upgrade_diamonds}\n\n"
        f"🥇 معدن طلا — ◈ {settings.mine_gold_hourly}/ساعت\n"
        f"   ارتقا: 💎 {settings.mine_gold_upgrade_diamonds}\n\n"
        f"💎 معدن کریستال — ◈ {settings.mine_crystal_hourly}/ساعت\n"
        f"   ارتقا: 💎 {settings.mine_crystal_upgrade_diamonds}\n\n"
        f"<b>حداکثر ذخیره:</b> {settings.mine_max_storage_hours} ساعت\n"
        "فراموش نکن برداشت کنی!"
    ),

    "events": (
        "⚔️ <b>رویداد جمعی</b>\n\n"
        "هر چند ساعت یه بار، ربات یه رویداد اعلام می‌کنه.\n"
        "همه شهروندا باید با هم کمک کنن!\n\n"
        "<b>انواع رویداد:</b>\n\n"
        "⚠️ <b>بحران اقتصادی</b>\n"
        "شهر به کمک مالی نیاز داره\n"
        "→ «کمک» بنویس\n\n"
        "⚔️ <b>حمله به شهر</b>\n"
        "شهر باید دفاع کنه\n"
        "→ «دفاع» بنویس\n\n"
        "🎉 <b>جشن شهر</b>\n"
        "همه ۲x XP می‌گیرن\n"
        "→ «شرکت» بنویس\n\n"
        "🏆 <b>رقابت بزرگ</b>\n"
        "بیشترین XP در ۲۴ ساعت\n"
        "→ فعال باش!\n\n"
        "🗺 <b>کشف مشترک</b>\n"
        "با هم یه منطقه رو کشف کنید\n"
        "→ «شرکت» بنویس"
    ),

    "premium": (
        "💎 <b>الماس و پریمیوم</b>\n\n"
        "الماس واحد پریمیوم اِکوئه.\n"
        "با الماس می‌تونی بازی رو سریع‌تر پیش ببری.\n\n"
        "<b>با الماس چی می‌شه خرید؟</b>\n\n"
        f"⚡ شارژ فوری انرژی — 💎 {settings.diamond_energy_refill}\n"
        f"📈 ۲x درآمد ۲۴ ساعت — 💎 {settings.diamond_income_boost_24h}\n"
        f"🛡 سپر ریسک — 💎 {settings.diamond_risk_shield}\n"
        f"⛏ معدن خاک — 💎 {settings.mine_buy_cost_diamonds}\n\n"
        "<b>اشتراک طلایی</b>\n"
        f"✨ {settings.gold_subscription_price:,} تومان در ماه\n"
        f"• {settings.gold_subscription_daily_diamonds} الماس رایگان روزانه\n"
        f"• {settings.gold_subscription_income_bonus}٪ درآمد بیشتر\n"
        "• شارژ انرژی روزانه رایگان\n"
        "• نشان ویژه ✨\n\n"
        "برای خرید «فروشگاه» بنویس."
    ),

    "transfer": (
        "↔️ <b>انتقال اِکو</b>\n\n"
        "می‌تونی اِکو رو به بازیکن دیگه‌ای بدی.\n\n"
        "<b>انتقال داخل شهر:</b>\n"
        "«انتقال @نام_کاربری مقدار» بنویس\n"
        "مثال: انتقال @ali 5000\n\n"
        "<b>انتقال بین شهرها:</b>\n"
        f"مالیات انتقال: {settings.city_transfer_tax}٪\n"
        f"حداقل مقدار: ◈ {GameConstants.MIN_TRANSFER_AMOUNT:,}\n\n"
        "<b>انتقال اکانت:</b>\n"
        "می‌تونی اکانت بازیت رو به کاربر دیگه‌ای انتقال بدی.\n"
        f"کارمزد: {settings.account_transfer_fee}٪ از ارزش اعلام‌شده"
    ),
}


# ================================================================
# هندلر /start در ربات خصوصی
# ================================================================

@private_router.message(CommandStart())
async def private_start(
    message: Message,
    bot: Bot,
) -> None:

    if not message.from_user:
        return

    bot_info = await bot.get_me()

    add_url = f"https://t.me/{bot_info.username}?startgroup=echo"

    keyboard = kb(
        [url_btn("➕ اضافه کردن به گروه", add_url)],
        [btn("🎮 شروع آموزش", "tutorial:start")],
        [btn("❓ راهنما", "menu:help")],
        [btn("💎 فروشگاه", "menu:shop")],
    )

    await safe_send(
        message,
        (
            "〰️ <b>اِکو</b>\n\n"
            "بنویس. بساز. حکومت کن.\n\n"
            "اِکو یه بازی دسته‌جمعی متنیه.\n"
            "هر گروه یه شهره.\n"
            "هر پیام یه آجر.\n"
            "با هم یه شهر می‌سازیم.\n\n"
            "برای شروع، ربات رو به گروهت اضافه کن."
        ),
        keyboard,
    )


# ================================================================
# هندلر /help در ربات خصوصی
# ================================================================

@private_router.message(Command("help"))
async def private_help_command(
    message: Message,
) -> None:

    await safe_send(
        message,
        "❓ <b>راهنمای اِکو</b>\n\nکدوم بخش رو می‌خوای بدونی؟",
        help_menu_kb(),
    )


# ================================================================
# هندلر پیام‌های متنی ربات خصوصی
# ================================================================

@private_router.message(F.text)
async def private_text_handler(
    message: Message,
    bot: Bot,
) -> None:

    if not message.from_user:
        return

    text = (message.text or "").strip()

    if not text:
        return

    user_id = message.from_user.id

    # شهر پیش‌فرض برای ربات خصوصی
    # کاربر باید از منوی «شهرهام» انتخاب کنه
    # فعلاً از آخرین شهر فعال استفاده می‌کنیم

    async with get_session() as session:

        await get_or_create_user(
            session,
            user_id,
            username=message.from_user.username,
            display_name=(
                message.from_user.first_name
                or message.from_user.username
                or str(user_id)
            ),
        )

        # پیدا کردن آخرین شهر فعال کاربر
        member_res = await session.execute(
            select(CityMember, City)
            .join(City, City.id == CityMember.city_id)
            .where(
                CityMember.user_id == user_id,
                CityMember.is_active.is_(True),
                City.is_active.is_(True),
            )
            .order_by(CityMember.last_active_at.desc())
            .limit(1)
        )
        row = member_res.first()

    if row is None:

        # کاربر هنوز در هیچ شهری نیست
        bot_info = await bot.get_me()
        add_url = f"https://t.me/{bot_info.username}?startgroup=echo"

        await safe_send(
            message,
            (
                "🏙 <b>هنوز در هیچ شهری نیستی</b>\n\n"
                "برای بازی باید ربات رو به یه گروه اضافه کنی.\n"
                "بعد توی گروه یه پیام بده — خودکار شهروند می‌شی."
            ),
            kb([url_btn("➕ اضافه کردن به گروه", add_url)]),
        )
        return

    member, city = row

    context = GameContext(
        user_id=user_id,
        city_id=city.id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
        is_group=False,
        is_private=True,
        username=message.from_user.username or "",
        display_name=(
            message.from_user.first_name
            or message.from_user.username
            or str(user_id)
        ),
    )

    engine = get_game_engine()
    response = await engine.process_message(context)

    if response.is_silent:
        return

    await render_response(response, message, bot)


# ================================================================
# هندلر کال‌بک‌های ربات خصوصی
# ================================================================

@private_router.callback_query()
async def private_callback_handler(
    callback: CallbackQuery,
    bot: Bot,
) -> None:

    await handle_callback(callback, bot, is_group=False)


# ================================================================
# هندلر عضویت ربات در گروه
# ================================================================

@group_router.my_chat_member()
async def group_membership_handler(
    event: ChatMemberUpdated,
    bot: Bot,
) -> None:

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    added = old_status in {"left", "kicked"} and new_status in {"member", "administrator"}
    removed = old_status in {"member", "administrator"} and new_status in {"left", "kicked"}

    # ━━━ ربات حذف شد ━━━
    if removed:
        try:
            async with get_session() as session:
                await deactivate_city(session, event.chat.id)
            logger.info("شهر غیرفعال شد: chat_id=%s", event.chat.id)
        except Exception:
            logger.exception("خطا در غیرفعال کردن شهر: chat_id=%s", event.chat.id)
        return

    # ━━━ ربات اضافه شد ━━━
    if not added:
        return

    actor = event.from_user
    actor_id = actor.id if actor else None

    try:
        async with get_session() as session:

            if actor:
                await get_or_create_user(
                    session,
                    actor.id,
                    username=actor.username,
                    display_name=(
                        actor.first_name
                        or actor.username
                        or str(actor.id)
                    ),
                )

            city = await get_or_restore_city(
                session,
                telegram_chat_id=event.chat.id,
                name=event.chat.title or "شهر اِکو",
                username=event.chat.username,
                owner_user_id=actor_id,
            )

            population = await get_city_population(session, city.id)
            city_name = city.custom_name or city.name

        keyboard = kb(
            [btn("🎮 شروع بازی", "tutorial:start")],
            [btn("❓ راهنما", "menu:help")],
        )

        await bot.send_message(
            event.chat.id,
            (
                f"〰️ <b>اِکو فعال شد!</b>\n\n"
                f"شهر <b>{escape_html(city_name)}</b> در دنیای اِکو ثبت شد.\n\n"
                f"از این لحظه هر پیامی که توی این گروه بفرستید،\n"
                f"یه آجر به شهر اضافه می‌شه.\n\n"
                f"با هم این شهر رو می‌سازیم.\n\n"
                f"<i>بنویس. بساز. حکومت کن.</i>"
            ),
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        logger.info(
            "شهر جدید فعال شد: chat_id=%s name=%s population=%s",
            event.chat.id, city_name, population,
        )

    except Exception:
        logger.exception("خطا در فعال‌سازی شهر: chat_id=%s", event.chat.id)


# ================================================================
# هندلر پیام‌های گروه
# ================================================================

@group_router.message(F.text)
async def group_message_handler(
    message: Message,
    bot: Bot,
) -> None:

    if not message.from_user:
        return

    text = (message.text or "").strip()
    if not text:
        return

    user_id = message.from_user.id

    try:
        async with get_session() as session:

            city = await get_city_by_chat(session, message.chat.id)

            if city is None:
                city = await get_or_restore_city(
                    session,
                    telegram_chat_id=message.chat.id,
                    name=message.chat.title or "شهر اِکو",
                    username=message.chat.username,
                    owner_user_id=user_id,
                )

            if not city.is_active:
                return

            city_id = city.id

        context = GameContext(
            user_id=user_id,
            city_id=city_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=text,
            is_group=True,
            is_private=False,
            username=message.from_user.username or "",
            display_name=(
                message.from_user.first_name
                or message.from_user.username
                or str(user_id)
            ),
            reply_to_message_id=(
                message.reply_to_message.message_id
                if message.reply_to_message else None
            ),
        )

        # ابتدا بررسی می‌کنیم دستور بازی است یا پیام معمولی
        normalized = normalize_text(text)
        intent = detect_intent(normalized)

        if intent == IntentType.NO_INTENT:
            # پیام معمولی → اِکوی خودکار
            response = await process_group_message(context)
        else:
            # دستور بازی → پردازش کامل
            engine = get_game_engine()
            response = await engine.process_message(context)

        if response.is_silent:
            return

        await render_response(response, message, bot)

    except Exception:
        logger.exception(
            "خطا در پردازش پیام گروه: user=%s chat=%s text=%r",
            message.from_user.id,
            message.chat.id,
            text[:50],
        )


# ================================================================
# هندلر کال‌بک‌های گروه
# ================================================================

@group_router.callback_query()
async def group_callback_handler(
    callback: CallbackQuery,
    bot: Bot,
) -> None:

    await handle_callback(callback, bot, is_group=True)


# ================================================================
# پردازشگر مرکزی کال‌بک
# ================================================================

async def handle_callback(
    callback: CallbackQuery,
    bot: Bot,
    is_group: bool = False,
) -> None:

    if not callback.message or not callback.from_user:
        await callback.answer()
        return

    data = callback.data or ""
    user_id = callback.from_user.id
    message = callback.message

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # بستن
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data == "ui:close":
        await callback.answer()
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # لغو
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data == "ui:cancel":
        await callback.answer("لغو شد.")
        await safe_edit(message, "❌ لغو شد.")
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # آموزش
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data == "tutorial:start" or data.startswith("tutorial:step"):

        await callback.answer()

        city_id = await get_user_active_city(user_id)

        if city_id is None:
            await callback.answer("اول ربات رو به گروهت اضافه کن!", show_alert=True)
            return

        context = _make_context(
            user_id=user_id,
            city_id=city_id,
            chat_id=message.chat.id,
            text="آموزش",
            is_private=not is_group,
            from_user=callback.from_user,
        )

        engine = get_game_engine()
        response = await engine.process_message(context)
        await render_response(response, message, bot, edit=True)
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # منوها
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data == "menu:main":
        await callback.answer()
        await show_main_menu(callback, bot)
        return

    if data == "menu:bank":
        await callback.answer()
        await safe_edit(
            message,
            "💰 <b>بانک</b>\n\nمدیریت پول نقد و بانک:",
            bank_menu_kb(),
        )
        return

    if data == "menu:shop":
        await callback.answer()
        await safe_edit(
            message,
            (
                "💎 <b>فروشگاه اِکو</b>\n\n"
                "با الماس می‌تونی بازی رو سریع‌تر پیش ببری.\n"
                "کدوم بخش رو می‌خوای؟"
            ),
            shop_menu_kb(),
        )
        return

    if data == "menu:help":
        await callback.answer()
        await safe_edit(
            message,
            "❓ <b>راهنمای اِکو</b>\n\nکدوم بخش رو می‌خوای بدونی؟",
            help_menu_kb(),
        )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # راهنما
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data.startswith("help:"):
        topic = data.split(":", 1)[1]
        await callback.answer()
        text = HELP_TEXTS.get(topic)
        if text:
            await safe_edit(
                message,
                text,
                kb(
                    [back_btn("menu:help")],
                    [close_btn()],
                ),
            )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # اکشن‌های بازی
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data.startswith("action:"):
        action = data.split(":", 1)[1]
        await callback.answer()

        city_id = await get_user_active_city(user_id)
        if city_id is None:
            await callback.answer("اول ربات رو به گروهت اضافه کن!", show_alert=True)
            return

        text_map = {
            "work":     "کار",
            "explore":  "اکتشاف",
            "missions": "مأموریت",
            "profile":  "پروفایل",
            "city":     "شهر",
            "rank":     "رتبه",
            "mine":     "معدن",
            "market":   "بازار",
            "guild":    "گیلد",
            "history":  "تاریخ شهر",
            "transfer": "انتقال",
            "deposit":  "واریز",
            "withdraw": "برداشت از بانک",
        }

        text = text_map.get(action, action)

        context = _make_context(
            user_id=user_id,
            city_id=city_id,
            chat_id=message.chat.id,
            text=text,
            is_private=not is_group,
            from_user=callback.from_user,
        )

        engine = get_game_engine()
        response = await engine.process_message(context)
        await render_response(response, message, bot, edit=True)
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # برداشت معدن
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data == "mine_collect":
        await callback.answer()

        city_id = await get_user_active_city(user_id)
        if city_id is None:
            await callback.answer("شهر پیدا نشد!", show_alert=True)
            return

        context = _make_context(
            user_id=user_id,
            city_id=city_id,
            chat_id=message.chat.id,
            text="برداشت از معدن",
            is_private=not is_group,
            from_user=callback.from_user,
        )

        engine = get_game_engine()
        response = await engine.handle_mine_collect(context)
        await render_response(response, message, bot, edit=True)
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # رویداد جمعی
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data.startswith("event:join:"):
        action_type = data.split(":")[-1]

        city_id = await get_city_from_chat(message.chat.id)
        if city_id is None:
            await callback.answer("شهر پیدا نشد!", show_alert=True)
            return

        action_text_map = {
            "help":       "کمک",
            "defend":     "دفاع",
            "participate": "شرکت",
        }

        text = action_text_map.get(action_type, "شرکت")

        context = _make_context(
            user_id=user_id,
            city_id=city_id,
            chat_id=message.chat.id,
            text=text,
            is_private=False,
            from_user=callback.from_user,
        )

        engine = get_game_engine()
        response = await engine.process_message(context)

        await callback.answer()
        await render_response(response, message, bot, edit=False)
        return

    if data == "event:status":
        await callback.answer()

        city_id = await get_city_from_chat(message.chat.id)
        if city_id is None:
            await callback.answer("شهر پیدا نشد!", show_alert=True)
            return

        async with get_session() as session:
            event = await get_active_event(session, city_id)

        if event is None:
            await callback.answer("رویداد فعالی نیست.", show_alert=True)
            return

        pct = int((event.current_value / max(event.target_value, 1)) * 100)
        fill = int(pct / 10)
        bar = "█" * fill + "░" * (10 - fill)

        await callback.answer(
            f"{event.title}\n"
            f"[{bar}] {pct}٪\n"
            f"{event.current_value:,}/{event.target_value:,}",
            show_alert=True,
        )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # انتخاب شغل
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data.startswith("job:select:"):
        job_key = data.split(":")[-1]
        await callback.answer()

        city_id = await get_user_active_city(user_id)
        if city_id is None:
            return

        context = _make_context(
            user_id=user_id,
            city_id=city_id,
            chat_id=message.chat.id,
            text=str(list(JOB_CONFIG.keys()).index(job_key) + 1),
            is_private=not is_group,
            from_user=callback.from_user,
        )

        engine = get_game_engine()
        response = await engine.process_message(context)
        await render_response(response, message, bot, edit=True)
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # فروشگاه
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data == "shop:diamonds":
        await callback.answer()
        await safe_edit(
            message,
            (
                "💎 <b>خرید الماس</b>\n\n"
                "بسته مورد نظرت رو انتخاب کن:\n\n"
                f"• {settings.diamond_pack_small} الماس — "
                f"{settings.diamond_pack_small_price:,} تومان\n"
                f"• {settings.diamond_pack_medium} الماس (+۱۰٪) — "
                f"{settings.diamond_pack_medium_price:,} تومان\n"
                f"• {settings.diamond_pack_large} الماس (+۲۰٪) — "
                f"{settings.diamond_pack_large_price:,} تومان\n"
                f"• {settings.diamond_pack_xlarge} الماس (+۳۵٪) — "
                f"{settings.diamond_pack_xlarge_price:,} تومان"
            ),
            diamond_packs_kb(),
        )
        return

    if data == "shop:items":
        await callback.answer()
        await safe_edit(
            message,
            (
                "🛒 <b>آیتم‌های ویژه</b>\n\n"
                "با الماس می‌تونی آیتم‌های فوری بخری:"
            ),
            shop_items_kb(),
        )
        return

    if data == "shop:mine":
        await callback.answer()

        async with get_session() as session:
            mine = await get_or_create_mine(session, user_id)

        await safe_edit(
            message,
            (
                "⛏ <b>معدن</b>\n\n"
                + (
                    f"معدن فعلی: {GameConstants.MINE_LEVELS.get(mine.level, 'معدن')}\n"
                    "برای ارتقا، سطح بالاتر رو انتخاب کن:"
                    if mine else
                    "هنوز معدن نداری.\nیه معدن بخر و شروع کن به جمع کردن اِکو!"
                )
            ),
            mine_shop_kb(has_mine=mine is not None),
        )
        return

    if data == "shop:gold":
        await callback.answer()
        await safe_edit(
            message,
            (
                "✨ <b>اشتراک طلایی</b>\n\n"
                f"ماهی {settings.gold_subscription_price:,} تومان\n\n"
                f"✅ {settings.gold_subscription_daily_diamonds} الماس رایگان هر روز\n"
                f"✅ {settings.gold_subscription_income_bonus}٪ درآمد بیشتر از کار\n"
                f"✅ شارژ انرژی رایگان روزانه\n"
                f"✅ نشان ویژه ✨ کنار اسمت\n"
                f"✅ اولویت در رویدادها\n\n"
                "برای خرید با پشتیبانی تماس بگیر."
            ),
            kb(
                [back_btn("menu:shop")],
                [close_btn()],
            ),
        )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # خرید آیتم
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    if data.startswith("buy:item:"):
        item = data.split(":")[-1]
        await callback.answer()
        await handle_item_purchase(callback, item, bot)
        return

    if data.startswith("buy:mine:"):
        mine_action = data.split(":")[-1]
        await callback.answer()
        await handle_mine_purchase(callback, mine_action, bot)
        return

    if data.startswith("buy:diamonds:"):
        await callback.answer(
            "برای خرید الماس با پشتیبانی تماس بگیر.",
            show_alert=True,
        )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━
    # پیش‌فرض
    # ━━━━━━━━━━━━━━━━━━━━━━━━
    await callback.answer("این گزینه هنوز فعال نیست.", show_alert=True)


# ================================================================
# خرید آیتم با الماس
# ================================================================

async def handle_item_purchase(
    callback: CallbackQuery,
    item: str,
    bot: Bot,
) -> None:

    user_id = callback.from_user.id
    message = callback.message

    item_config = {
        "energy": {
            "cost": settings.diamond_energy_refill,
            "name": "شارژ فوری انرژی",
            "action": "energy_refill",
        },
        "boost": {
            "cost": settings.diamond_income_boost_24h,
            "name": "۲x درآمد ۲۴ ساعت",
            "action": "income_boost",
        },
        "shield": {
            "cost": settings.diamond_risk_shield,
            "name": "سپر ریسک",
            "action": "risk_shield",
        },
        "work_reset": {
            "cost": settings.diamond_work_reset,
            "name": "ریست کولداون کار",
            "action": "work_cooldown_reset",
        },
        "explore_reset": {
            "cost": settings.diamond_explore_reset,
            "name": "ریست کولداون اکتشاف",
            "action": "explore_cooldown_reset",
        },
    }

    config = item_config.get(item)
    if not config:
        await callback.answer("آیتم پیدا نشد.", show_alert=True)
        return

    city_id = await get_user_active_city(user_id)

    try:
        async with get_session() as session:

            await spend_diamonds(session, user_id, config["cost"])

            action = config["action"]

            if action == "energy_refill" and city_id:
                member_res = await session.execute(
                    select(CityMember).where(
                        CityMember.user_id == user_id,
                        CityMember.city_id == city_id,
                    )
                )
                member = member_res.scalar_one_or_none()
                if member:
                    member.energy = settings.max_energy
                    await session.flush()

            elif action == "income_boost":
                await set_income_boost(user_id, ttl_seconds=86_400)

            elif action == "risk_shield":
                await set_risk_shield(user_id)

            elif action == "work_cooldown_reset" and city_id:
                from database import redis_client, RedisKeys
                await redis_client.delete(
                    RedisKeys.cooldown(user_id, city_id, "work")
                )

            elif action == "explore_cooldown_reset" and city_id:
                from database import redis_client, RedisKeys
                await redis_client.delete(
                    RedisKeys.cooldown(user_id, city_id, "explore")
                )

        await safe_edit(
            message,
            (
                f"✅ <b>{config['name']}</b> فعال شد!\n\n"
                f"💎 {config['cost']} الماس کم شد."
            ),
            kb([back_btn("menu:shop")]),
        )

    except InsufficientDiamondsError:
        await callback.answer(
            f"الماس کافی نداری. این آیتم {config['cost']} الماس نیاز داره.",
            show_alert=True,
        )


# ================================================================
# خرید / ارتقا معدن
# ================================================================

async def handle_mine_purchase(
    callback: CallbackQuery,
    mine_action: str,
    bot: Bot,
) -> None:

    user_id = callback.from_user.id
    message = callback.message

    upgrade_map = {
        "new":     (settings.mine_buy_cost_diamonds, None, MineLevel.DIRT.value),
        "stone":   (settings.mine_stone_upgrade_diamonds, MineLevel.DIRT.value, MineLevel.STONE.value),
        "iron":    (settings.mine_iron_upgrade_diamonds, MineLevel.STONE.value, MineLevel.IRON.value),
        "gold":    (settings.mine_gold_upgrade_diamonds, MineLevel.IRON.value, MineLevel.GOLD.value),
        "crystal": (settings.mine_crystal_upgrade_diamonds, MineLevel.GOLD.value, MineLevel.CRYSTAL.value),
    }

    config = upgrade_map.get(mine_action)
    if not config:
        await callback.answer("گزینه نامعتبر.", show_alert=True)
        return

    cost, required_level, new_level = config

    try:
        async with get_session() as session:

            await spend_diamonds(session, user_id, cost)

            mine_res = await session.execute(
                select(UserMine).where(UserMine.user_id == user_id)
            )
            mine = mine_res.scalar_one_or_none()

            if mine_action == "new":
                if mine is not None:
                    await callback.answer("قبلاً معدن داری!", show_alert=True)
                    return

                from database import utcnow
                new_mine = UserMine(
                    user_id=user_id,
                    level=MineLevel.DIRT.value,
                    accumulated_eco=0,
                    last_calculated_at=utcnow(),
                )
                session.add(new_mine)
                await session.flush()

            else:
                if mine is None:
                    await callback.answer("معدن نداری!", show_alert=True)
                    return

                if mine.level != required_level:
                    await callback.answer(
                        f"برای این ارتقا باید اول به {GameConstants.MINE_LEVELS.get(required_level, required_level)} برسی.",
                        show_alert=True,
                    )
                    return

                mine.level = new_level
                await session.flush()

        mine_name = GameConstants.MINE_LEVELS.get(new_level, "معدن")
        hourly = settings.mine_hourly_production(new_level)

        await safe_edit(
            message,
            (
                f"⛏ <b>{mine_name} فعال شد!</b>\n\n"
                f"تولید: ◈ {hourly:,} در ساعت\n"
                f"💎 {cost} الماس کم شد.\n\n"
                f"برای برداشت «معدن» بنویس."
            ),
            kb([back_btn("menu:shop")]),
        )

    except InsufficientDiamondsError:
        await callback.answer(
            f"الماس کافی نداری. این ارتقا {cost} الماس نیاز داره.",
            show_alert=True,
        )


# ================================================================
# رندر پاسخ بازی
# ================================================================

async def render_response(
    response: GameResponse,
    message: Message,
    bot: Bot,
    edit: bool = False,
) -> None:

    if response is None or response.is_silent:
        return

    if not response.text:
        return

    # ساخت کیبورد از اکشن‌ها
    keyboard = None
    if response.requires_ui and response.actions:
        keyboard = build_action_keyboard(response.actions)

    # اعلامیه عمومی در گروه
    if response.public_announcement and message.chat.type in (
        ChatType.GROUP, ChatType.SUPERGROUP
    ):
        await safe_send(message, response.public_announcement)

    # پاسخ اصلی
    if edit:
        success = await safe_edit(message, response.text, keyboard)
        if not success:
            await safe_send(message, response.text, keyboard)
    else:
        await safe_send(message, response.text, keyboard)


def build_action_keyboard(
    actions: list[ActionButton],
) -> Optional[InlineKeyboardMarkup]:

    if not actions:
        return None

    rows = []
    for action in actions:
        rows.append([
            btn(action.label, f"action_btn:{action.action}")
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ================================================================
# نمایش منوی اصلی
# ================================================================

async def show_main_menu(
    callback: CallbackQuery,
    bot: Bot,
) -> None:

    user_id = callback.from_user.id
    message = callback.message

    city_id = await get_user_active_city(user_id)

    city_name = "شهر"
    has_mine = False

    if city_id:
        async with get_session() as session:
            city_res = await session.execute(
                select(City).where(City.id == city_id)
            )
            city = city_res.scalar_one_or_none()
            if city:
                city_name = city.custom_name or city.name

            mine = await get_or_create_mine(session, user_id)
            has_mine = mine is not None

    await safe_edit(
        message,
        (
            f"〰️ <b>اِکو</b> — <b>{escape_html(city_name)}</b>\n\n"
            "بنویس. بساز. حکومت کن.\n\n"
            "کدوم بخش رو می‌خوای؟"
        ),
        main_menu_kb(has_mine=has_mine, city_name=city_name),
    )


# ================================================================
# کمک‌کننده‌ها
# ================================================================

async def get_user_active_city(user_id: int) -> Optional[int]:
    """آخرین شهر فعال کاربر."""

    async with get_session() as session:

        result = await session.execute(
            select(CityMember.city_id)
            .join(City, City.id == CityMember.city_id)
            .where(
                CityMember.user_id == user_id,
                CityMember.is_active.is_(True),
                City.is_active.is_(True),
            )
            .order_by(CityMember.last_active_at.desc())
            .limit(1)
        )

        row = result.first()
        return row[0] if row else None


async def get_city_from_chat(chat_id: int) -> Optional[int]:
    """شناسه شهر از چت گروه."""

    async with get_session() as session:
        city = await get_city_by_chat(session, chat_id)
        return city.id if city else None


def _make_context(
    user_id: int,
    city_id: int,
    chat_id: int,
    text: str,
    is_private: bool,
    from_user: Any,
) -> GameContext:

    return GameContext(
        user_id=user_id,
        city_id=city_id,
        chat_id=chat_id,
        message_id=0,
        text=text,
        is_group=not is_private,
        is_private=is_private,
        username=getattr(from_user, "username", "") or "",
        display_name=(
            getattr(from_user, "first_name", "")
            or getattr(from_user, "username", "")
            or str(user_id)
        ),
    )


# ================================================================
# ارسال امن پیام
# ================================================================

async def safe_send(
    message: Message,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:

    try:
        return await message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.warning("خطا در ارسال پیام: %s", exc)
        return None
    except TelegramForbiddenError:
        logger.warning("ربات در این چت مسدود است.")
        return None
    except Exception:
        logger.exception("خطای غیرمنتظره در ارسال پیام.")
        return None


async def safe_edit(
    message: Message,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> bool:

    try:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return True
    except TelegramBadRequest:
        return False
    except Exception:
        logger.exception("خطا در ویرایش پیام.")
        return False


async def safe_send_to_chat(
    bot: Bot,
    chat_id: int,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:

    try:
        return await bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramForbiddenError:
        logger.warning("ربات در چت %s مسدود است.", chat_id)
        return None
    except TelegramBadRequest as exc:
        logger.warning("خطا در ارسال به چت %s: %s", chat_id, exc)
        return None
    except Exception:
        logger.exception("خطای غیرمنتظره در ارسال به چت %s.", chat_id)
        return None


async def safe_edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> bool:

    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return True
    except TelegramBadRequest:
        return False
    except Exception:
        logger.exception("خطا در ویرایش پیام %s در چت %s.", message_id, chat_id)
        return False


def escape_html(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ================================================================
# تنظیم دستورات ربات
# ================================================================

async def setup_bot_commands(bot: Bot) -> None:

    await bot.set_my_commands([
        BotCommand(command="start", description="شروع اِکو"),
        BotCommand(command="help",  description="راهنمای بازی"),
    ])


# ================================================================
# ثبت هندلرها
# ================================================================

def register_handlers(dp: Dispatcher) -> None:

    dp.include_router(group_router)
    dp.include_router(private_router)


# ================================================================
# ارسال رویداد عمومی (برای تسک پس‌زمینه)
# ================================================================

async def send_event_announcement(
    bot: Bot,
    chat_id: int,
    event_data: dict,
) -> Optional[int]:
    """
    رویداد جمعی را در گروه اعلام می‌کند.
    شناسه پیام برمی‌گرداند (برای به‌روزرسانی بعدی).
    """

    event_type = event_data.get("event_type", "")
    keyboard = event_action_kb(event_type)

    msg = await safe_send_to_chat(
        bot,
        chat_id,
        event_data.get("message", "رویداد جدید!"),
        keyboard,
    )

    return msg.message_id if msg else None


async def send_event_result(
    bot: Bot,
    chat_id: int,
    result_data: dict,
) -> None:
    """نتیجه رویداد جمعی را در گروه اعلام می‌کند."""

    await safe_send_to_chat(
        bot,
        chat_id,
        result_data.get("message", "رویداد پایان یافت."),
    )


# ================================================================
# صادرات
# ================================================================

__all__ = [
    "private_router",
    "group_router",
    "register_handlers",
    "setup_bot_commands",
    "safe_send",
    "safe_edit",
    "safe_send_to_chat",
    "safe_edit_message",
    "send_event_announcement",
    "send_event_result",
    "escape_html",
    "kb",
    "btn",
    "url_btn",
    "back_btn",
    "close_btn",
    "main_menu_kb",
    "event_action_kb",
]
