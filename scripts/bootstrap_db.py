import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import psycopg
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: psycopg. Install with `pip install psycopg[binary]`."
    ) from exc


ROOT_DIR = Path(__file__).resolve().parents[1]

SCHEMA_FILES = [
    "schema_auth_security.sql",
    "schema_school_admin.sql",
    "schema_school_website.sql",
    "schema_staff.sql",
    "schema_notifications.sql",
    "schema_contact_messages.sql",
    "schema_announcements_alerts.sql",
    "schema_online_applications.sql",
    "schema_application_screenings.sql",
    "schema_finance_ops.sql",
    "schema_portal_results.sql",
    "schema_student_ai_features.sql",
    "schema_virtual_call_features.sql",
    "schema_global_virtual_meetings.sql",
]

SEED_FILES = [
    "seed_emr_college_content.sql",
    "seed_limkokwing_content.sql",
    "seed_sifundzani_content.sql",
]


def _resolve_db_url():
    # Preferred explicit DB URL.
    db_url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    if db_url:
        if db_url.startswith(("postgresql://", "postgres://")):
            return db_url
        raise SystemExit(
            "SUPABASE_DB_URL must be a Postgres URL (postgresql://...)."
        )

    # Common fallback for generic Postgres envs.
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url:
        if db_url.startswith(("postgresql://", "postgres://")):
            return db_url
        raise SystemExit(
            "DATABASE_URL is set but is not Postgres. Set SUPABASE_DB_URL to your Supabase Postgres connection string."
        )

    raise SystemExit(
        "No database URL found. Set SUPABASE_DB_URL (recommended) or DATABASE_URL."
    )


def _read_sql_file(filename):
    file_path = ROOT_DIR / filename
    if not file_path.exists():
        raise SystemExit(f"Missing SQL file: {filename}")
    return file_path.read_text(encoding="utf-8")


def _apply_sql_file(conn, filename):
    sql = _read_sql_file(filename)
    with conn.cursor() as cur:
        cur.execute(sql)
    print(f"Applied: {filename}")


def main():
    load_dotenv(ROOT_DIR / ".env")
    db_url = _resolve_db_url()
    include_seeds = (os.getenv("BOOTSTRAP_INCLUDE_SEEDS") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    print("Starting DB bootstrap...")
    with psycopg.connect(db_url, autocommit=False) as conn:
        try:
            for filename in SCHEMA_FILES:
                _apply_sql_file(conn, filename)

            if include_seeds:
                for filename in SEED_FILES:
                    _apply_sql_file(conn, filename)

            conn.commit()
            print("DB bootstrap completed successfully.")
        except Exception:
            conn.rollback()
            raise


if __name__ == "__main__":
    main()
