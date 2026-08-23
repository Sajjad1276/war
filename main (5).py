# ================================================================
# اِکو — main.py
# نقطه ورود برنامه و تسک‌های پس‌زمینه
# ================================================================
#
# بنویس. بساز. حکومت کن.
#
# مسئولیت این فایل:
#   - راه‌اندازی ربات
#   - ثبت هندلرها
#   - تسک‌های پس‌زمینه:
#       * بررسی و اجرای رویداد جمعی
#       * پایان رویدادهای منقضی
#       * ریکاوری انرژی
#       * ریست روزانه مأموریت‌ها
#       * اعلام رتبه‌بندی هفتگی
#       * محاسبه تولید معادن
#       * الماس روزانه اشتراک طلایی
# ================================================================

from __future__ import annotations

import asyncio
import logging
import random
import signal
import sys

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy import select, update

from config import settings, GameConstants
from database import (
    init_database,
    database_health,
    redis_health,
    close_database,
    close_redis,
    get_session,
    City,
    CityEvent,
    CityMember,
    User,
    UserStats,
    UserSubscription,
    Mission,
    MissionProgress,
    MissionStatus,
    MissionType,
    EventStatus,
    get_city_population,
    get_city_leaderboard,
    add_city_history,
    add_diamonds,
    restore_energy_for_city,
    redis_client,
    RedisKeys,
)

from game import (
    get_game_engine,
    create_random_city_event,
    finalize_event,
)

from handlers import (
    register_handlers,
    setup_bot_commands,
    send_event_announcement,
    send_event_result,
    safe_send_to_chat,
    escape_html,
    kb,
    btn,
)


# ================================================================
# لاگ
# ================================================================

LOG_FORMAT  = "%(asctime)s | %(levelname)-8s | echo | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("echo.main")


