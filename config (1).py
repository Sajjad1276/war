# ================================================================
# اِکو — config.py
# تنظیمات مرکزی برنامه و ثابت‌های بازی
# ================================================================
#
# بنویس. بساز. حکومت کن.
#
# این فایل تنها منبع تنظیمات برنامه است.
# هیچ منطق بازی، اتصال دیتابیس یا هندلر تلگرامی
# در این فایل وجود ندارد.
#
# ساختار:
#   config.py
#       ↓
#   database.py
#       ↓
#   game.py
#       ↓
#   handlers.py
#       ↓
#   main.py
# ================================================================

from __future__ import annotations

from typing import Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ================================================================
# انواع محیط و لاگ
# ================================================================

AppEnvironment = Literal[
    "development",
    "staging",
    "production",
]

LogLevel = Literal[
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
]


# ================================================================
# تنظیمات اصلی
# ================================================================

class Settings(BaseSettings):
    """
    تنظیمات مرکزی اِکو.

    تمام مقادیر از فایل .env یا متغیرهای محیطی خوانده می‌شوند.
    """

    # ------------------------------------------------------------
    # برنامه
    # ------------------------------------------------------------

    app_name: str = Field(
        default="اِکو",
        min_length=1,
    )

    app_env: AppEnvironment = "development"

    debug: bool = False

    log_level: LogLevel = "INFO"

    # ------------------------------------------------------------
    # هسته اصلی
    # ------------------------------------------------------------

    bot_token: str = Field(
        ...,
        min_length=1,
        repr=False,
    )

    database_url: str = Field(
        ...,
        min_length=1,
        repr=False,
    )

    redis_url: str = Field(
        ...,
        min_length=1,
        repr=False,
    )

    # ------------------------------------------------------------
    # شناسه ادمین‌های سیستم
    # ------------------------------------------------------------

    # شناسه‌های تلگرامی که دسترسی ادمین دارند (با کاما جدا)
    admin_ids: str = Field(
        default="",
        repr=False,
    )

    # ------------------------------------------------------------
    # اقتصاد پایه بازی
    # ------------------------------------------------------------

    # واحد پول بازی
    currency_name: str = "اکو"
    currency_symbol: str = "◈"

    # موجودی اولیه هر بازیکن جدید
    starting_eco: int = Field(
        default=500,
        ge=0,
    )

    # انرژی اولیه و حداکثر
    starting_energy: int = Field(
        default=100,
        ge=1,
    )

    max_energy: int = Field(
        default=100,
        ge=1,
    )

    # ریکاوری انرژی: هر X ثانیه Y واحد
    energy_recovery_amount: int = Field(
        default=25,
        ge=1,
    )

    energy_recovery_interval_seconds: int = Field(
        default=21_600,  # ۶ ساعت
        ge=60,
    )

    # ------------------------------------------------------------
    # سیستم سطح و تجربه
    # ------------------------------------------------------------

    # پایه XP برای هر سطح (فرمول: base * level * 1.5)
    xp_base_per_level: int = Field(
        default=100,
        ge=10,
    )

    # ضریب رشد XP بین سطح‌ها
    xp_level_multiplier: float = Field(
        default=1.5,
        ge=1.0,
    )

    # حداکثر سطح
    max_level: int = Field(
        default=50,
        ge=10,
    )

    # ------------------------------------------------------------
    # سیستم اِکو (پیام در گروه)
    # ------------------------------------------------------------

    # اِکوی پایه برای هر پیام در گروه
    eco_per_message: int = Field(
        default=10,
        ge=1,
    )

    # حداکثر اِکو از پیام در روز (جلوگیری از اسپم)
    max_eco_from_messages_daily: int = Field(
        default=500,
        ge=100,
    )

    # XP برای هر پیام در گروه
    xp_per_message: int = Field(
        default=2,
        ge=0,
    )

    # شانس واکنش تصادفی ربات به پیام (درصد)
    random_reaction_chance: int = Field(
        default=15,
        ge=0,
        le=100,
    )

    # ------------------------------------------------------------
    # سیستم کار
    # ------------------------------------------------------------

    # کولداون کار (ثانیه)
    work_cooldown_seconds: int = Field(
        default=3_600,  # ۱ ساعت
        ge=60,
    )

    # حداکثر دفعات کار در روز
    work_max_daily: int = Field(
        default=5,
        ge=1,
    )

    # درآمد هر شغل (حداقل، حداکثر)
    work_laborer_min: int = Field(default=500, ge=0)
    work_laborer_max: int = Field(default=1_500, ge=0)
    work_laborer_energy: int = Field(default=20, ge=0)
    work_laborer_xp: int = Field(default=50, ge=0)
    work_laborer_min_level: int = Field(default=1, ge=1)
    work_laborer_fail_chance: int = Field(default=0, ge=0, le=100)

    work_trader_min: int = Field(default=1_000, ge=0)
    work_trader_max: int = Field(default=4_000, ge=0)
    work_trader_energy: int = Field(default=25, ge=0)
    work_trader_xp: int = Field(default=100, ge=0)
    work_trader_min_level: int = Field(default=3, ge=1)
    work_trader_fail_chance: int = Field(default=15, ge=0, le=100)

    work_detective_min: int = Field(default=2_000, ge=0)
    work_detective_max: int = Field(default=7_000, ge=0)
    work_detective_energy: int = Field(default=30, ge=0)
    work_detective_xp: int = Field(default=150, ge=0)
    work_detective_min_level: int = Field(default=5, ge=1)
    work_detective_fail_chance: int = Field(default=25, ge=0, le=100)

    work_hacker_min: int = Field(default=5_000, ge=0)
    work_hacker_max: int = Field(default=15_000, ge=0)
    work_hacker_energy: int = Field(default=35, ge=0)
    work_hacker_xp: int = Field(default=250, ge=0)
    work_hacker_min_level: int = Field(default=10, ge=1)
    work_hacker_fail_chance: int = Field(default=35, ge=0, le=100)
    work_hacker_penalty_min: int = Field(default=1_000, ge=0)
    work_hacker_penalty_max: int = Field(default=3_000, ge=0)

    # ------------------------------------------------------------
    # سیستم اکتشاف
    # ------------------------------------------------------------

    # کولداون اکتشاف (ثانیه)
    explore_cooldown_seconds: int = Field(
        default=7_200,  # ۲ ساعت
        ge=60,
    )

    # انرژی مصرفی اکتشاف
    explore_energy_cost: int = Field(
        default=25,
        ge=1,
    )

    # XP پایه اکتشاف
    explore_base_xp: int = Field(
        default=75,
        ge=0,
    )

    # احتمالات اکتشاف (درصد — جمع باید ۱۰۰ بشه)
    explore_chance_nothing: int = Field(default=35, ge=0)
    explore_chance_money: int = Field(default=30, ge=0)
    explore_chance_trap: int = Field(default=20, ge=0)
    explore_chance_special: int = Field(default=10, ge=0)
    explore_chance_legendary: int = Field(default=5, ge=0)

    # پاداش‌های اکتشاف
    explore_money_min: int = Field(default=2_000, ge=0)
    explore_money_max: int = Field(default=8_000, ge=0)
    explore_trap_energy_min: int = Field(default=10, ge=0)
    explore_trap_energy_max: int = Field(default=25, ge=0)
    explore_special_xp_bonus: int = Field(default=300, ge=0)
    explore_legendary_eco: int = Field(default=20_000, ge=0)
    explore_legendary_xp: int = Field(default=1_000, ge=0)

    # ------------------------------------------------------------
    # سیستم مأموریت
    # ------------------------------------------------------------

    # تعداد مأموریت‌های روزانه نمایش‌داده‌شده
    daily_mission_count: int = Field(default=3, ge=1)

    # تعداد مأموریت‌های هفتگی
    weekly_mission_count: int = Field(default=2, ge=1)

    # ساعت ریست مأموریت‌های روزانه (UTC)
    mission_daily_reset_hour: int = Field(default=0, ge=0, le=23)

    # ساعت ریست مأموریت‌های هفتگی (شنبه، UTC)
    mission_weekly_reset_hour: int = Field(default=0, ge=0, le=23)

    # ------------------------------------------------------------
    # سیستم رویداد جمعی
    # ------------------------------------------------------------

    # فاصله بین رویدادها (ثانیه) — حداقل و حداکثر
    event_interval_min_seconds: int = Field(
        default=28_800,   # ۸ ساعت
        ge=3_600,
    )

    event_interval_max_seconds: int = Field(
        default=43_200,   # ۱۲ ساعت
        ge=3_600,
    )

    # مدت هر رویداد (ثانیه)
    event_crisis_duration: int = Field(default=21_600, ge=3_600)   # ۶ ساعت
    event_attack_duration: int = Field(default=14_400, ge=3_600)   # ۴ ساعت
    event_festival_duration: int = Field(default=10_800, ge=3_600) # ۳ ساعت
    event_contest_duration: int = Field(default=86_400, ge=3_600)  # ۲۴ ساعت
    event_explore_duration: int = Field(default=21_600, ge=3_600)  # ۶ ساعت

    # پاداش رویداد بحران (ضریب برگشت)
    event_crisis_reward_multiplier: float = Field(default=2.0, ge=1.0)

    # پنالتی شکست رویداد بحران (درصد کاهش خزانه)
    event_crisis_fail_penalty: int = Field(default=20, ge=0, le=100)

    # پاداش رویداد حمله (اِکو به هر شرکت‌کننده)
    event_attack_reward_eco: int = Field(default=1_500, ge=0)

    # پنالتی شکست رویداد حمله (درصد کاهش خزانه)
    event_attack_fail_penalty: int = Field(default=15, ge=0, le=100)

    # ضریب XP در جشن
    event_festival_xp_multiplier: float = Field(default=2.0, ge=1.0)

    # جایزه نفر اول رقابت
    event_contest_first_prize: int = Field(default=50_000, ge=0)
    event_contest_second_prize: int = Field(default=25_000, ge=0)
    event_contest_third_prize: int = Field(default=10_000, ge=0)

    # حداقل شرکت‌کننده برای کشف مشترک
    event_explore_min_participants: int = Field(default=10, ge=2)

    # ------------------------------------------------------------
    # سیستم شهر
    # ------------------------------------------------------------

    # آجر پایه برای لول‌آپ شهر (فرمول: base * level^2)
    city_level_base_bricks: int = Field(
        default=1_000,
        ge=100,
    )

    # حداکثر سطح شهر
    city_max_level: int = Field(
        default=100,
        ge=10,
    )

    # درصد مالیات انتقال اِکو بین شهرها
    city_transfer_tax: int = Field(
        default=10,
        ge=0,
        le=50,
    )

    # درصد کارمزد معاملات P2P
    market_transaction_fee: int = Field(
        default=5,
        ge=0,
        le=30,
    )

    # ------------------------------------------------------------
    # سیستم معدن
    # ------------------------------------------------------------

    # تولید معدن در ساعت (هر سطح)
    mine_dirt_hourly: int = Field(default=10, ge=0)
    mine_stone_hourly: int = Field(default=25, ge=0)
    mine_iron_hourly: int = Field(default=60, ge=0)
    mine_gold_hourly: int = Field(default=150, ge=0)
    mine_crystal_hourly: int = Field(default=400, ge=0)

    # هزینه ارتقا معدن (الماس)
    mine_buy_cost_diamonds: int = Field(default=500, ge=1)
    mine_stone_upgrade_diamonds: int = Field(default=200, ge=1)
    mine_iron_upgrade_diamonds: int = Field(default=500, ge=1)
    mine_gold_upgrade_diamonds: int = Field(default=1_000, ge=1)
    mine_crystal_upgrade_diamonds: int = Field(default=2_500, ge=1)

    # حداکثر ذخیره معدن (ساعت)
    mine_max_storage_hours: int = Field(default=72, ge=1)

    # ------------------------------------------------------------
    # سیستم الماس (پریمیوم)
    # ------------------------------------------------------------

    # بسته‌های الماس (تعداد الماس)
    diamond_pack_small: int = Field(default=100, ge=1)
    diamond_pack_medium: int = Field(default=500, ge=1)
    diamond_pack_large: int = Field(default=1_500, ge=1)
    diamond_pack_xlarge: int = Field(default=5_000, ge=1)

    # قیمت بسته‌های الماس (تومان)
    diamond_pack_small_price: int = Field(default=9_900, ge=0)
    diamond_pack_medium_price: int = Field(default=44_900, ge=0)
    diamond_pack_large_price: int = Field(default=124_900, ge=0)
    diamond_pack_xlarge_price: int = Field(default=399_000, ge=0)

    # هزینه آیتم‌های الماسی
    diamond_energy_refill: int = Field(default=50, ge=1)
    diamond_income_boost_24h: int = Field(default=150, ge=1)
    diamond_risk_shield: int = Field(default=80, ge=1)
    diamond_work_reset: int = Field(default=30, ge=1)
    diamond_explore_reset: int = Field(default=40, ge=1)
    diamond_profile_frame: int = Field(default=200, ge=1)
    diamond_custom_title: int = Field(default=300, ge=1)
    diamond_colored_name: int = Field(default=150, ge=1)
    diamond_factory_buy: int = Field(default=800, ge=1)
    diamond_market_stall_buy: int = Field(default=1_200, ge=1)
    diamond_land_buy: int = Field(default=800, ge=1)
    diamond_guild_slot: int = Field(default=400, ge=1)
    diamond_event_ticket: int = Field(default=100, ge=1)

    # ------------------------------------------------------------
    # اشتراک طلایی
    # ------------------------------------------------------------

    # قیمت اشتراک ماهانه (تومان)
    gold_subscription_price: int = Field(
        default=29_900,
        ge=0,
    )

    # الماس روزانه اشتراک طلایی
    gold_subscription_daily_diamonds: int = Field(
        default=50,
        ge=0,
    )

    # درصد بونوس درآمد اشتراک طلایی
    gold_subscription_income_bonus: int = Field(
        default=25,
        ge=0,
        le=100,
    )

    # ------------------------------------------------------------
    # پلن مدیر گروه
    # ------------------------------------------------------------

    # قیمت پلن مدیر (تومان در ماه)
    admin_plan_price: int = Field(
        default=49_900,
        ge=0,
    )

    # ------------------------------------------------------------
    # سیستم گیلد
    # ------------------------------------------------------------

    # حداقل سطح برای تأسیس گیلد
    guild_min_level: int = Field(
        default=15,
        ge=1,
    )

    # هزینه تأسیس گیلد (اِکو)
    guild_create_cost: int = Field(
        default=50_000,
        ge=0,
    )

    # حداکثر اعضای گیلد پایه
    guild_max_members: int = Field(
        default=20,
        ge=5,
    )

    # ------------------------------------------------------------
    # سیستم استریک روزانه
    # ------------------------------------------------------------

    # بونوس استریک (به ازای هر روز پشت سر هم)
    streak_bonus_eco: int = Field(
        default=100,
        ge=0,
    )

    streak_bonus_xp: int = Field(
        default=25,
        ge=0,
    )

    # حداکثر استریک (روز)
    streak_max_days: int = Field(
        default=30,
        ge=7,
    )

    # ضریب پاداش استریک ۷ روزه
    streak_week_multiplier: float = Field(
        default=2.0,
        ge=1.0,
    )

    # ضریب پاداش استریک ۳۰ روزه
    streak_month_multiplier: float = Field(
        default=5.0,
        ge=1.0,
    )

    # ------------------------------------------------------------
    # سیستم انتقال اکانت
    # ------------------------------------------------------------

    # کارمزد انتقال اکانت (درصد از ارزش اعلام‌شده)
    account_transfer_fee: int = Field(
        default=10,
        ge=0,
        le=30,
    )

    # مدت اعتبار کد انتقال (ثانیه)
    account_transfer_code_ttl: int = Field(
        default=86_400,  # ۲۴ ساعت
        ge=3_600,
    )

    # ------------------------------------------------------------
    # نرخ‌گذاری پیام
    # ------------------------------------------------------------

    # حداکثر پیام در X ثانیه (جلوگیری از اسپم)
    rate_limit_messages: int = Field(default=5, ge=1)
    rate_limit_window_seconds: int = Field(default=10, ge=1)

    # کولداون بعد از خطای نرخ‌گذاری (ثانیه)
    rate_limit_cooldown_seconds: int = Field(default=30, ge=5)

    # ------------------------------------------------------------
    # سِشن
    # ------------------------------------------------------------

    # TTL سِشن بازی در Redis (ثانیه)
    session_ttl_seconds: int = Field(
        default=600,
        ge=60,
    )

    # TTL نیت (intent) در Redis (ثانیه)
    intent_ttl_seconds: int = Field(
        default=300,
        ge=30,
    )

    # ------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------

    redis_prefix: str = Field(
        default="echo:",
        min_length=1,
    )

    redis_max_connections: int = Field(
        default=20,
        ge=5,
    )

    # ------------------------------------------------------------
    # دیتابیس
    # ------------------------------------------------------------

    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_recycle: int = Field(default=1_800, ge=60)

    # ------------------------------------------------------------
    # تسک‌های پس‌زمینه
    # ------------------------------------------------------------

    # فاصله بررسی رویدادها (ثانیه)
    event_check_interval_seconds: int = Field(
        default=600,  # ۱۰ دقیقه
        ge=60,
    )

    # فاصله بررسی معادن (ثانیه)
    mine_check_interval_seconds: int = Field(
        default=3_600,  # ۱ ساعت
        ge=60,
    )

    # فاصله اعلام رتبه‌بندی هفتگی (ثانیه)
    weekly_rank_interval_seconds: int = Field(
        default=604_800,  # ۷ روز
        ge=3_600,
    )

    # فاصله ریکاوری انرژی (ثانیه)
    energy_task_interval_seconds: int = Field(
        default=21_600,  # ۶ ساعت
        ge=60,
    )

    # ساعت ریست روزانه (UTC)
    daily_reset_hour_utc: int = Field(
        default=0,
        ge=0,
        le=23,
    )

    # ================================================================
    # Pydantic Settings
    # ================================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # ================================================================
    # اعتبارسنجی‌ها
    # ================================================================

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(
        cls,
        value: str,
    ) -> str:

        value = value.strip()

        if not value:
            raise ValueError(
                "BOT_TOKEN الزامی است."
            )

        return value

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(
        cls,
        value: str,
    ) -> str:

        value = value.strip()

        if not value:
            raise ValueError(
                "DATABASE_URL الزامی است."
            )

        replacements = {
            "postgres://": "postgresql+asyncpg://",
            "postgresql://": "postgresql+asyncpg://",
            "postgresql+psycopg2://": "postgresql+asyncpg://",
        }

        for old, new in replacements.items():
            if value.startswith(old):
                return new + value[len(old):]

        if value.startswith("postgresql+asyncpg://"):
            return value

        raise ValueError(
            "DATABASE_URL باید از PostgreSQL استفاده کند.\n"
            "فرمت‌های پشتیبانی‌شده:\n"
            "  postgres://\n"
            "  postgresql://\n"
            "  postgresql+asyncpg://"
        )

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(
        cls,
        value: str,
    ) -> str:

        value = value.strip()

        if not value:
            raise ValueError(
                "REDIS_URL الزامی است."
            )

        if not value.startswith(
            ("redis://", "rediss://")
        ):
            raise ValueError(
                "REDIS_URL باید با redis:// یا rediss:// شروع شود."
            )

        return value

    @field_validator("redis_prefix")
    @classmethod
    def normalize_redis_prefix(
        cls,
        value: str,
    ) -> str:

        value = value.strip()

        if not value:
            raise ValueError(
                "REDIS_PREFIX نمی‌تواند خالی باشد."
            )

        if not value.endswith(":"):
            value += ":"

        return value

    @field_validator("admin_ids")
    @classmethod
    def validate_admin_ids(
        cls,
        value: str,
    ) -> str:

        if not value.strip():
            return ""

        parts = value.strip().split(",")

        for part in parts:

            part = part.strip()

            if not part.isdigit():
                raise ValueError(
                    f"شناسه ادمین نامعتبر: {part!r}\n"
                    "شناسه‌ها باید عدد باشند و با کاما جدا شوند."
                )

        return value

    @model_validator(mode="before")
    @classmethod
    def set_environment_defaults(
        cls,
        values: object,
    ) -> object:

        if not isinstance(values, dict):
            return values

        app_env = values.get(
            "APP_ENV",
            values.get(
                "app_env",
                "development",
            ),
        )

        debug_provided = (
            "DEBUG" in values
            or "debug" in values
        )

        if not debug_provided:
            values["DEBUG"] = (
                app_env != "production"
            )

        return values

    # ================================================================
    # متدهای کمکی
    # ================================================================

    def get_admin_ids(self) -> list[int]:
        """
        لیست شناسه‌های ادمین سیستم.
        """

        if not self.admin_ids.strip():
            return []

        return [
            int(i.strip())
            for i in self.admin_ids.split(",")
            if i.strip().isdigit()
        ]

    def is_admin(
        self,
        user_id: int,
    ) -> bool:
        """
        بررسی اینکه کاربر ادمین سیستم است یا نه.
        """

        return user_id in self.get_admin_ids()

    def xp_required_for_level(
        self,
        level: int,
    ) -> int:
        """
        محاسبه XP لازم برای رسیدن به سطح مشخص.

        فرمول: base * level * multiplier
        """

        if level <= 1:
            return 0

        return int(
            self.xp_base_per_level
            * (level - 1)
            * (self.xp_level_multiplier ** (level - 2))
        )

    def total_xp_for_level(
        self,
        level: int,
    ) -> int:
        """
        مجموع XP لازم برای رسیدن به سطح مشخص از صفر.
        """

        return sum(
            self.xp_required_for_level(lvl)
            for lvl in range(2, level + 1)
        )

    def city_bricks_for_level(
        self,
        city_level: int,
    ) -> int:
        """
        آجر لازم برای رسیدن شهر به سطح مشخص.

        فرمول: base * level^2
        """

        return (
            self.city_level_base_bricks
            * (city_level ** 2)
        )

    def mine_hourly_production(
        self,
        mine_level: str,
    ) -> int:
        """
        تولید ساعتی معدن بر اساس سطح.
        """

        production_map = {
            "dirt":    self.mine_dirt_hourly,
            "stone":   self.mine_stone_hourly,
            "iron":    self.mine_iron_hourly,
            "gold":    self.mine_gold_hourly,
            "crystal": self.mine_crystal_hourly,
        }

        return production_map.get(
            mine_level,
            self.mine_dirt_hourly,
        )

    def format_eco(
        self,
        amount: int,
    ) -> str:
        """
        نمایش مقدار اِکو با نماد.
        مثال: ◈ ۴,۵۰۰
        """

        return f"{self.currency_symbol} {amount:,}"


