from typing import AsyncIterator, Awaitable, Union, Optional
import asyncio
import os

from fastapi import FastAPI, Depends, Query
from fastapi.responses import Response
import uvicorn

from lib.content_manager import ContentManager
from lib.structs import SegmentRequest, PlaylistRequest, EncryptionKeyRequest
from lib.constants import SERVER_NAME, ENCODER_HOST, ENCODER_PORT, API_PORT

app = FastAPI()
base_headers = {
    "Server": SERVER_NAME,
}

encoder_host = os.environ.get("ENCODER_HOST", ENCODER_HOST)
encoder_port = os.environ.get("ENCODER_PORT", ENCODER_PORT)
api_port = int(os.environ.get("API_PORT", API_PORT))
content_manager = ContentManager(encoder_host, encoder_port)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(content_manager.run_forever())
    


@app.get("/segment.ts")
@app.get("/api/segment.ts")
async def segment(request: SegmentRequest = Depends()):
    segment = await content_manager.get_segment(request)
    return Response(content=segment.bytes, media_type="video/mp2t", headers=base_headers)

@app.get("/playlist.m3u8")
@app.get("/api/playlist.m3u8")
async def playlist(request: PlaylistRequest = Depends()):
    playlist = await content_manager.get_playlist(request)
    return Response(content=playlist.bytes, media_type="application/vnd.apple.mpegurl", headers=base_headers)

@app.get("/key.bin")
@app.get("/api/key.bin")
async def key(request: EncryptionKeyRequest = Depends()):
    key = await content_manager.get_key(request)
    return Response(content=key.bytes, media_type="application/octet-stream", headers=base_headers)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=api_port, timeout_keep_alive=60)