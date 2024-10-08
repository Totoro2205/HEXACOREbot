from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str

    AUTO_TAP: bool = True
    TAPS_CHUNK: list[int] = [15, 20]

    GET_REFERRALS_ACTIVITY: bool = False

    DAILY_REWARD: bool = False
    DAILY_CHECKIN: bool = True
    AUTO_MISSION: bool = True
    AUTO_LVL_UP: bool = True

    PLAY_WALK_GAME: bool = True
    PLAY_SHOOT_GAME: bool = True
    PLAY_RPG_GAME: bool = True
    PLAY_DIRTY_JOB_GAME: bool = True
    PLAY_HURTMEPLEASE_GAME: bool = True

    AUTO_BUY_PASS: bool = True

    SLEEP_TIME: list[int] = [3000, 4600]
    USE_RANDOM_DELAY_IN_RUN: bool = True
    RANDOM_DELAY_IN_RUN: list[int] = [0, 20]

    AUTO_STAKING: bool = True
    STAKING_TYPE: str = 'month'
    BALANCE_TO_SAVE: int = 10_000
    MIN_LVL_TO_STAKE: int = 25
    MIN_STAKE: int = 200

    REF_ID: str = ""

    USE_PROXY_FROM_FILE: bool = False

    MAX_ERRORS: int = 5


settings = Settings()
