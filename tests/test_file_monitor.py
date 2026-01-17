"""Unit tests for FileMonitor."""

import os
import time
from unittest.mock import MagicMock

from clicknick.data.file_monitor import FILE_MONITOR_INTERVAL_MS, FileMonitor


class TestFileMonitorInit:
    """Tests for FileMonitor initialization."""

    def test_init_with_existing_file(self, tmp_path):
        """FileMonitor captures initial mtime for existing file."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("initial content")
        initial_mtime = os.path.getmtime(test_file)

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        assert monitor.file_path == str(test_file)
        assert monitor._last_mtime == initial_mtime
        assert monitor.is_active is False

    def test_init_with_nonexistent_file(self):
        """FileMonitor handles nonexistent file path."""
        callback = MagicMock()
        monitor = FileMonitor("/nonexistent/path.mdb", callback)

        assert monitor.file_path == "/nonexistent/path.mdb"
        assert monitor._last_mtime == 0.0
        assert monitor.is_active is False

    def test_init_with_none_path(self):
        """FileMonitor handles None file path."""
        callback = MagicMock()
        monitor = FileMonitor(None, callback)

        assert monitor.file_path is None
        assert monitor._last_mtime == 0.0
        assert monitor.is_active is False


class TestFileMonitorStartStop:
    """Tests for starting and stopping file monitoring."""

    def test_start_activates_monitoring(self, tmp_path):
        """start() activates monitoring and schedules first check."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id_123"

        monitor.start(mock_root)

        assert monitor.is_active is True
        mock_root.after.assert_called_once_with(FILE_MONITOR_INTERVAL_MS, monitor._check_modified)

    def test_start_does_nothing_if_already_active(self, tmp_path):
        """start() is idempotent - doesn't schedule twice."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id_123"

        monitor.start(mock_root)
        monitor.start(mock_root)  # Second call

        # Only one after() call
        assert mock_root.after.call_count == 1

    def test_start_does_nothing_with_none_path(self):
        """start() does nothing if file_path is None."""
        callback = MagicMock()
        monitor = FileMonitor(None, callback)

        mock_root = MagicMock()
        monitor.start(mock_root)

        assert monitor.is_active is False
        mock_root.after.assert_not_called()

    def test_stop_deactivates_monitoring(self, tmp_path):
        """stop() deactivates monitoring and cancels scheduled check."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id_123"

        monitor.start(mock_root)
        monitor.stop()

        assert monitor.is_active is False
        mock_root.after_cancel.assert_called_once_with("after_id_123")

    def test_stop_is_safe_when_not_started(self):
        """stop() is safe to call even if not started."""
        callback = MagicMock()
        monitor = FileMonitor("/some/path.mdb", callback)

        # Should not raise
        monitor.stop()
        assert monitor.is_active is False


class TestFileMonitorCheckModified:
    """Tests for file modification detection."""

    def test_check_modified_calls_callback_on_change(self, tmp_path):
        """_check_modified calls callback when file mtime increases."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("initial")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"
        monitor.start(mock_root)

        # Modify the file (ensure mtime changes)
        time.sleep(0.01)
        test_file.write_text("modified content")

        # Trigger the check manually
        monitor._check_modified()

        callback.assert_called_once()

    def test_check_modified_no_callback_if_unchanged(self, tmp_path):
        """_check_modified doesn't call callback if file unchanged."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"
        monitor.start(mock_root)

        # Check without modifying
        monitor._check_modified()

        callback.assert_not_called()

    def test_check_modified_schedules_next_check(self, tmp_path):
        """_check_modified schedules the next check."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"
        monitor.start(mock_root)

        # First after() call is from start()
        assert mock_root.after.call_count == 1

        # Trigger check
        monitor._check_modified()

        # Second after() call is from _check_modified scheduling next
        assert mock_root.after.call_count == 2

    def test_check_modified_does_nothing_when_inactive(self, tmp_path):
        """_check_modified does nothing if monitoring is inactive."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("initial")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        # Modify file but don't start monitoring
        time.sleep(0.01)
        test_file.write_text("modified")

        monitor._check_modified()

        callback.assert_not_called()

    def test_check_modified_handles_missing_file(self, tmp_path):
        """_check_modified handles file being deleted."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"
        monitor.start(mock_root)

        # Delete the file
        os.remove(test_file)

        # Should not raise, should not call callback
        monitor._check_modified()
        callback.assert_not_called()

    def test_check_modified_handles_locked_file(self, tmp_path):
        """_check_modified handles file access errors gracefully."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("content")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"
        monitor.start(mock_root)

        # Simulate file access error by making path invalid after init
        monitor._file_path = "/invalid\x00path"  # Invalid path with null byte

        # Should not raise
        monitor._check_modified()
        callback.assert_not_called()


class TestFileMonitorUpdateMtime:
    """Tests for update_mtime() method."""

    def test_update_mtime_refreshes_stored_time(self, tmp_path):
        """update_mtime() captures current file mtime."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("initial")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        initial_mtime = monitor._last_mtime

        # Modify file
        time.sleep(0.01)
        test_file.write_text("modified")

        # Update mtime
        monitor.update_mtime()

        assert monitor._last_mtime > initial_mtime

    def test_update_mtime_prevents_false_detection(self, tmp_path):
        """update_mtime() after save prevents callback on next check."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("initial")

        callback = MagicMock()
        monitor = FileMonitor(str(test_file), callback)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"
        monitor.start(mock_root)

        # Simulate: we write to file, then call update_mtime
        time.sleep(0.01)
        test_file.write_text("saved by us")
        monitor.update_mtime()

        # Now check - should not trigger callback since we updated mtime
        monitor._check_modified()
        callback.assert_not_called()

    def test_update_mtime_handles_missing_file(self):
        """update_mtime() handles missing file gracefully."""
        callback = MagicMock()
        monitor = FileMonitor("/nonexistent/file.mdb", callback)

        # Should not raise
        monitor.update_mtime()
        assert monitor._last_mtime == 0.0

    def test_update_mtime_handles_none_path(self):
        """update_mtime() handles None path gracefully."""
        callback = MagicMock()
        monitor = FileMonitor(None, callback)

        # Should not raise
        monitor.update_mtime()
        assert monitor._last_mtime == 0.0


class TestFileMonitorIntegration:
    """Integration-style tests for FileMonitor."""

    def test_full_lifecycle(self, tmp_path):
        """Test complete start -> detect change -> stop lifecycle."""
        test_file = tmp_path / "test.mdb"
        test_file.write_text("initial")

        changes_detected = []

        def on_change():
            changes_detected.append(True)

        monitor = FileMonitor(str(test_file), on_change)

        mock_root = MagicMock()
        mock_root.after.return_value = "after_id"

        # Start monitoring
        monitor.start(mock_root)
        assert monitor.is_active

        # No change yet
        monitor._check_modified()
        assert len(changes_detected) == 0

        # Modify file
        time.sleep(0.01)
        test_file.write_text("modified")

        # Detect change
        monitor._check_modified()
        assert len(changes_detected) == 1

        # Stop monitoring
        monitor.stop()
        assert not monitor.is_active

        # Further modifications not detected (inactive)
        time.sleep(0.01)
        test_file.write_text("more changes")
        monitor._check_modified()
        assert len(changes_detected) == 1  # Still 1