def configure_logging() -> None:

    debug = bool(getattr(settings, "debug", False))

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stdout,
        force=True,
    )

    for noisy in ("aiogram", "aiohttp", "asyncio", "sqlalchemy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ================================================================
# ابزار زمان
# ================================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ================================================================
# مدیریت تسک‌های پس‌زمینه
# ================================================================

_background_tasks: set[asyncio.Task] = set()


def spawn(coro: Any) -> asyncio.Task:
    """یه تسک پس‌زمینه می‌سازد و ردیابی می‌کند."""

    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def cancel_all_tasks() -> None:

    if not _background_tasks:
        return

    logger.info("لغو %d تسک پس‌زمینه...", len(_background_tasks))

    tasks = list(_background_tasks)
    for task in tasks:
        if not task.done():
            task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    _background_tasks.clear()

    logger.info("همه تسک‌ها لغو شدند.")


# ================================================================
# تسک: رویداد جمعی
# ================================================================

async def task_event_manager(bot: Bot) -> None:
    """
    هر X دقیقه:
      ۱. رویدادهای منقضی را پایان می‌دهد
      ۲. اگه شهری رویداد نداره و وقتشه، رویداد جدید می‌سازد
    """

    interval = settings.event_check_interval_seconds
    logger.info("تسک رویداد شروع شد — فاصله: %ds", interval)

    while True:

        try:
            await asyncio.sleep(interval)
            await _check_and_finalize_events(bot)
            await _create_new_events(bot)

        except asyncio.CancelledError:
            logger.info("تسک رویداد لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک رویداد.")
            await asyncio.sleep(60)


async def _check_and_finalize_events(bot: Bot) -> None:
    """رویدادهای منقضی را پایان می‌دهد."""

    now = utcnow()

    async with get_session() as session:

        result = await session.execute(
            select(CityEvent).where(
                CityEvent.status == EventStatus.ACTIVE.value,
                CityEvent.ends_at <= now,
            )
        )

        expired_events = result.scalars().all()

    for event in expired_events:

        try:
            result_data = await finalize_event(event.id, event.city_id)

            if result_data is None:
                continue

            # پیدا کردن چت گروه
            async with get_session() as session:
                city_res = await session.execute(
                    select(City).where(City.id == event.city_id)
                )
                city = city_res.scalar_one_or_none()

            if city:
                await send_event_result(bot, city.telegram_chat_id, result_data)

            logger.info(
                "رویداد %d پایان یافت — شهر %d — موفق: %s",
                event.id, event.city_id, result_data.get("success"),
            )

        except Exception:
            logger.exception("خطا در پایان رویداد %d.", event.id)


async def _create_new_events(bot: Bot) -> None:
    """
    برای شهرهایی که رویداد ندارن و زمانشه،
    رویداد جدید می‌سازد.
    """

    now = utcnow()
    min_interval = timedelta(seconds=settings.event_interval_min_seconds)
    max_interval = timedelta(seconds=settings.event_interval_max_seconds)

    async with get_session() as session:

        result = await session.execute(
            select(City).where(
                City.is_active.is_(True),
            )
        )

        cities = result.scalars().all()

    for city in cities:

        try:
            # بررسی آیا رویداد فعال داره
            async with get_session() as session:
                event = await session.execute(
                    select(CityEvent).where(
                        CityEvent.city_id == city.id,
                        CityEvent.status == EventStatus.ACTIVE.value,
                        CityEvent.ends_at > now,
                    )
                )
                active = event.scalar_one_or_none()

            if active:
                continue

            # بررسی زمان آخرین رویداد
            last_event = city.last_event_at

            if last_event:
                interval = timedelta(
                    seconds=random.randint(
                        settings.event_interval_min_seconds,
                        settings.event_interval_max_seconds,
                    )
                )

                if now - last_event < interval:
                    continue

            # بررسی جمعیت کافی
            async with get_session() as session:
                population = await get_city_population(session, city.id)

            if population < GameConstants.MIN_POPULATION_FOR_EVENTS:
                continue

            # ساخت رویداد جدید
            event_data = await create_random_city_event(city.id, population)

            if event_data is None:
                continue

            # ارسال در گروه
            message_id = await send_event_announcement(
                bot,
                city.telegram_chat_id,
                event_data,
            )

            # ذخیره شناسه پیام
            if message_id:
                async with get_session() as session:
                    await session.execute(
                        update(CityEvent)
                        .where(CityEvent.id == event_data["event_id"])
                        .values(telegram_message_id=message_id)
                    )

            logger.info(
                "رویداد جدید در شهر %d — نوع: %s",
                city.id, event_data["event_type"],
            )

        except Exception:
            logger.exception("خطا در ساخت رویداد برای شهر %d.", city.id)


# ================================================================
# تسک: ریکاوری انرژی
# ================================================================

async def task_energy_recovery(bot: Bot) -> None:
    """
    هر ۶ ساعت انرژی همه بازیکنان را بازیابی می‌کند.
    """

    interval = settings.energy_task_interval_seconds
    logger.info("تسک ریکاوری انرژی شروع شد — فاصله: %ds", interval)

    while True:

        try:
            await asyncio.sleep(interval)
            await _recover_all_energy(bot)

        except asyncio.CancelledError:
            logger.info("تسک ریکاوری انرژی لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک ریکاوری انرژی.")
            await asyncio.sleep(300)


async def _recover_all_energy(bot: Bot) -> None:

    amount = settings.energy_recovery_amount
    total_recovered = 0

    async with get_session() as session:

        result = await session.execute(
            select(City.id).where(City.is_active.is_(True))
        )
        city_ids = [row[0] for row in result.all()]

    for city_id in city_ids:

        try:
            async with get_session() as session:
                count = await restore_energy_for_city(session, city_id, amount)
                total_recovered += count

        except Exception:
            logger.exception("خطا در ریکاوری انرژی شهر %d.", city_id)

    if total_recovered > 0:
        logger.info(
            "ریکاوری انرژی انجام شد — %d بازیکن — +%d انرژی",
            total_recovered, amount,
        )


# ================================================================
# تسک: ریست روزانه
# ================================================================

async def task_daily_reset(bot: Bot) -> None:
    """
    هر روز در ساعت مشخص:
      - مأموریت‌های منقضی پاک می‌شن
      - الماس روزانه اشتراک طلایی داده می‌شه
      - اعلام رتبه‌بندی روزانه
    """

    logger.info("تسک ریست روزانه شروع شد.")

    while True:

        try:
            now = utcnow()
            reset_hour = settings.daily_reset_hour_utc

            # محاسبه زمان تا ریست بعدی
            next_reset = now.replace(
                hour=reset_hour,
                minute=0,
                second=0,
                microsecond=0,
            )

            if now >= next_reset:
                next_reset += timedelta(days=1)

            wait_seconds = (next_reset - now).total_seconds()

            logger.info(
                "ریست روزانه بعدی: %s — %d ثانیه دیگه",
                next_reset.strftime("%Y-%m-%d %H:%M UTC"),
                int(wait_seconds),
            )

            await asyncio.sleep(wait_seconds)
            await _perform_daily_reset(bot)

        except asyncio.CancelledError:
            logger.info("تسک ریست روزانه لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک ریست روزانه.")
            await asyncio.sleep(3600)


async def _perform_daily_reset(bot: Bot) -> None:

    logger.info("ریست روزانه شروع شد.")

    # ━━━ ۱. الماس روزانه اشتراک طلایی ━━━
    await _distribute_daily_diamonds()

    # ━━━ ۲. پاکسازی مأموریت‌های منقضی ━━━
    await _expire_old_missions()

    # ━━━ ۳. اعلام رتبه‌بندی روزانه ━━━
    await _announce_daily_rankings(bot)

    logger.info("ریست روزانه تموم شد.")


async def _distribute_daily_diamonds() -> None:
    """الماس روزانه به اشتراک‌های طلایی فعال می‌دهد."""

    now = utcnow()
    daily_diamonds = settings.gold_subscription_daily_diamonds

    if daily_diamonds <= 0:
        return

    async with get_session() as session:

        result = await session.execute(
            select(User).where(
                User.gold_subscription_until > now,
                User.is_active.is_(True),
            )
        )

        users = result.scalars().all()
        count = 0

        for user in users:
            user.diamonds += daily_diamonds
            count += 1

        if count > 0:
            await session.flush()

    logger.info(
        "الماس روزانه توزیع شد — %d کاربر — +%d الماس",
        count, daily_diamonds,
    )


async def _expire_old_missions() -> None:
    """مأموریت‌های روزانه منقضی را پاک می‌کند."""

    now = utcnow()

    async with get_session() as session:

        # مأموریت‌های روزانه که بیشتر از ۲۴ ساعت از ساختشون گذشته
        result = await session.execute(
            select(Mission).where(
                Mission.mission_type == MissionType.DAILY.value,
                Mission.created_at < now - timedelta(days=1),
                Mission.is_active.is_(True),
            )
        )

        old_missions = result.scalars().all()

        for mission in old_missions:
            mission.is_active = False

        if old_missions:
            await session.flush()

    logger.info("مأموریت‌های منقضی: %d", len(old_missions))


async def _announce_daily_rankings(bot: Bot) -> None:
    """رتبه‌بندی روزانه را در شهرهای فعال اعلام می‌کند."""

    async with get_session() as session:

        result = await session.execute(
            select(City).where(City.is_active.is_(True))
        )
        cities = result.scalars().all()

    for city in cities:

        try:
            async with get_session() as session:
                rows = await get_city_leaderboard(session, city.id, limit=5)
                population = await get_city_population(session, city.id)

            if not rows or population < 5:
                continue

            lines = [f"📊 <b>رتبه‌بندی روزانه — {escape_html(city.name)}</b>\n"]

            medals = GameConstants.RANK_MEDALS

            for i, row in enumerate(rows[:3]):
                user = row["user"]
                stats = row["stats"]
                medal = medals[i] if i < len(medals) else f"{i+1}."
                name = f"@{user.username}" if user.username else user.display_name or str(user.id)
                lines.append(
                    f"{medal} {escape_html(name)} — "
                    f"سطح {stats.level} — "
                    f"◈ {row['total_eco']:,}"
                )

            await safe_send_to_chat(
                bot,
                city.telegram_chat_id,
                "\n".join(lines),
            )

        except Exception:
            logger.exception("خطا در اعلام رتبه‌بندی شهر %d.", city.id)


# ================================================================
# تسک: رتبه‌بندی هفتگی
# ================================================================

async def task_weekly_ranking(bot: Bot) -> None:
    """هر هفته رتبه‌بندی کامل را اعلام می‌کند."""

    interval = settings.weekly_rank_interval_seconds
    logger.info("تسک رتبه‌بندی هفتگی شروع شد — فاصله: %ds", interval)

    # اول یه هفته صبر کن
    await asyncio.sleep(interval)

    while True:

        try:
            await _announce_weekly_rankings(bot)
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("تسک رتبه‌بندی هفتگی لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک رتبه‌بندی هفتگی.")
            await asyncio.sleep(3600)


async def _announce_weekly_rankings(bot: Bot) -> None:

    async with get_session() as session:

        result = await session.execute(
            select(City).where(City.is_active.is_(True))
        )
        cities = result.scalars().all()

    for city in cities:

        try:
            async with get_session() as session:
                rows = await get_city_leaderboard(session, city.id, limit=10)
                population = await get_city_population(session, city.id)

            if not rows or population < 3:
                continue

            lines = [
                f"🏆 <b>رتبه‌بندی هفتگی — {escape_html(city.name)}</b>\n",
                f"👥 جمعیت: {population:,}\n",
            ]

            medals = GameConstants.RANK_MEDALS

            for i, row in enumerate(rows):
                user = row["user"]
                stats = row["stats"]
                medal = medals[i] if i < len(medals) else f"{i+1}."
                name = (
                    f"@{user.username}"
                    if user.username
                    else user.display_name or str(user.id)
                )
                lines.append(
                    f"{medal} {escape_html(name)}\n"
                    f"   سطح {stats.level} | "
                    f"⭐ {stats.xp:,} XP | "
                    f"◈ {row['total_eco']:,}"
                )

            # ثبت در تاریخ شهر
            if rows:
                top_user = rows[0]["user"]
                top_name = (
                    f"@{top_user.username}"
                    if top_user.username
                    else top_user.display_name or str(top_user.id)
                )

                async with get_session() as session:
                    await add_city_history(
                        session,
                        city.id,
                        "weekly_ranking",
                        f"🏆 {top_name} برنده رتبه‌بندی هفتگی شد",
                        actor_user_id=top_user.id,
                    )

            await safe_send_to_chat(
                bot,
                city.telegram_chat_id,
                "\n".join(lines),
            )

        except Exception:
            logger.exception("خطا در اعلام رتبه‌بندی هفتگی شهر %d.", city.id)


# ================================================================
# تسک: محاسبه معادن
# ================================================================

async def task_mine_calculator(bot: Bot) -> None:
    """
    هر ساعت تولید معادن را محاسبه و ذخیره می‌کند.
    اگه معدن پر بود، به صاحبش اطلاع می‌ده.
    """

    interval = settings.mine_check_interval_seconds
    logger.info("تسک معدن شروع شد — فاصله: %ds", interval)

    while True:

        try:
            await asyncio.sleep(interval)
            await _calculate_mines(bot)

        except asyncio.CancelledError:
            logger.info("تسک معدن لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک معدن.")
            await asyncio.sleep(300)


async def _calculate_mines(bot: Bot) -> None:
    """تولید همه معادن را محاسبه می‌کند."""

    from database import UserMine, calculate_mine_production

    async with get_session() as session:

        result = await session.execute(
            select(UserMine)
        )
        mines = result.scalars().all()

    notified = 0

    for mine in mines:

        try:
            async with get_session() as session:
                production = await calculate_mine_production(session, mine.user_id)

            # اگه معدن ۹۰٪ پر بود، به بازیکن اطلاع بده
            if (
                production["accumulated"] >= production["max_storage"] * 0.9
                and production["accumulated"] > 0
            ):
                # پیدا کردن اکانت تلگرام
                async with get_session() as session:
                    user_res = await session.execute(
                        select(User).where(User.id == mine.user_id)
                    )
                    user = user_res.scalar_one_or_none()

                if user:
                    try:
                        await bot.send_message(
                            mine.user_id,
                            (
                                f"⛏ <b>معدنت داره پر می‌شه!</b>\n\n"
                                f"◈ {production['accumulated']:,} اکو منتظر برداشته.\n\n"
                                f"زود برگرد و برداشت کن!"
                            ),
                            parse_mode="HTML",
                        )
                        notified += 1
                    except Exception:
                        pass  # کاربر ربات رو بلاک کرده

        except Exception:
            logger.exception("خطا در محاسبه معدن کاربر %d.", mine.user_id)

    if notified > 0:
        logger.info("%d اعلام معدن پر ارسال شد.", notified)


# ================================================================
# تسک: نظارت بر اشتراک‌ها
# ================================================================

async def task_subscription_monitor(bot: Bot) -> None:
    """
    هر ساعت اشتراک‌های منقضی را غیرفعال می‌کند.
    """

    logger.info("تسک نظارت اشتراک شروع شد.")

    while True:

        try:
            await asyncio.sleep(3600)
            await _expire_subscriptions(bot)

        except asyncio.CancelledError:
            logger.info("تسک نظارت اشتراک لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک نظارت اشتراک.")
            await asyncio.sleep(300)


async def _expire_subscriptions(bot: Bot) -> None:

    now = utcnow()

    async with get_session() as session:

        result = await session.execute(
            select(User).where(
                User.gold_subscription_until != None,
                User.gold_subscription_until <= now,
            )
        )

        expired_users = result.scalars().all()

        for user in expired_users:
            user.gold_subscription_until = None

            try:
                await bot.send_message(
                    user.id,
                    (
                        "⏰ <b>اشتراک طلایی منقضی شد</b>\n\n"
                        "اشتراک طلایی تو تموم شد.\n"
                        "برای تمدید از فروشگاه اقدام کن."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        if expired_users:
            await session.flush()
            logger.info("%d اشتراک منقضی شد.", len(expired_users))


# ================================================================
# تسک: سلامت‌سنجی
# ================================================================

async def task_health_monitor() -> None:
    """هر ۵ دقیقه سلامت دیتابیس و Redis را بررسی می‌کند."""

    logger.info("تسک سلامت‌سنجی شروع شد.")

    while True:

        try:
            await asyncio.sleep(300)

            db_ok    = await database_health()
            redis_ok = await redis_health()

            if not db_ok:
                logger.error("⚠️ PostgreSQL در دسترس نیست!")

            if not redis_ok:
                logger.error("⚠️ Redis در دسترس نیست!")

            if db_ok and redis_ok:
                logger.debug("سلامت‌سنجی: همه چیز خوبه.")

        except asyncio.CancelledError:
            logger.info("تسک سلامت‌سنجی لغو شد.")
            break

        except Exception:
            logger.exception("خطا در تسک سلامت‌سنجی.")


# ================================================================
# راه‌اندازی
# ================================================================

async def startup(bot: Bot, dp: Dispatcher) -> None:

    logger.info("=" * 60)
    logger.info("اِکو در حال راه‌اندازی...")
    logger.info("محیط: %s", getattr(settings, "app_env", "production"))
    logger.info("=" * 60)

    # ━━━ ۱. دیتابیس ━━━
    logger.info("راه‌اندازی دیتابیس...")
    try:
        await init_database()
    except Exception:
        logger.exception("راه‌اندازی دیتابیس شکست خورد.")
        raise

    logger.info("PostgreSQL: ✓")
    logger.info("Redis: ✓")

    # ━━━ ۲. تلگرام ━━━
    logger.info("بررسی اتصال تلگرام...")
    try:
        me = await bot.get_me()
    except Exception:
        logger.exception("اتصال به تلگرام شکست خورد.")
        raise

    logger.info("تلگرام: @%s (id=%s) ✓", me.username, me.id)

    # ━━━ ۳. هندلرها ━━━
    register_handlers(dp)
    logger.info("هندلرها ثبت شدند. ✓")

    # ━━━ ۴. دستورات ━━━
    try:
        await setup_bot_commands(bot)
        logger.info("دستورات ربات تنظیم شدند. ✓")
    except Exception:
        logger.warning("خطا در تنظیم دستورات ربات.")

    # ━━━ ۵. وب‌هوک ━━━
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("وب‌هوک پاک شد. ✓")
    except Exception:
        logger.exception("خطا در پاک کردن وب‌هوک.")
        raise

    # ━━━ ۶. تسک‌های پس‌زمینه ━━━
    spawn(task_event_manager(bot))
    spawn(task_energy_recovery(bot))
    spawn(task_daily_reset(bot))
    spawn(task_weekly_ranking(bot))
    spawn(task_mine_calculator(bot))
    spawn(task_subscription_monitor(bot))
    spawn(task_health_monitor())

    logger.info("تسک‌های پس‌زمینه شروع شدند. ✓")
    logger.info("=" * 60)
    logger.info("اِکو آماده است. بنویس. بساز. حکومت کن.")
    logger.info("=" * 60)


# ================================================================
# خاموش‌سازی
# ================================================================

async def shutdown(bot: Bot) -> None:

    logger.info("=" * 60)
    logger.info("اِکو در حال خاموش شدن...")
    logger.info("=" * 60)

    # ━━━ ۱. تسک‌ها ━━━
    try:
        await cancel_all_tasks()
    except Exception:
        logger.exception("خطا در لغو تسک‌ها.")

    # ━━━ ۲. Redis ━━━
    try:
        await close_redis()
        logger.info("Redis: بسته شد.")
    except Exception:
        logger.exception("خطا در بستن Redis.")

    # ━━━ ۳. دیتابیس ━━━
    try:
        await close_database()
        logger.info("PostgreSQL: بسته شد.")
    except Exception:
        logger.exception("خطا در بستن دیتابیس.")

    # ━━━ ۴. تلگرام ━━━
    try:
        await bot.session.close()
        logger.info("سِشن تلگرام: بسته شد.")
    except Exception:
        logger.exception("خطا در بستن سِشن تلگرام.")

    logger.info("اِکو متوقف شد.")


# ================================================================
# نقطه ورود اصلی
# ================================================================

async def main() -> None:

    configure_logging()

    bot: Optional[Bot] = None

    try:
        # ━━━ ساخت ربات ━━━
        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
            ),
        )

        # ━━━ ساخت دیسپچر ━━━
        dp = Dispatcher()

        # ━━━ راه‌اندازی ━━━
        await startup(bot, dp)

        # ━━━ مدیریت سیگنال ━━━
        loop = asyncio.get_running_loop()

        def handle_signal(sig: signal.Signals) -> None:
            logger.info("سیگنال %s دریافت شد.", sig.name)
            asyncio.create_task(dp.stop_polling())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal, sig)
            except (NotImplementedError, RuntimeError):
                pass

        # ━━━ پولینگ ━━━
        logger.info("پولینگ شروع شد...")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    except KeyboardInterrupt:
        logger.info("توقف با Ctrl+C.")

    except Exception:
        logger.exception("خطای بحرانی در اِکو.")
        raise

    finally:
        if bot is not None:
            await shutdown(bot)


# ================================================================
# اجرا
# ================================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
