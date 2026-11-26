"""app_client: contrato HTTP (con transporte falso de httpx) y FakeAppClient."""

from __future__ import annotations

import httpx
import pytest

from pt_worker.app_client.fake import FakeAppClient
from pt_worker.app_client.http import HttpAppClient
from pt_worker.app_client.port import AppClientError, CallAlreadyEndedError


class Recorder:
    """Transporte falso: responde con una lista de resultados y guarda lo recibido."""

    def __init__(self, *results: httpx.Response | Exception) -> None:
        self.results = list(results)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_client(recorder: Recorder, attempts: int = 3) -> tuple[HttpAppClient, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = HttpAppClient(
        "https://app.test/",
        "tok-123",
        max_attempts=attempts,
        transport=httpx.MockTransport(recorder),
        sleep=fake_sleep,
    )
    return client, sleeps


async def test_get_context_sends_bearer_and_returns_json() -> None:
    rec = Recorder(httpx.Response(200, json={"call_id": "c1"}))
    client, _ = make_client(rec)
    assert await client.get_context("c1") == {"call_id": "c1"}
    request = rec.requests[0]
    assert request.method == "GET"
    assert str(request.url) == "https://app.test/api/internal/calls/c1/context"
    assert request.headers["Authorization"] == "Bearer tok-123"


async def test_context_404_means_generic_config() -> None:
    client, _ = make_client(Recorder(httpx.Response(404)))
    assert await client.get_context("c1") is None


async def test_context_409_means_call_already_ended() -> None:
    client, _ = make_client(Recorder(httpx.Response(409)))
    with pytest.raises(CallAlreadyEndedError):
        await client.get_context("c1")


async def test_post_turns_body_and_path() -> None:
    rec = Recorder(httpx.Response(204))
    client, _ = make_client(rec)
    turns = [{"seq": 1, "role": "assistant", "text": "hola", "started_ms": 10}]
    await client.post_turns("c1", turns)
    request = rec.requests[0]
    assert request.url.path == "/api/internal/calls/c1/turns"
    assert request.read() == (
        b'{"turns":[{"seq":1,"role":"assistant","text":"hola","started_ms":10}]}'
    )


async def test_post_end_path() -> None:
    rec = Recorder(httpx.Response(200))
    client, _ = make_client(rec)
    await client.post_end("c1", {"ended_reason": "completed"})
    assert rec.requests[0].url.path == "/api/internal/calls/c1/end"


async def test_retries_5xx_then_succeeds_with_backoff() -> None:
    rec = Recorder(httpx.Response(503), httpx.Response(429), httpx.Response(204))
    client, sleeps = make_client(rec)
    await client.post_turns("c1", [])
    assert len(rec.requests) == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


async def test_retries_any_5xx() -> None:
    rec = Recorder(httpx.Response(501), httpx.Response(204))
    client, _ = make_client(rec)
    await client.post_turns("c1", [])
    assert len(rec.requests) == 2


async def test_timeouts_follow_the_contract() -> None:
    rec = Recorder(
        httpx.Response(200, json={}), httpx.Response(204), httpx.Response(200), httpx.Response(204)
    )
    client, _ = make_client(rec)
    await client.get_context("c1")
    await client.post_turns("c1", [])
    await client.post_end("c1", {})
    await client.post_heartbeat("w1", 0, "0.1.0")
    read_timeouts = [r.extensions["timeout"]["read"] for r in rec.requests]
    assert read_timeouts == [3.0, 5.0, 5.0, 5.0]


async def test_retries_network_errors() -> None:
    rec = Recorder(httpx.ConnectError("boom"), httpx.Response(204))
    client, _ = make_client(rec)
    await client.post_turns("c1", [])
    assert len(rec.requests) == 2


async def test_never_retries_4xx() -> None:
    rec = Recorder(httpx.Response(401))
    client, sleeps = make_client(rec)
    with pytest.raises(AppClientError, match="401"):
        await client.post_turns("c1", [])
    assert len(rec.requests) == 1
    assert sleeps == []


async def test_gives_up_after_max_attempts() -> None:
    rec = Recorder(httpx.Response(500), httpx.Response(500))
    client, _ = make_client(rec, attempts=2)
    with pytest.raises(AppClientError, match="2 intentos"):
        await client.post_end("c1", {})
    assert len(rec.requests) == 2


async def test_fake_turns_are_idempotent_by_seq() -> None:
    fake = FakeAppClient()
    turn = {"seq": 1, "role": "user", "text": "hola", "started_ms": 5}
    await fake.post_turns("c1", [turn])
    await fake.post_turns("c1", [turn])
    assert list(fake.turns["c1"]) == [1]


async def test_fake_second_end_changes_nothing() -> None:
    fake = FakeAppClient()
    await fake.post_end("c1", {"ended_reason": "completed"})
    await fake.post_end("c1", {"ended_reason": "failed"})
    assert fake.ends["c1"]["ended_reason"] == "completed"


async def test_fake_can_simulate_app_down() -> None:
    fake = FakeAppClient()
    fake.fail_next = 1
    with pytest.raises(AppClientError):
        await fake.get_context("c1")
    assert await fake.get_context("c1") is None
