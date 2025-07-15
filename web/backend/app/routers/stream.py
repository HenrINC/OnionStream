import os
import asyncio
from collections import defaultdict

from redis import asyncio as aioredis

from fastapi.routing import APIRouter
from fastapi import WebSocket, WebSocketDisconnect

router = APIRouter()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
redis = aioredis.from_url(redis_url, decode_responses=False)

clients: defaultdict[str : list[WebSocket]] = defaultdict(list)
tasks: defaultdict[str : asyncio.Task] = dict()


@router.get("/stream_list")
async def stream_list() -> list[str]:
    streams = await redis.smembers("onionstream:streams")
    return [i.decode() for i in streams]


@router.websocket("/live/{stream_id}")
async def live_stream(ws: WebSocket, stream_id: str):
    await ws.accept()
    clients[stream_id].append(ws)
    await _create_task_if_needed(stream_id)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print(f"Client disconnected from stream {stream_id}")
    except Exception as e:
        print(f"Error in live stream for {stream_id}: {e}")
    finally:
        print(f"Closing WebSocket for stream {stream_id}")
        await ws.close()
        clients[stream_id].remove(ws)
        await _cancel_task_if_needed(stream_id)


async def _stream_handler(stream_id: str):
    stream_key = f"onionstream:stream:{stream_id}"
    last_id = "$"  # Start from newest messages

    print(f"Started Redis stream listener for stream: {stream_id}")

    try:
        while True:
            if not clients[stream_id]:
                print(f"No clients left for stream {stream_id}, exiting loop")
                break

            # Read new messages from stream
            try:
                messages = await redis.xread({stream_key: last_id}, block=1000, count=1)

                if messages:
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            frame_data = fields[b"data"]
                            frame_type = fields.get(b"frame_type", b"frame").decode()
                            frame_size = fields.get(b"size", b"0").decode()
                            last_id = msg_id

                            print(
                                f"Received {frame_type} of size {frame_size} for stream {stream_id}"
                            )

                            # Send to all connected clients
                            disconnected = []
                            for ws in clients[stream_id]:
                                try:
                                    await asyncio.wait_for(
                                        ws.send_bytes(frame_data), timeout=0.1
                                    )
                                    print(
                                        f"Sent {frame_type} to client for stream {stream_id}"
                                    )
                                except asyncio.TimeoutError:
                                    print(f"Client send timeout for stream {stream_id}")
                                    disconnected.append(ws)
                                except Exception as e:
                                    print(
                                        f"Error sending to client for stream {stream_id}: {e}"
                                    )
                                    disconnected.append(ws)

                            # Remove disconnected clients
                            for ws in disconnected:
                                if ws in clients[stream_id]:
                                    clients[stream_id].remove(ws)
                else:
                    print(f"No new messages for stream {stream_id}")

            except Exception as e:
                print(f"Error reading from Redis stream {stream_id}: {e}")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(0.001)  # Small delay to prevent tight loop

    except asyncio.CancelledError:
        print(f"Stopping Redis stream listener for stream: {stream_id}")
    except Exception as e:
        print(f"Error in Redis stream handler {stream_id}: {e}")


async def _create_task_if_needed(stream_id: str):
    if stream_id not in tasks:
        task = asyncio.create_task(_stream_handler(stream_id))
        tasks[stream_id] = task


async def _cancel_task_if_needed(stream_id: str):
    if stream_id in tasks and not clients[stream_id]:
        task = tasks[stream_id]
        if task:
            task.cancel()
            del tasks[stream_id]
            print(f"Cancelled task for stream {stream_id}")
