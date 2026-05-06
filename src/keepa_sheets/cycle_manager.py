"""
Keepa multi-marketplace cycle manager.

Runs one marketplace per invocation in the fixed rotation:
  US -> CA -> UK -> DE -> repeat

Advancement rule: the active marketplace only advances when ALL are true:
  1. run_sheet_update returns status == "SUCCESS"
  2. result["checkpoint_saved"] is True
  3. result["batch_last_row"] >= result["max_asin_row"]
  4. result["batch_truncated"] is False
  5. dry_run is False

Fail-closed loading: missing file -> default to CA; corrupt/invalid -> RuntimeError.
Dry-run: no cycle state is written.
"""

import datetime
import json
import logging
import os
from zoneinfo import ZoneInfo

_LONDON_TZ = ZoneInfo("Europe/London")

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_SRC_DIR, "..", ".."))
_STATE_DIR = os.path.join(_PROJECT_ROOT, "data", "state")

CYCLE_STATE_FILE = os.path.join(_STATE_DIR, "keepa_cycle_state.json")
LOCK_FILE = os.path.join(_STATE_DIR, "keepa_cycle.lock")

# Fixed authoritative sequence; disk value is stored for inspection only.
SEQUENCE: list[str] = ["US", "CA", "UK", "DE"]
_VALID_MARKETPLACES: frozenset[str] = frozenset(SEQUENCE)
_DEFAULT_ACTIVE = "CA"

logger = logging.getLogger(__name__)


class CycleLockError(RuntimeError):
    """Raised when the cycle lock is already held by another process."""


def _now_str() -> str:
    return datetime.datetime.now(_LONDON_TZ).strftime("%Y-%m-%d %H:%M:%S")


def read_cycle_state() -> dict:
    """Return the current cycle state dict.

    - File absent: return default with active_marketplace="CA".
    - Corrupt JSON or invalid content: raise RuntimeError (fail closed).
    """
    try:
        with open(CYCLE_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {
            "active_marketplace": _DEFAULT_ACTIVE,
            "sequence": list(SEQUENCE),
        }
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Cycle state file contains invalid JSON: {CYCLE_STATE_FILE}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Cycle state file has unexpected format (expected object): {CYCLE_STATE_FILE}"
        )

    active = data.get("active_marketplace")
    if not isinstance(active, str) or not active:
        raise RuntimeError(
            f"Cycle state missing or invalid 'active_marketplace': {CYCLE_STATE_FILE}"
        )
    if active not in _VALID_MARKETPLACES:
        raise RuntimeError(
            f"Cycle state 'active_marketplace' value {active!r} is not a supported "
            f"marketplace (expected one of {sorted(_VALID_MARKETPLACES)}): "
            f"{CYCLE_STATE_FILE}"
        )

    return data


def write_cycle_state(state: dict) -> None:
    """Atomically write cycle state using tmp file + os.replace."""
    os.makedirs(_STATE_DIR, exist_ok=True)
    tmp_path = CYCLE_STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, CYCLE_STATE_FILE)


def next_marketplace(current: str) -> str:
    """Return the marketplace that follows current in SEQUENCE (wraps around)."""
    try:
        idx = SEQUENCE.index(current)
    except ValueError:
        return SEQUENCE[0]
    return SEQUENCE[(idx + 1) % len(SEQUENCE)]


class _Lock:
    """Non-blocking exclusive file lock.

    Uses fcntl.flock on Linux/macOS.
    On Windows (dev), locking is skipped with a warning.
    Raises CycleLockError if the lock is already held.
    """

    def __init__(self, path: str):
        self._path = path
        self._fh = None

    def __enter__(self) -> "_Lock":
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._fh = open(self._path, "w")
        try:
            import fcntl
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            logger.warning(
                "fcntl unavailable (Windows). Single-instance locking skipped."
            )
        except BlockingIOError:
            self._fh.close()
            self._fh = None
            raise CycleLockError(
                "Another keepa-cycle run is already active. "
                f"Lock file: {self._path}"
            )
        return self

    def __exit__(self, *_) -> None:
        if self._fh is not None:
            try:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            except ImportError:
                pass
            self._fh.close()
            self._fh = None


