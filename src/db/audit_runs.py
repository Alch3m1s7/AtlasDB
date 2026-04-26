import uuid

from db.db_connection import get_connection

_INSERT_SQL = """
INSERT INTO audit.ingestion_runs (
    run_id, source, report_type, status
) VALUES (%s, %s, %s, 'STARTED')
"""

_FINISH_SQL = """
UPDATE audit.ingestion_runs SET
    status        = %s,
    finished_at   = now(),
    report_id     = %s,
    source_file   = %s,
    parsed_rows   = %s,
    expected_rows = %s,
    inserted_rows = %s,
    skipped_rows  = %s,
    snapshot_id   = %s
WHERE run_id = %s
"""

_FAIL_SQL = """
UPDATE audit.ingestion_runs SET
    status        = 'FAILED',
    finished_at   = now(),
    report_id     = %s,
    error_message = %s
WHERE run_id = %s
"""


def start_ingestion_run(source: str, report_type: str | None = None) -> str:
    run_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(_INSERT_SQL, (run_id, source, report_type))
        conn.commit()
    finally:
        conn.close()
    return run_id


def finish_ingestion_run(
    run_id: str,
    status: str,
    report_id: str | None = None,
    source_file: str | None = None,
    parsed_rows: int | None = None,
    expected_rows: int | None = None,
    inserted_rows: int | None = None,
    skipped_rows: int | None = None,
    snapshot_id: str | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(_FINISH_SQL, (
            status, report_id, source_file,
            parsed_rows, expected_rows, inserted_rows, skipped_rows,
            snapshot_id, run_id,
        ))
        conn.commit()
    finally:
        conn.close()


def fail_ingestion_run(
    run_id: str,
    error_message: str,
    report_id: str | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(_FAIL_SQL, (report_id, error_message, run_id))
        conn.commit()
    finally:
        conn.close()
