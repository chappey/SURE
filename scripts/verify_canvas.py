#!/usr/bin/env python3
"""Verify Canvas API connectivity (loads .env from project root)."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: F401 — loads PROJECT_ROOT/.env
from canvas_client import get_canvas

canvas = get_canvas()
user = canvas.get_current_user()
print(f"Connected as {user.name} (id={user.id})")
accounts = list(canvas.get_accounts())
print(f"Accounts visible: {len(accounts)}")
