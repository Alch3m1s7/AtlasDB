"""CLI dispatch tests for update-keepa-sheets-cycle.

Verifies that main.py correctly routes the command to cycle_manager.run_cycle_step,
passes arguments, exits appropriately, and sanitizes exception output.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

import keepa_sheets.cycle_manager as cm


# Patch target for run_cycle_step as imported by main.py
_PATCH_CYCLE = "keepa_sheets.cycle_manager.run_cycle_step"


def _run_main(argv: list[str]) -> int:
    """Run main() with the given sys.argv, return the SystemExit code (0 if no exit)."""
    import importlib
    import src.main as main_mod

    with patch("sys.argv", ["main.py"] + argv):
        try:
            main_mod.main()
            return 0
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0


class TestCycleCliDispatch:
    def test_dispatch_calls_run_cycle_step_with_max_asins(self, capsys):
        success_result = {
            "status": "SUCCESS",
            "marketplace": "CA",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": True,
            "batch_truncated": False,
            "cycle_advanced": False,
        }
        with patch(_PATCH_CYCLE, return_value=success_result) as mock_step:
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "90"])
        assert code == 0
        mock_step.assert_called_once_with(max_asins=90, dry_run=False)

    def test_dispatch_passes_dry_run_flag(self, capsys):
        dry_result = {
            "status": "DRY_RUN",
            "marketplace": "CA",
            "batch_last_row": 400,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
            "cycle_advanced": False,
        }
        with patch(_PATCH_CYCLE, return_value=dry_result) as mock_step:
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "10", "--dry-run"])
        assert code == 0
        mock_step.assert_called_once_with(max_asins=10, dry_run=True)

    def test_cycle_lock_error_exits_nonzero_with_safe_message(self, capsys):
        with patch(_PATCH_CYCLE, side_effect=cm.CycleLockError("lock held")):
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "10"])
        assert code == 1
        out = capsys.readouterr().out
        assert "already active" in out
        # Must not print raw exception internals
        assert "lock held" not in out

    def test_runtime_error_exits_nonzero_with_safe_message(self, capsys):
        with patch(_PATCH_CYCLE, side_effect=RuntimeError("SECRET_KEY=abc123")):
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "10"])
        assert code == 1
        out = capsys.readouterr().out
        # Raw exception text must not appear in output
        assert "SECRET_KEY" not in out
        assert "abc123" not in out
        assert "log file" in out or "failed" in out.lower()

    def test_unhandled_exception_exits_nonzero_with_safe_message(self, capsys):
        with patch(_PATCH_CYCLE, side_effect=Exception("unexpected internal error")):
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "10"])
        assert code == 1
        out = capsys.readouterr().out
        assert "unexpected internal error" not in out

    def test_nothing_to_do_exits_zero(self, capsys):
        nothing_result = {
            "status": "NOTHING_TO_DO",
            "marketplace": "CA",
            "batch_last_row": None,
            "max_asin_row": 400,
            "checkpoint_saved": False,
            "batch_truncated": False,
            "cycle_advanced": False,
        }
        with patch(_PATCH_CYCLE, return_value=nothing_result):
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "10"])
        assert code == 0


class TestMaxAsinsValidation:
    def test_zero_max_asins_exits_nonzero(self, capsys):
        with patch(_PATCH_CYCLE) as mock_step:
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "0"])
        assert code != 0
        mock_step.assert_not_called()
        out = capsys.readouterr().out
        assert "--max-asins" in out

    def test_negative_max_asins_exits_nonzero(self, capsys):
        with patch(_PATCH_CYCLE) as mock_step:
            code = _run_main(["update-keepa-sheets-cycle", "--max-asins", "-1"])
        assert code != 0
        mock_step.assert_not_called()
        out = capsys.readouterr().out
        assert "--max-asins" in out
