from typing import AsyncIterator, Awaitable, Union
import logging
import asyncio
import time
import os

from lib.connector import SubscriptionServer
from lib.constants import RESTREAMER_PORT, DEFAULT_LOG_LEVEL

restreamer_port = os.environ.get("RESTREAMER_PORT", RESTREAMER_PORT)
log_level = os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)
logging.getLogger("ConnectionLogger").setLevel(log_level)

class Restreamer:
    def __init__(self, source: str, segment_duration: Union[str, int] = 5, **kwargs):
        # TODO: do input validation on kwargs and add them to the cmd
        self.cmd = (
            "ffmpeg",
            "-loglevel",
            "warning",  # Hide FFmpeg's console output
            "-i",
            source,  # source
            "-codec",
            "copy",  # Copy original codecs, no re-encoding
            "-map",
            "0",  # Map all streams (video, audio, subtitles) from the source
            "-f",
            "mpegts",  # Output format (MPEG-TS)
            "-",  # Output to stdout
        )
        self.segment_time = int(segment_duration)

    async def start(self):
        self.subprocess = await asyncio.create_subprocess_exec(
            *self.cmd, stdout=asyncio.subprocess.PIPE
        )
        self.last_update = time.time()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.subprocess is None:
            await self.start()
        buffer = b""
        while time.time() - self.last_update < self.segment_time:
            chunk = await self.subprocess.stdout.readuntil(b"\x47")
            if chunk:
                buffer += chunk
            else:
                raise StopAsyncIteration("Stream ended")
        self.last_update = time.time()
        return buffer


class RestreamingServer(SubscriptionServer):
    async def get_iterator(
        self, arguments: dict[str, str]
    ) -> Awaitable[AsyncIterator[bytes]]:
        restreamer = Restreamer(**arguments)
        await restreamer.start()
        return restreamer.__aiter__()


async def main():
    server = RestreamingServer("0.0.0.0", restreamer_port)
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())