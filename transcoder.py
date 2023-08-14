from typing import AsyncIterator, Awaitable, Union, Optional
import logging
import asyncio

from lib.handle_crash import handle
from lib.structs import TranscodingSettings
from lib.connector import SubscriptionClient, SubscriptionServer


logging.getLogger("ConnectionLogger").setLevel(logging.DEBUG)
transcoding_logger = logging.getLogger("TranscodingLogger")
transcoding_logger.setLevel(logging.DEBUG)
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
        for key, value in transcoding_settings.dict().items():
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
    server = TranscodingServer("0.0.0.0", 8081, subscription_client=client)
    await server.run()


async def main():
    client = SubscriptionClient("127.0.0.1", 8080)
    await client.run(run)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        asyncio.run(handle())