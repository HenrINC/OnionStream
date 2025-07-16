import os
import asyncio

from contextlib import asynccontextmanager
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
        self.queues: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    @property
    def _channel_name(self) -> str:
        return f"onionstream:stream:{self.stream_id}"

    async def _main_loop(self):
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(self._channel_name)
            print(f"Subscribed to {self._channel_name}")

            while True:
                try:
                    message = await pubsub.get_message(timeout=1.0)
                    if message is None:
                        # Check if we still have active queues
                        if not self.queues:
                            print(
                                f"No active queues for stream {self.stream_id}, continuing"
                            )
                        continue

                    if message["type"] != "message":
                        continue

                    frame_data = message["data"]
                    if not self.queues:
                        continue

                    # Send to all active queues
                    for (
                        queue
                    ) in (
                        self.queues.copy()
                    ):  # Copy to avoid modification during iteration
                        try:
                            await queue.put(frame_data)
                        except asyncio.QueueFull:
                            print(f"Queue full for stream {self.stream_id}, skipping")
                            continue

                    await asyncio.sleep(0)  # Yield control

                except asyncio.CancelledError:
                    print(f"Main loop cancelled for stream {self.stream_id}")
                    break
                except Exception as e:
                    print(f"Error in main loop for stream {self.stream_id}: {e}")
                    await asyncio.sleep(0.1)  # Brief pause before retrying

        except Exception as e:
            print(f"Failed to subscribe to {self._channel_name}: {e}")
        finally:
            try:
                await pubsub.unsubscribe(self._channel_name)
                await pubsub.close()
            except Exception as e:
                print(f"Error closing pubsub for stream {self.stream_id}: {e}")

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

    @asynccontextmanager
    async def get_queue(self):
        async with self._lock:
            if len(self.queues) == 0:
                await self._initialize()
            queue = asyncio.Queue(maxsize=3000)  # Around 3 seconds of data
            self.queues.append(queue)
        yield queue
        async with self._lock:
            self.queues.remove(queue)
            if len(self.queues) == 0:
                await self._shutdown()


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

    try:
        async with broker.get_queue() as queue:
            while True:
                try:
                    # Wait for frame data from the broker
                    nal = await queue.get()
                    await ws.send_bytes(nal)
                except Exception as e:
                    print(
                        f"Error sending data to WebSocket for stream {stream_id}: {e}"
                    )
                    break
    except Exception as e:
        print(f"Error in live_stream for stream {stream_id}: {e}")
    finally:
        try:
            await ws.close()
        except:
            pass
