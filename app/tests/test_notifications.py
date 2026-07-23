import asyncio

import respx
from httpx import Response

import main


@respx.mock
def test_send_failure_notification_posts_the_message(monkeypatch):
    monkeypatch.setattr(main.settings, "NOTIFY_WEBHOOK_URL", "http://hook.test/topic")
    route = respx.post("http://hook.test/topic").mock(return_value=Response(200))
    asyncio.run(main.send_failure_notification("Import failed: Dune"))
    assert route.called
    assert b"Import failed: Dune" in route.calls.last.request.content
