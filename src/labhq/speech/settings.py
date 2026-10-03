"""Speech limits, read from `LABHQ_SPEECH_*` environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_SPEECH_", extra="ignore")

    # A sentence longer than this cannot be followed by ear.
    max_sentence_words: int = Field(default=40, gt=0)


@lru_cache(maxsize=1)
def get_speech_settings() -> SpeechSettings:
    return SpeechSettings()
