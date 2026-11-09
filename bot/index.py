"""Vercel entry point (FastAPI preset): Vercel looks for an `app` variable in index.py at the project root.

All routes (/health, /orders, /webhook) are served by this app. Set PROCESS_INLINE=true on Vercel.
"""

from app.main import create_app

app = create_app()