def run_cycle_step(max_asins: int, dry_run: bool) -> dict:
    """Run one update pass for the active marketplace.

    Reads cycle state, calls run_sheet_update for the active marketplace, then
    advances the active marketplace only when all advancement conditions are met.

    Dry-run: calls run_sheet_update with dry_run=True but does not write cycle state.

    Returns the run_sheet_update result dict augmented with:
      cycle_advanced: bool
      next_marketplace: str  (present only when cycle_advanced is True)
    """
    from keepa_sheets.sheet_updater import run_sheet_update

    with _Lock(LOCK_FILE):
        # read_cycle_state raises RuntimeError on corrupt/invalid state;
        # that propagates out without calling run_sheet_update.
        cycle = read_cycle_state()
        active = cycle["active_marketplace"]

        print(f"\n{'=' * 60}")
        print(
            f"Keepa cycle  active={active}  max_asins={max_asins}  "
            f"{'DRY-RUN' if dry_run else 'LIVE'}"
        )
        print(f"{'=' * 60}")

        result = run_sheet_update(
            marketplace=active,
            max_asins=max_asins,
            dry_run=dry_run,
            reset_checkpoint=False,
        )

        if dry_run:
            result["cycle_advanced"] = False
            print(f"\n  Cycle NOT advanced: dry_run=True, no state written")
            return result

        # Evaluate all advancement conditions
        status_ok = result.get("status") == "SUCCESS"
        checkpoint_saved = result.get("checkpoint_saved", False)
        batch_truncated = result.get("batch_truncated", False)
        batch_last = result.get("batch_last_row")
        max_asin = result.get("max_asin_row")
        reached_end = (
            batch_last is not None
            and max_asin is not None
            and batch_last >= max_asin
        )
        may_advance = (
            status_ok
            and checkpoint_saved
            and not batch_truncated
            and reached_end
        )

        now = _now_str()
        cycle["updated_at"] = now
        if status_ok:
            cycle["last_success_at"] = now
        # Always store sequence for inspection
        cycle["sequence"] = list(SEQUENCE)

        if may_advance:
            next_mp = next_marketplace(active)
            reason = (
                f"{active} completed full pass -- "
                f"batch_last_row={batch_last} max_asin_row={max_asin}"
            )
            cycle["active_marketplace"] = next_mp
            cycle["last_completed_marketplace"] = active
            cycle["last_advance_reason"] = reason
            cycle.pop("last_error", None)
            write_cycle_state(cycle)
            result["cycle_advanced"] = True
            result["next_marketplace"] = next_mp
            print(f"\n  Cycle advanced: {active} -> {next_mp}  ({reason})")
        else:
            _log_no_advance_reason(
                active, status_ok, checkpoint_saved, batch_truncated,
                reached_end, batch_last, max_asin,
            )
            cycle["active_marketplace"] = active
            write_cycle_state(cycle)
            result["cycle_advanced"] = False

        return result


def _log_no_advance_reason(
    active: str,
    status_ok: bool,
    checkpoint_saved: bool,
    batch_truncated: bool,
    reached_end: bool,
    batch_last: object,
    max_asin: object,
) -> None:
    parts = []
    if not status_ok:
        parts.append("status != SUCCESS")
    if not checkpoint_saved:
        parts.append("checkpoint_saved=False")
    if batch_truncated:
        parts.append("batch_truncated=True")
    if not reached_end:
        if batch_last is not None and max_asin is not None:
            parts.append(f"batch_last_row={batch_last} < max_asin_row={max_asin}")
        else:
            parts.append("reached_end=False")
    reason = "; ".join(parts) if parts else "conditions not met"
    print(f"\n  Cycle NOT advanced: {active} remains active  ({reason})")
