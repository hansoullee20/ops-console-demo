"""Seeding the canonical fictional demo dataset into SQLite.

Standard library only — no FastAPI, no pydantic. The GitHub Pages deploy runs
this to build the public snapshot, and must not need `pip install`.
"""

from app.seed.demo_dataset import seed_demo_database  # noqa: F401
