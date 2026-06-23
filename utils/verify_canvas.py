#!/usr/bin/env python3
"""Verify Canvas API connectivity (loads config from app.config)."""

import sys
from pathlib import Path

# Add project root to path to resolve absolute app.* imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.canvas import get_canvas

def main():
    canvas = get_canvas()
    user = canvas.get_current_user()
    print(f"Connected as {user.name} (id={user.id})")
    accounts = list(canvas.get_accounts())
    print(f"Accounts visible: {len(accounts)}")

if __name__ == "__main__":
    main()