# ================================================================
# نمونه تنها (Singleton)
# ================================================================

settings = Settings()


# ================================================================
# ثابت‌های بازی (غیر قابل تغییر از ENV)
# ================================================================

class GameConstants:
    """
    ثابت‌هایی که نباید از بیرون تغییر کنند.
    """

    # نام مشاغل
    JOBS = {
        "laborer":   "کارگر ساده",
        "trader":    "تاجر",
        "detective": "کارآگاه",
        "hacker":    "هکر",
    }

    # نام سطوح معدن
    MINE_LEVELS = {
        "dirt":    "معدن خاک",
        "stone":   "معدن سنگ",
        "iron":    "معدن آهن",
        "gold":    "معدن طلا",
        "crystal": "معدن کریستال",
    }

    # ترتیب ارتقا معدن
    MINE_UPGRADE_ORDER = [
        "dirt",
        "stone",
        "iron",
        "gold",
        "crystal",
    ]

    # نام انواع رویداد
    EVENT_TYPES = {
        "crisis":  "بحران اقتصادی",
        "attack":  "حمله به شهر",
        "festival": "جشن شهر",
        "contest": "رقابت بزرگ",
        "explore": "کشف مشترک",
    }

    # نام نقش‌های شهر
    CITY_ROLES = {
        "owner":  "مالک شهر",
        "admin":  "مدیر شهر",
        "member": "شهروند",
    }

    # نام نقش‌های گیلد
    GUILD_ROLES = {
        "founder": "بنیان‌گذار",
        "officer": "افسر",
        "member":  "عضو",
    }

    # نام وضعیت مأموریت
    MISSION_STATUS = {
        "in_progress": "در جریان",
        "completed":   "تکمیل‌شده",
        "failed":      "شکست‌خورده",
        "expired":     "منقضی‌شده",
    }

    # پیام‌های اِکو (تصادفی نمایش داده می‌شوند)
    ECO_MESSAGES = [
        "صدات توی شهر پیچید",
        "شهر بیدار شد",
        "یه موج تازه",
        "شهر می‌شنوه",
        "اِکوی تو به همه رسید",
        "شهر از صدات لرزید",
        "یه نبض تازه",
    ]

    # پیام‌های واکنش تصادفی ربات
    RANDOM_REACTIONS = [
        "〰️ {name} شهر رو تکون داد",
        "〰️ صدای {name} همه جا پیچید",
        "〰️ {name} یه اثر گذاشت",
        "〰️ {name} در تاریخ شهر ثبت شد",
    ]

    # نام‌های کشف‌های ویژه (تصادفی انتخاب می‌شوند)
    SPECIAL_DISCOVERIES = [
        "یک تونل مخفی",
        "یک گنج قدیمی",
        "یک نقشه رمزآلود",
        "یک اتاق فراموش‌شده",
        "یک مدرک تاریخی",
        "یک آزمایشگاه متروک",
        "یک کتابخانه پنهان",
        "یک خزانه قدیمی",
    ]

    # نام‌های کشف‌های افسانه‌ای
    LEGENDARY_DISCOVERIES = [
        "گنج افسانه‌ای شهر",
        "کریستال جادویی",
        "سنگ فلسفی",
        "نقشه شهرهای گمشده",
        "رمز ابدی شهر",
    ]

    # مدال‌های رتبه‌بندی
    RANK_MEDALS = [
        "🥇",
        "🥈",
        "🥉",
    ]

    # حداقل جمعیت برای برخی رویدادها
    MIN_POPULATION_FOR_EVENTS = 5

    # حداقل اِکو برای واریز به بانک
    MIN_BANK_DEPOSIT = 100

    # حداقل اِکو برای انتقال بین بازیکنان
    MIN_TRANSFER_AMOUNT = 500


# ================================================================
# صادرات
# ================================================================

__all__ = [
    "Settings",
    "settings",
    "GameConstants",
]
