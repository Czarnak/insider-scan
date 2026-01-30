from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SourceToggles:
    openinsider: bool = True
    secform4: bool = True


@dataclass(frozen=True)
class SecOverrides:
    user_agent: str | None = None
    throttle_s: float | None = None
    timeout_s: float | None = None


@dataclass(frozen=True)
class AppConfig:
    sources: SourceToggles = SourceToggles()
    tickers: list[str] = None  # type: ignore
    sec: SecOverrides = SecOverrides()

    def __post_init__(self):
        # dataclasses with frozen=True: use object.__setattr__
        if self.tickers is None:
            object.__setattr__(self, "tickers", [])


def _as_bool(x: Any, default: bool) -> bool:
    if x is None:
        return default
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        # no config -> defaults
        return AppConfig(sources=SourceToggles(True, True), tickers=[], sec=SecOverrides())

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    sources_raw = data.get("sources", {}) or {}
    tickers_raw = data.get("tickers", []) or []
    sec_raw = data.get("sec", {}) or {}

    sources = SourceToggles(
        openinsider=_as_bool(sources_raw.get("openinsider"), True),
        secform4=_as_bool(sources_raw.get("secform4"), True),
    )

    tickers = []
    for t in tickers_raw:
        if t is None:
            continue
        tt = str(t).strip().upper()
        if tt:
            tickers.append(tt)

    sec = SecOverrides(
        user_agent=(str(sec_raw.get("user_agent")).strip() if sec_raw.get("user_agent") else None),
        throttle_s=(float(sec_raw["throttle_s"]) if sec_raw.get("throttle_s") is not None else None),
        timeout_s=(float(sec_raw["timeout_s"]) if sec_raw.get("timeout_s") is not None else None),
    )

    return AppConfig(sources=sources, tickers=tickers, sec=sec)
