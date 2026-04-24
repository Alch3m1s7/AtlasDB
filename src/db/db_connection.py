import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in environment")
    return url


def get_connection() -> psycopg.Connection:
    return psycopg.connect(get_database_url())
