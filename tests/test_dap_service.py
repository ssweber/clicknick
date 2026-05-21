"""Tests for DapService DAP wire protocol and state management."""

from __future__ import annotations

import io
import json

from clicknick.services.dap_service import DapService, SimState, _coerce_string


def _make_dap_message(msg: dict) -> bytes:
    """Encode a DAP message with Content-Length framing."""
    payload = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
    return header + payload


class TestDapWireProtocol:
    def test_write_message_format(self):
        service = DapService()
        buf = io.BytesIO()

        class FakeProc:
            stdin = buf
            stdout = io.BytesIO()

        service._proc = FakeProc()
        msg = {"seq": 1, "type": "request", "command": "initialize"}
        service._write_message(msg)

        raw = buf.getvalue()
        assert raw.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in raw

        header_end = raw.index(b"\r\n\r\n") + 4
        body = json.loads(raw[header_end:])
        assert body["command"] == "initialize"

    def test_read_message_parses_correctly(self):
        service = DapService()
        msg = {"seq": 1, "type": "response", "command": "initialize", "success": True}
        raw = _make_dap_message(msg)

        class FakeProc:
            stdin = io.BytesIO()
            stdout = io.BytesIO(raw)

        service._proc = FakeProc()
        result = service._read_message()
        assert result is not None
        assert result["command"] == "initialize"
        assert result["success"] is True

    def test_read_message_returns_none_on_eof(self):
        service = DapService()

        class FakeProc:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b"")

        service._proc = FakeProc()
        result = service._read_message()
        assert result is None


class TestDapRequestResponse:
    def test_send_request_increments_seq(self):
        service = DapService()
        buf = io.BytesIO()

        class FakeProc:
            stdin = buf
            stdout = io.BytesIO()

        service._proc = FakeProc()

        seq1 = service._send_request("initialize")
        seq2 = service._send_request("launch", {"program": "test.py"})
        assert seq2 > seq1

    def test_handle_response_signals_waiter(self):
        service = DapService()
        buf = io.BytesIO()

        class FakeProc:
            stdin = buf
            stdout = io.BytesIO()

        service._proc = FakeProc()

        seq = service._send_request("initialize")

        response = {
            "seq": 100,
            "type": "response",
            "request_seq": seq,
            "command": "initialize",
            "success": True,
            "body": {"supportsConfigurationDoneRequest": True},
        }
        service._handle_response(response)

        result = service._wait_response(seq, timeout=1.0)
        assert result is not None
        assert result["success"] is True


class TestDapEventHandling:
    def test_stopped_entry_sets_state(self):
        states = []
        service = DapService(on_state=lambda s, e: states.append(s))
        service._handle_event(
            {
                "type": "event",
                "event": "stopped",
                "body": {"reason": "entry", "threadId": 1},
            }
        )
        assert SimState.STOPPED in states

    def test_stopped_pause_sets_paused(self):
        states = []
        service = DapService(on_state=lambda s, e: states.append(s))
        service._handle_event(
            {
                "type": "event",
                "event": "stopped",
                "body": {"reason": "pause", "threadId": 1},
            }
        )
        assert SimState.PAUSED in states

    def test_scan_frame_extracts_tag_values(self):
        received_tags = []
        service = DapService(on_tags=lambda t: received_tags.append(t))

        service._handle_event(
            {
                "type": "event",
                "event": "pyrungScanFrame",
                "body": {
                    "scanId": 42,
                    "trace": {
                        "tagValues": {"Motor": True, "Counter": 5},
                        "tagTypes": {"Motor": "bool", "Counter": "int"},
                        "tagHints": {},
                        "tagGroups": {},
                    },
                    "changes": [],
                    "monitors": [],
                    "snapshots": [],
                    "outputs": [],
                },
            }
        )

        assert len(received_tags) == 1
        assert received_tags[0]["Motor"] is True
        assert received_tags[0]["Counter"] == 5

    def test_scan_frame_dispatches_changes(self):
        received_changes = []
        service = DapService(on_changes=lambda c: received_changes.append(c))

        service._handle_event(
            {
                "type": "event",
                "event": "pyrungScanFrame",
                "body": {
                    "scanId": 42,
                    "trace": {"tagValues": {}, "tagTypes": {}, "tagHints": {}, "tagGroups": {}},
                    "changes": [
                        {"tag": "Motor", "previous": "False", "current": "True"},
                    ],
                    "monitors": [],
                    "snapshots": [],
                    "outputs": [],
                },
            }
        )

        assert len(received_changes) == 1
        assert received_changes[0][0]["tag"] == "Motor"

    def test_scan_frame_caches_tag_metadata(self):
        service = DapService()
        service._handle_event(
            {
                "type": "event",
                "event": "pyrungScanFrame",
                "body": {
                    "scanId": 1,
                    "trace": {
                        "tagValues": {},
                        "tagTypes": {"Motor": "bool"},
                        "tagHints": {"Motor": {"readonly": True}},
                        "tagGroups": {"Block1": ["Motor", "Pump"]},
                    },
                    "changes": [],
                    "monitors": [],
                    "snapshots": [],
                    "outputs": [],
                },
            }
        )

        assert service.tag_types == {"Motor": "bool"}
        assert service.tag_hints == {"Motor": {"readonly": True}}
        assert service.tag_groups == {"Block1": ["Motor", "Pump"]}

    def test_terminated_sets_idle(self):
        states = []
        service = DapService(on_state=lambda s, e: states.append(s))
        service._handle_event(
            {
                "type": "event",
                "event": "terminated",
                "body": {},
            }
        )
        assert SimState.IDLE in states


