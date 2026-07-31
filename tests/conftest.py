"""Shared test configuration for deterministic headless Qt execution."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
