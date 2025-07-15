import os
import asyncio
from collections import defaultdict

from redis import asyncio as aioredis

from fastapi.routing import APIRouter
from fastapi import WebSocket, WebSocketDisconnect

router = APIRouter()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
redis = aioredis.from_url(redis_url, decode_responses=False)

clients: defaultdict[str, list[WebSocket]] = defaultdict(list)
pubsub_tasks: defaultdict[str, asyncio.Task] = dict()


@router.get("/stream_list")
async def stream_list() -> list[str]:
    streams = await redis.smembers("onionstream:streams")
    return [i.decode() for i in streams]


@router.websocket("/live/{stream_id}")
async def live_stream(ws: WebSocket, stream_id: str):
    await ws.accept()
    clients[stream_id].append(ws)
    await _create_pubsub_task_if_needed(stream_id)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print(f"Client disconnected from stream {stream_id}")
    except Exception as e:
        print(f"Error in live stream for {stream_id}: {e}")
    finally:
        print(f"Closing WebSocket for stream {stream_id}")
        try:
            await ws.close()
        except:
            pass
        if ws in clients[stream_id]:
            clients[stream_id].remove(ws)
        await _cancel_pubsub_task_if_needed(stream_id)


async def _pubsub_handler(stream_id: str):
    channel_name = f"onionstream:stream:{stream_id}"

    print(f"Started Redis pubsub listener for stream: {stream_id}")

    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_name)

    try:
        while True:
            if not clients[stream_id]:
                print(f"No clients left for stream {stream_id}, exiting pubsub loop")
                break

            try:
                message = await pubsub.get_message(timeout=1.0)

                if message is not None and message["type"] == "message":
                    frame_data = message["data"]

                    # Send to all connected clients
                    disconnected = []
                    for ws in clients[stream_id]:
                        try:
                            await asyncio.wait_for(
                                ws.send_bytes(frame_data), timeout=0.1
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

            except Exception as e:
                print(f"Error reading from Redis pubsub {stream_id}: {e}")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(0.001)  # Small delay to prevent tight loop

    except asyncio.CancelledError:
        print(f"Stopping Redis pubsub listener for stream: {stream_id}")
    except Exception as e:
        print(f"Error in Redis pubsub handler {stream_id}: {e}")
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.close()


async def _create_pubsub_task_if_needed(stream_id: str):
    if stream_id not in pubsub_tasks:
        task = asyncio.create_task(_pubsub_handler(stream_id))
        pubsub_tasks[stream_id] = task


async def _cancel_pubsub_task_if_needed(stream_id: str):
    if stream_id in pubsub_tasks and not clients[stream_id]:
        task = pubsub_tasks[stream_id]
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del pubsub_tasks[stream_id]
            print(f"Cancelled pubsub task for stream {stream_id}")
