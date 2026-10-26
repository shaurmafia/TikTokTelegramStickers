"""Per-file conversion reports (JSON) — settings, hashes, metadata,
warnings, and validator results. Written even for failures."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict


@dataclass
class ConversionReport:
    source_path: str = ""
    source_sha256: str = ""
    original_copy_path: str = ""
    output_path: str = ""
    output_sha256: str = ""
    profile: str = ""
    quality_mode: str = ""
    source_info: dict = field(default_factory=dict)
    output_info: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    attempt_notes: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    telegram_ready: bool = False
    status: str = "pending"          # ok | failed | needs_review | cancelled
    error: str = ""
    started_utc: str = field(default_factory=lambda: time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    duration_s: float = 0.0
    app_version: str = "0.2.0"

    def to_dict(self):
        return asdict(self)

    def save(self, reports_dir: str) -> str:
        os.makedirs(reports_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(self.source_path or "job"))[0][:80]
        path = os.path.join(reports_dir, f"{stem}-{self.started_utc.replace(':', '')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return path
