import os
import asyncio

from redis import asyncio as aioredis

from fastapi.routing import APIRouter
from fastapi import WebSocket


class StreamBroker:
    __instances__: dict[str, "StreamBroker"] = {}

    @classmethod
    def get(cls, stream_id: str) -> "StreamBroker":
        if stream_id not in cls.__instances__:
            cls.__instances__[stream_id] = cls(stream_id)
        return cls.__instances__[stream_id]

    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.task: asyncio.Task | None = None
        self.contexts: list["StreamBrokerContext"] = []
        self._lock = asyncio.Lock()

    @property
    def _channel_name(self) -> str:
        return f"onionstream:stream:{self.stream_id}"

    async def _main_loop(self):
        pubsub = redis.pubsub()
        await pubsub.subscribe(self._channel_name)

        while True:
            message = await pubsub.get_message(timeout=1.0)
            if message is None:
                print(f"No message received for stream {self.stream_id}, continuing")
                continue
            if message["type"] != "message":
                print(
                    f"Received non-message type for stream {self.stream_id}: {message['type']}"
                )
                continue
            frame_data = message["data"]
            if not self.contexts:
                print(f"No active contexts for stream {self.stream_id}, skipping")
                continue
            for context in self.contexts:
                try:
                    await context._nals.put(frame_data)
                except asyncio.QueueFull:
                    print(
                        f"Queue full for context in stream {self.stream_id}, skipping"
                    )
                    continue
            await asyncio.sleep(0)

    async def _initialize(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._main_loop())

    async def _shutdown(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def __aenter__(self):
        async with self._lock:
            if len(self.contexts) == 0:
                await self._initialize()
            context = StreamBrokerContext(self)
            self.contexts.append(context)
        return context

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self._lock:
            self.contexts.remove(self)
            if len(self.contexts) == 0:
                await self._shutdown()


class StreamBrokerContext:
    def __init__(self, stream_broker: StreamBroker):
        self._stream_broker = stream_broker
        self._nals = asyncio.Queue()

    async def next_nal(self):
        if self._stream_broker.task is None or self._stream_broker.task.done():
            raise RuntimeError("Stream broker task is not running")
        return await self._nals.get()


router = APIRouter()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
redis = aioredis.from_url(redis_url, decode_responses=False)


@router.get("/stream_list")
async def stream_list() -> list[str]:
    streams = await redis.smembers("onionstream:streams")
    return [i.decode() for i in streams]


@router.websocket("/live/{stream_id}")
async def live_stream(ws: WebSocket, stream_id: str):
    await ws.accept()
    broker = StreamBroker.get(stream_id)
    async with broker as context:
        nal = await context.next_nal()
        ws.send_bytes(nal)
