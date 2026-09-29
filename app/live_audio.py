"""Forward the bounded live buffer in order, including speech/music boundaries."""
from app.config import REDIS_URL
from redis import asyncio as aioredis


async def chunks(request):
    client = aioredis.from_url(REDIS_URL)
    try:
        # Anchor once at connection time. Reusing '$' after an idle read can skip
        # audio that arrives between reads. Existing listeners keep their cursor.
        latest = await client.xrevrange('radio:audio', count=1)
        cursor = latest[0][0] if latest else '0-0'
        while not await request.is_disconnected():
            rows = await client.xread({'radio:audio': cursor}, count=100, block=10000)
            for _, messages in rows:
                for cursor, fields in messages:
                    yield fields[b'chunk']
            # Do not jump to the newest chunk after a transient delay: doing so
            # can delete the end of an announcement just as the music starts.
            # Redis retention already bounds lag; trimmed audio is not an archive.
    finally:
        await client.aclose()
