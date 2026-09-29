import asyncio
from types import SimpleNamespace
from app import live_audio


def test_delayed_listener_receives_entire_announcement_before_music(monkeypatch):
    """A >3s scheduling/network pause must not seek past the closing speech."""
    batches = [
        [(b'radio:audio', [(b'1000-0', {b'chunk': b'intro-start'})])],
        [(b'radio:audio', [(b'2000-0', {b'chunk': b'closing-words'}),
                          (b'6000-0', {b'chunk': b'music-start'})])],
    ]
    class Redis:
        closed = False
        reads = []
        edges = 0
        async def xrevrange(self, *args, **kwargs):
            self.edges += 1
            return [(b'900-0' if self.edges == 1 else b'6000-0', {})]
        async def xread(self, streams, **kwargs):
            self.reads.append(streams['radio:audio'])
            return batches.pop(0)
        async def aclose(self): self.closed = True
    client = Redis()
    monkeypatch.setattr(live_audio.aioredis, 'from_url', lambda *a, **k: client)
    async def disconnected(): return not batches
    async def collect(): return [chunk async for chunk in live_audio.chunks(SimpleNamespace(is_disconnected=disconnected))]
    assert asyncio.run(collect()) == [b'intro-start', b'closing-words', b'music-start']
    assert client.reads == [b'900-0', b'1000-0']
    assert client.edges == 1 and client.closed


def test_idle_stream_anchors_once_and_closes_on_cancellation(monkeypatch):
    class Redis:
        reads = []
        closed = False
        async def xrevrange(self, *a, **k): return []
        async def xread(self, streams, **kwargs):
            self.reads.append(streams['radio:audio'])
            return [] if len(self.reads) == 1 else [(b'radio:audio', [(b'5-0', {b'chunk': b'speech'})])]
        async def aclose(self): self.closed = True
    client = Redis()
    monkeypatch.setattr(live_audio.aioredis, 'from_url', lambda *a, **k: client)
    async def disconnected(): return False
    async def collect():
        stream = live_audio.chunks(SimpleNamespace(is_disconnected=disconnected))
        try: assert await anext(stream) == b'speech'
        finally: await stream.aclose()
    asyncio.run(collect())
    assert client.reads == ['0-0', '0-0'] and client.closed
