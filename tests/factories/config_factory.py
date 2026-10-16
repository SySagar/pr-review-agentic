from __future__ import annotations

from harness.config import Settings


def build_settings(**overrides) -> Settings:
    if "_env" not in overrides:
        return Settings(**overrides)
    return Settings(**overrides)
