"""运行期配置（全部来自环境变量，带默认值）。"""

from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "乐谱反复路径展开 API")
        self.max_expansion_steps: int = int(os.getenv("MAX_EXPANSION_STEPS", "100000"))
        self.default_max_steps: int = int(os.getenv("DEFAULT_MAX_STEPS", "10000"))

        if self.max_expansion_steps < 1:
            raise ValueError("MAX_EXPANSION_STEPS 必须为正整数")
        if self.default_max_steps > self.max_expansion_steps:
            raise ValueError("DEFAULT_MAX_STEPS 不能大于 MAX_EXPANSION_STEPS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
