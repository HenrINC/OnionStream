import os
import time

from fastapi.routing import APIRouter
from fastapi.websockets import WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/latency")
async def latency(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            T1 = time.time() * 1000
            await ws.send_text(f"time:{T1}")

            T3_str = await ws.receive_text()
            T4 = time.time() * 1000

            T3, T2 = map(float, T3_str.split(":"))

            rtt = (T4 - T1) - (T3 - T2)
            offset = ((T2 - T1) + (T3 - T4)) / 2
            video_latency = (T2 - T1) - offset

            message = f"[VideoLatency] {video_latency:.2f}, [RTT] {rtt:.2f} ms, [Offset] {offset:.2f} ms"
            await ws.send_text(f"log:{message}")
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@router.websocket("/throughput")
async def throughput(ws: WebSocket):
    await ws.accept()
    results = []
    try:
        for size_kb in [128, 256, 512, 1024]:
            await ws.send_text(f"log:[INFO] Testing throughput with size {size_kb} KB")
            size = size_kb * 1024
            for i in range(10):
                data = os.urandom(size)
                start = time.time()

                await ws.send_bytes(data)
                await ws.receive_text()

                end = time.time()
                duration = end - start
                rate = (size * 8) / duration
                results.append(rate)

                await ws.send_text(f"log:[Sample {i+1}] {rate/1000:.2f} kbps")

        avg = sum(results) / len(results)
        await ws.send_text(f"log:[Throughput Estimate] {avg/1000:.2f} kbps")
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
