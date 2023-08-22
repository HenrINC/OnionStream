from typing import AsyncIterator, Awaitable, Union, Optional
import logging
import asyncio
import os

from lib.structs import TranscodingSettings
from lib.connector import SubscriptionClient, SubscriptionServer
from lib.constants import (
    RESTREAMER_HOST,
    RESTREAMER_PORT,
    TRANSCODER_PORT,
    DEFAULT_LOG_LEVEL,
    POST_MORTEM_DEBUGGER,
)

restreamer_host = os.environ.get("RESTREAMER_HOST", RESTREAMER_HOST)
restreamer_port = os.environ.get("RESTREAMER_PORT", RESTREAMER_PORT)
transcoder_port = os.environ.get("TRANSCODER_PORT", TRANSCODER_PORT)
log_level = os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)


logging.getLogger("ConnectionLogger").setLevel(log_level)
transcoding_logger = logging.getLogger("TranscodingLogger")
transcoding_logger.setLevel(log_level)
transcoding_logger.addHandler(logging.StreamHandler())
transcoding_logger.debug("TranscodingLogger initialized")


class Transcoder:
    def __init__(self, subscription_client: SubscriptionClient, **kwargs):
        transcoding_args = kwargs.keys() & TranscodingSettings.__fields__.keys()
        restreaming_args = kwargs.keys() - transcoding_args
        self.subscription_client: SubscriptionClient = subscription_client
        self.restreaming_iterator: Optional[AsyncIterator[bytes]] = None
        transcoding_settings = TranscodingSettings(
            **{k: kwargs[k] for k in transcoding_args}
        )
        self.restreaming_settings = {k: kwargs[k] for k in restreaming_args}
        command = ["ffmpeg", "-loglevel", "warning", "-i", "pipe:0"]
        for key, value in transcoding_settings.dict(exclude_none=True).items():
            if value is not None:
                # Convert Python-style variable names to ffmpeg-style command line arguments
                ffmpeg_arg = "-" + key.replace("__", ":")
                command.append(ffmpeg_arg)
                command.append(str(value))
        command += ["-f", "mpegts", "pipe:1"]
        self.cmd = command
        transcoding_logger.debug(f"Transcoding command: {' '.join(self.cmd)}")
        self.subprocess: Optional[asyncio.subprocess.Process] = None

    async def start(self):
        transcoding_logger.debug("Starting transcoding subprocess")
        self.subprocess = await asyncio.create_subprocess_exec(
            *self.cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
        )
        self.restreaming_iterator = await self.subscription_client.subscribe(
            self.restreaming_settings, self.restreaming_settings
        )

    def __aiter__(self):
        return self

    async def __anext__(self):
        buffer = b""
        while True:
            while True:
                try:
                    buffer += await asyncio.wait_for(
                        self.subprocess.stdout.readuntil(b"\x47"), timeout=1
                    )
                    await asyncio.sleep(0)
                except asyncio.TimeoutError:
                    next_segment = await self.restreaming_iterator.__anext__()
                    self.subprocess.stdin.write(next_segment)
                    break
            if buffer:
                transcoding_logger.debug(f"Yielding a segment of size {len(buffer)}")
                return buffer
            else:
                await asyncio.sleep(1)


class TranscodingServer(SubscriptionServer):
    def __init__(self, host: str, port: int, subscription_client: SubscriptionClient):
        super().__init__(host, port)
        self.subscription_client = subscription_client

    async def get_iterator(
        self, arguments: dict[str, str]
    ) -> Awaitable[AsyncIterator[bytes]]:
        transcoder = Transcoder(
            subscription_client=self.subscription_client, **arguments
        )
        await transcoder.start()
        return transcoder.__aiter__()


async def run(client: SubscriptionClient):
    server = TranscodingServer("0.0.0.0", transcoder_port, subscription_client=client)
    await server.run()


async def main():
    client = SubscriptionClient(restreamer_host, restreamer_port)
    await client.run(run)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        if POST_MORTEM_DEBUGGER:
            import pdb

            pdb.post_mortem()
