"""Vercel entry point: every route of the bot is served by this one Python function (see ../vercel.json)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import create_app  # noqa: E402

app = create_app()
