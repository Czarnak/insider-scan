from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = os.getenv("INSIDER_SCAN_CACHE_DIR", str(PROJECT_ROOT / "cache"))
OUTPUT_DIR = os.getenv("INSIDER_SCAN_OUTPUT_DIR", str(PROJECT_ROOT / "outputs"))
LOG_DIR = os.getenv("INSIDER_SCAN_LOG_DIR", str(PROJECT_ROOT / "logs"))

Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class HttpConfig:
    timeout_s: float = 20.0
    throttle_s: float = 0.35  # SEC guidance: be gentle
    max_retries: int = 4

    # IMPORTANT: SEC requires identifiable User-Agent. Use env var to personalize:
    # export SEC_USER_AGENT="YourName your.email@domain.com"
    user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "InsiderScan/0.1 (contact: example@example.com) - please set SEC_USER_AGENT env var",
    )


HTTP = HttpConfig()

# Sources base URLs
OPENINSIDER_BASE = "https://openinsider.com"
SECFORM4_BASE = "https://secform4.com"
SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"
