"""The daemon log keeps what matters (2026-11-19: 476 of its lines were one MCP
notice about unlisted tools, and every stop added a traceback)."""
import logging

import pytest


def test_the_unlisted_tool_notice_is_dropped_and_nothing_else():
    from gray_matter._worker import _UnlistedToolNotice
    f = _UnlistedToolNotice()
    rec = lambda msg: logging.LogRecord("mcp.server.lowlevel.server", logging.WARNING,  # noqa: E731
                                        __file__, 1, msg, ("forgotten",), None)
    assert not f.filter(rec("Tool '%s' not listed, no validation will be performed"))
    assert f.filter(rec("Received exception from stream: %s"))


def test_only_the_aborted_accept_is_silenced():
    pytest.importorskip("mcp")
    from gray_matter import server

    seen = []

    class _Loop:
        def default_exception_handler(self, context):
            seen.append(context)

    aborted = OSError(22, "aborted")
    aborted.winerror = 995
    server._quiet_aborted_accept(_Loop(), {"exception": aborted})
    assert seen == [], "the accept the shutdown cancels is expected"

    other = {"exception": OSError(13, "denied"), "message": "real"}
    server._quiet_aborted_accept(_Loop(), other)
    assert seen == [other], "any other error still reaches asyncio's handler"