class TestCoerceString:
    def test_bool_true(self):
        assert _coerce_string("True", "bool") is True

    def test_bool_false(self):
        assert _coerce_string("False", "bool") is False

    def test_bool_one(self):
        assert _coerce_string("1", "bool") is True

    def test_bool_zero(self):
        assert _coerce_string("0", "bool") is False

    def test_int(self):
        assert _coerce_string("42", "int") == 42

    def test_int_negative(self):
        assert _coerce_string("-7", "int") == -7

    def test_dint(self):
        assert _coerce_string("100000", "dint") == 100000

    def test_word(self):
        assert _coerce_string("65535", "word") == 65535

    def test_real(self):
        assert _coerce_string("3.14", "real") == 3.14

    def test_char_returns_string(self):
        assert _coerce_string("A", "char") == "A"

    def test_unknown_type_returns_string(self):
        assert _coerce_string("hello", "") == "hello"

    def test_invalid_int_returns_string(self):
        assert _coerce_string("not_a_number", "int") == "not_a_number"

    def test_invalid_real_returns_string(self):
        assert _coerce_string("not_a_number", "real") == "not_a_number"


class TestCoerceTagValues:
    def test_string_bools_coerced(self):
        received_tags = []
        service = DapService(on_tags=lambda t: received_tags.append(t))

        service._handle_event(
            {
                "type": "event",
                "event": "pyrungScanFrame",
                "body": {
                    "scanId": 1,
                    "trace": {
                        "tagValues": {"Motor": "False", "Pump": "True", "Counter": "5"},
                        "tagTypes": {"Motor": "bool", "Pump": "bool", "Counter": "int"},
                        "tagHints": {},
                        "tagGroups": {},
                    },
                    "changes": [],
                    "monitors": [],
                    "snapshots": [],
                    "outputs": [],
                },
            }
        )

        assert len(received_tags) == 1
        assert received_tags[0]["Motor"] is False
        assert received_tags[0]["Pump"] is True
        assert received_tags[0]["Counter"] == 5

    def test_native_values_passed_through(self):
        received_tags = []
        service = DapService(on_tags=lambda t: received_tags.append(t))

        service._handle_event(
            {
                "type": "event",
                "event": "pyrungScanFrame",
                "body": {
                    "scanId": 1,
                    "trace": {
                        "tagValues": {"Motor": False, "Counter": 42},
                        "tagTypes": {"Motor": "bool", "Counter": "int"},
                        "tagHints": {},
                        "tagGroups": {},
                    },
                    "changes": [],
                    "monitors": [],
                    "snapshots": [],
                    "outputs": [],
                },
            }
        )

        assert received_tags[0]["Motor"] is False
        assert received_tags[0]["Counter"] == 42


class TestDapStateProperties:
    def test_initial_state_is_idle(self):
        service = DapService()
        assert service.state == SimState.IDLE

    def test_continue_sets_running(self):
        states = []
        service = DapService(on_state=lambda s, e: states.append(s))
        buf = io.BytesIO()

        class FakeProc:
            stdin = buf
            stdout = io.BytesIO()

        service._proc = FakeProc()
        service.continue_()
        assert SimState.RUNNING in states
