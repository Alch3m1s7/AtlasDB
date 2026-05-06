"""Unit tests for keepa_sheets.cycle_manager.

All external calls (run_sheet_update, read_cycle_state, write_cycle_state, _Lock)
are mocked. No Keepa API, Google Sheets, database, or file-system I/O occurs.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

import keepa_sheets.cycle_manager as cm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success_result(
    batch_last: int,
    max_asin: int,
    *,
    checkpoint_saved: bool = True,
    batch_truncated: bool = False,
) -> dict:
    return {
        "status": "SUCCESS",
        "marketplace": "CA",
        "batch_last_row": batch_last,
        "max_asin_row": max_asin,
        "checkpoint_saved": checkpoint_saved,
        "batch_truncated": batch_truncated,
        "next_row": batch_last + 1,
        "cells_written": 5,
    }


def _make_cycle_state(active: str) -> dict:
    return {"active_marketplace": active, "sequence": list(cm.SEQUENCE)}


def _no_op_lock():
    lock = MagicMock()
    lock.__enter__ = MagicMock(return_value=lock)
    lock.__exit__ = MagicMock(return_value=False)
    return lock


# Patch targets
_PATCH_RUN = "keepa_sheets.sheet_updater.run_sheet_update"
_PATCH_READ = "keepa_sheets.cycle_manager.read_cycle_state"
_PATCH_WRITE = "keepa_sheets.cycle_manager.write_cycle_state"
_PATCH_LOCK = "keepa_sheets.cycle_manager._Lock"


# ---------------------------------------------------------------------------
# next_marketplace
# ---------------------------------------------------------------------------

class TestNextMarketplace:
    def test_us_to_ca(self):
        assert cm.next_marketplace("US") == "CA"

    def test_ca_to_uk(self):
        assert cm.next_marketplace("CA") == "UK"

    def test_uk_to_de(self):
        assert cm.next_marketplace("UK") == "DE"

    def test_de_wraps_to_us(self):
        assert cm.next_marketplace("DE") == "US"

    def test_unknown_falls_back_to_first(self):
        assert cm.next_marketplace("XX") == "US"


# ---------------------------------------------------------------------------
# read_cycle_state: fail-closed behaviour
# ---------------------------------------------------------------------------

class TestReadCycleState:
    def test_missing_file_defaults_to_ca(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cm, "CYCLE_STATE_FILE", str(tmp_path / "absent.json"))
        state = cm.read_cycle_state()
        assert state["active_marketplace"] == "CA"

    def test_corrupt_json_raises(self, tmp_path, monkeypatch):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(cm, "CYCLE_STATE_FILE", str(p))
        with pytest.raises(RuntimeError, match="invalid JSON"):
            cm.read_cycle_state()

    def test_non_dict_raises(self, tmp_path, monkeypatch):
        p = tmp_path / "list.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        monkeypatch.setattr(cm, "CYCLE_STATE_FILE", str(p))
        with pytest.raises(RuntimeError, match="unexpected format"):
            cm.read_cycle_state()

    def test_missing_active_marketplace_raises(self, tmp_path, monkeypatch):
        p = tmp_path / "no_active.json"
        p.write_text(json.dumps({"sequence": cm.SEQUENCE}), encoding="utf-8")
        monkeypatch.setattr(cm, "CYCLE_STATE_FILE", str(p))
        with pytest.raises(RuntimeError, match="missing or invalid"):
            cm.read_cycle_state()

    def test_invalid_marketplace_value_raises(self, tmp_path, monkeypatch):
        p = tmp_path / "bad_mp.json"
        p.write_text(json.dumps({"active_marketplace": "AU"}), encoding="utf-8")
        monkeypatch.setattr(cm, "CYCLE_STATE_FILE", str(p))
        with pytest.raises(RuntimeError, match="not a supported marketplace"):
            cm.read_cycle_state()

    def test_valid_file_returned(self, tmp_path, monkeypatch):
        p = tmp_path / "good.json"
        p.write_text(json.dumps({"active_marketplace": "DE"}), encoding="utf-8")
        monkeypatch.setattr(cm, "CYCLE_STATE_FILE", str(p))
        state = cm.read_cycle_state()
        assert state["active_marketplace"] == "DE"


# ---------------------------------------------------------------------------
# run_cycle_step: corrupt state blocks run_sheet_update
# ---------------------------------------------------------------------------

class TestCorruptStateBlocksRun:
    def test_corrupt_state_raises_before_run(self):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, side_effect=RuntimeError("Cycle state file contains invalid JSON")),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN) as mock_run,
        ):
            with pytest.raises(RuntimeError, match="invalid JSON"):
                cm.run_cycle_step(max_asins=10, dry_run=False)
        mock_run.assert_not_called()
        mock_write.assert_not_called()

    def test_invalid_active_marketplace_raises_before_run(self):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, side_effect=RuntimeError("not a supported marketplace")),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN) as mock_run,
        ):
            with pytest.raises(RuntimeError, match="not a supported marketplace"):
                cm.run_cycle_step(max_asins=10, dry_run=False)
        mock_run.assert_not_called()
        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# run_cycle_step: advancement conditions
# ---------------------------------------------------------------------------

class TestAdvancement:
    def _run(self, result, active="CA", dry_run=False):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state(active)),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=result),
        ):
            out = cm.run_cycle_step(max_asins=10, dry_run=dry_run)
        return out, mock_write

    def test_advances_when_all_conditions_met(self):
        result = _success_result(batch_last=400, max_asin=400)
        out, mock_write = self._run(result, active="CA")
        assert out["cycle_advanced"] is True
        assert out["next_marketplace"] == "UK"
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "UK"
        assert written["last_completed_marketplace"] == "CA"

    def test_does_not_advance_on_dry_run(self):
        result = _success_result(batch_last=400, max_asin=400)
        out, mock_write = self._run(result, dry_run=True)
        assert out["cycle_advanced"] is False
        mock_write.assert_not_called()

    def test_does_not_advance_when_checkpoint_not_saved(self):
        result = _success_result(batch_last=400, max_asin=400, checkpoint_saved=False)
        out, mock_write = self._run(result)
        assert out["cycle_advanced"] is False
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "CA"

    def test_does_not_advance_when_batch_short_of_end(self):
        result = _success_result(batch_last=350, max_asin=400)
        out, mock_write = self._run(result)
        assert out["cycle_advanced"] is False
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "CA"

    def test_does_not_advance_on_non_success_status(self):
        result = {
            "status": "ERROR",
            "marketplace": "CA",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
        }
        out, mock_write = self._run(result)
        assert out["cycle_advanced"] is False
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "CA"

    def test_does_not_advance_when_batch_last_row_is_none(self):
        result = _success_result(batch_last=400, max_asin=400)
        result["batch_last_row"] = None
        out, _ = self._run(result)
        assert out["cycle_advanced"] is False

    def test_does_not_advance_when_max_asin_row_is_none(self):
        result = _success_result(batch_last=400, max_asin=400)
        result["max_asin_row"] = None
        out, _ = self._run(result)
        assert out["cycle_advanced"] is False

    def test_does_not_advance_on_nothing_to_do(self):
        result = {
            "status": "NOTHING_TO_DO",
            "marketplace": "CA",
            "batch_last_row": None,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
        }
        out, _ = self._run(result)
        assert out["cycle_advanced"] is False

    def test_does_not_advance_on_success_no_op(self):
        """SUCCESS with cells_written=0 and checkpoint_saved=False must not advance."""
        result = {
            "status": "SUCCESS",
            "marketplace": "CA",
            "cells_written": 0,
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
        }
        out, _ = self._run(result)
        assert out["cycle_advanced"] is False

    def test_de_wraps_to_us(self):
        result = _success_result(batch_last=500, max_asin=500)
        out, mock_write = self._run(result, active="DE")
        assert out["cycle_advanced"] is True
        assert out["next_marketplace"] == "US"
        assert mock_write.call_args[0][0]["active_marketplace"] == "US"

    def test_us_advances_to_ca(self):
        result = _success_result(batch_last=300, max_asin=300)
        out, mock_write = self._run(result, active="US")
        assert out["cycle_advanced"] is True
        assert out["next_marketplace"] == "CA"


# ---------------------------------------------------------------------------
# Token shortage / truncated batch never advances
# ---------------------------------------------------------------------------

class TestTokenShortageTruncation:
    def _run(self, result, active="CA"):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state(active)),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=result),
        ):
            out = cm.run_cycle_step(max_asins=10, dry_run=False)
        return out, mock_write

    def test_batch_truncated_blocks_advance_even_if_batch_last_row_equals_max(self):
        """batch_truncated=True must prevent advancement even when rows appear complete."""
        result = _success_result(
            batch_last=400, max_asin=400,
            checkpoint_saved=True, batch_truncated=True,
        )
        out, mock_write = self._run(result)
        assert out["cycle_advanced"] is False
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "CA"

    def test_batch_not_truncated_can_advance(self):
        result = _success_result(
            batch_last=400, max_asin=400,
            checkpoint_saved=True, batch_truncated=False,
        )
        out, _ = self._run(result)
        assert out["cycle_advanced"] is True

    def test_truncated_batch_with_short_reach_does_not_advance(self):
        result = _success_result(
            batch_last=350, max_asin=400,
            checkpoint_saved=True, batch_truncated=True,
        )
        out, _ = self._run(result)
        assert out["cycle_advanced"] is False


# ---------------------------------------------------------------------------
# Dry-run does not write state
# ---------------------------------------------------------------------------

class TestDryRunNoStateWrite:
    def test_dry_run_never_writes_cycle_state(self):
        lock_instance = _no_op_lock()
        dry_run_result = {
            "status": "DRY_RUN",
            "marketplace": "CA",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
        }
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state("CA")),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=dry_run_result),
        ):
            out = cm.run_cycle_step(max_asins=10, dry_run=True)
        mock_write.assert_not_called()
        assert out["cycle_advanced"] is False

    def test_dry_run_live_like_result_also_no_write(self):
        """Even if run_sheet_update returned SUCCESS/checkpoint_saved, dry-run wins."""
        lock_instance = _no_op_lock()
        result = _success_result(batch_last=400, max_asin=400)
        result["status"] = "DRY_RUN"
        result["checkpoint_saved"] = False
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state("CA")),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=result),
        ):
            out = cm.run_cycle_step(max_asins=10, dry_run=True)
        mock_write.assert_not_called()
        assert out["cycle_advanced"] is False


# ---------------------------------------------------------------------------
# Lock blocks run_sheet_update
# ---------------------------------------------------------------------------

class TestLockBehaviour:
    def test_lock_failure_prevents_run_sheet_update(self):
        failing_lock = MagicMock()
        failing_lock.__enter__ = MagicMock(side_effect=cm.CycleLockError("already active"))
        failing_lock.__exit__ = MagicMock(return_value=False)
        with (
            patch(_PATCH_LOCK, return_value=failing_lock),
            patch(_PATCH_RUN) as mock_run,
            patch(_PATCH_WRITE) as mock_write,
        ):
            with pytest.raises(cm.CycleLockError):
                cm.run_cycle_step(max_asins=10, dry_run=False)
        mock_run.assert_not_called()
        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------

class TestExceptionPropagation:
    def test_propagates_runtime_error_from_run_sheet_update(self):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state("CA")),
            patch(_PATCH_WRITE),
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, side_effect=RuntimeError("Keepa query failed")),
        ):
            with pytest.raises(RuntimeError, match="Keepa query failed"):
                cm.run_cycle_step(max_asins=10, dry_run=False)

    def test_does_not_write_cycle_state_on_exception(self):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state("CA")),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, side_effect=RuntimeError("boom")),
        ):
            with pytest.raises(RuntimeError):
                cm.run_cycle_step(max_asins=10, dry_run=False)
        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# Passthrough: reset_checkpoint always False
# ---------------------------------------------------------------------------

class TestPassthrough:
    def test_always_passes_reset_checkpoint_false(self):
        result = _success_result(batch_last=400, max_asin=400)
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state("CA")),
            patch(_PATCH_WRITE),
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=result) as mock_run,
        ):
            cm.run_cycle_step(max_asins=50, dry_run=False)
        mock_run.assert_called_once_with(
            marketplace="CA",
            max_asins=50,
            dry_run=False,
            reset_checkpoint=False,
        )

    def test_passes_dry_run_true_to_run_sheet_update(self):
        result = {
            "status": "DRY_RUN",
            "marketplace": "US",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
        }
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state("US")),
            patch(_PATCH_WRITE),
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=result) as mock_run,
        ):
            cm.run_cycle_step(max_asins=10, dry_run=True)
        mock_run.assert_called_once_with(
            marketplace="US",
            max_asins=10,
            dry_run=True,
            reset_checkpoint=False,
        )


# ---------------------------------------------------------------------------
# skipped_asins policy
# ---------------------------------------------------------------------------

class TestSkippedAsinPolicy:
    """Document that skipped_asins do not block cycle advancement.

    Policy: permanent Keepa data gaps (missing products) must not trap the
    cycle on one marketplace forever. When all five advancement conditions
    are satisfied, the cycle advances regardless of skipped_asins.
    Skipped ASINs will be retried on the next full pass after checkpoint
    wraparound.

    Advancement conditions (all must be true):
      1. status == "SUCCESS"
      2. checkpoint_saved is True
      3. batch_last_row >= max_asin_row
      4. batch_truncated is False
      5. dry_run is False
    """

    def _run(self, result, active="CA", dry_run=False):
        lock_instance = _no_op_lock()
        with (
            patch(_PATCH_READ, return_value=_make_cycle_state(active)),
            patch(_PATCH_WRITE) as mock_write,
            patch(_PATCH_LOCK, return_value=lock_instance),
            patch(_PATCH_RUN, return_value=result),
        ):
            out = cm.run_cycle_step(max_asins=10, dry_run=dry_run)
        return out, mock_write

    def test_skipped_asins_do_not_block_advancement(self):
        """Cycle advances even when some ASINs had no Keepa data."""
        result = {
            "status": "SUCCESS",
            "marketplace": "CA",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": True,
            "batch_truncated": False,
            "skipped_asins": ["B000000001", "B000000002"],
            "cells_written": 8,
        }
        out, mock_write = self._run(result)
        assert out["cycle_advanced"] is True
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "UK"

    def test_skipped_asins_with_checkpoint_not_saved_still_blocks(self):
        """checkpoint_saved=False blocks even when all other conditions are met."""
        result = {
            "status": "SUCCESS",
            "marketplace": "CA",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
            "skipped_asins": ["B000000001"],
            "cells_written": 0,
        }
        out, mock_write = self._run(result)
        assert out["cycle_advanced"] is False
        written = mock_write.call_args[0][0]
        assert written["active_marketplace"] == "CA"
