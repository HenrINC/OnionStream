from typing import AsyncIterator, Awaitable, Union, Optional
import logging
import asyncio
import time

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes

from lib.handle_crash import handle
from lib.structs import EncryptionKey
from lib.connector import SubscriptionClient, SubscriptionServer

encryption_logger = logging.getLogger("EncryptionLogger")
encryption_logger.setLevel(logging.DEBUG)
encryption_logger.addHandler(logging.StreamHandler())
encryption_logger.debug("EncryptionLogger initialized")

class KeyChain:
    def __init__(self, pepper: Optional[bytes] = None, key_rotation_interval: int = 60):
        self.pepper = pepper or get_random_bytes(16)
        self.keys: list[EncryptionKey] = []
        self.new_keys: list[EncryptionKey] = []
        self.key_rotation_interval = key_rotation_interval

    def add_new_key(self):
        key_bytes = get_random_bytes(16)
        salt = get_random_bytes(16)
        key = EncryptionKey(
            salt=salt,
            bytes=key_bytes,
            hash=str(hash(self.pepper + key_bytes + salt)).encode().hex(),
            creation_time=time.time(),
            ttl=self.key_rotation_interval * 2,
        )
        self.keys.append(key)
        self.new_keys.append(key)
        encryption_logger.debug(f"Added new key: {key.hash}")

    def maintain_keys(self):
        for key in self.keys.copy():
            if key.creation_time + key.ttl < time.time():
                self.keys.remove(key)
                encryption_logger.debug(f"Removed key: {key.hash}")
        if (
            not self.keys
            or max(self.keys, key=lambda key: key.creation_time).creation_time
            + self.key_rotation_interval
            < time.time()
        ):
            self.add_new_key()

    def get_latest_key(self) -> EncryptionKey:
        self.maintain_keys()
        return max(self.keys, key=lambda key: key.creation_time)

    def get_key(self, hash: str) -> EncryptionKey:
        encryption_logger.info(f"Looking for key: {hash}")
        self.maintain_keys()
        for key in self.keys:
            if key.hash == hash:
                return key
        raise KeyError("Key not found")

    def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.new_keys:
            await asyncio.sleep(0.5)
        encryption_logger.debug(f"Yielding new key: {self.new_keys[0].hash}")
        return self.new_keys.pop(0).to_bytes()


class Encoder:
    _keychain: KeyChain = KeyChain()

    def __init__(self, subscription_client: SubscriptionClient, **kwargs):
        self.subscription_client: SubscriptionClient = subscription_client
        self.transcoding_iterator: Optional[AsyncIterator[bytes]] = None
        self.transcoding_settings = kwargs

    async def start(self):
        encryption_logger.debug("Starting encoder")
        self.transcoding_iterator = await self.subscription_client.subscribe(
            self.transcoding_settings, self.transcoding_settings
        )
        encryption_logger.debug("Encoder started")

    def __aiter__(self):
        return self

    async def __anext__(self):
        segment = await self.transcoding_iterator.__anext__()
        encryption_logger.debug(f"Encrypting segment of size {len(segment)}")
        key = self._keychain.get_latest_key()
        iv = get_random_bytes(16).hex().encode()
        cipher = AES.new(key.bytes, AES.MODE_CBC, key.salt)
        encrypted_segment = cipher.encrypt(pad(segment, AES.block_size))
        encryption_logger.debug(f"Sending segment of size {len(encrypted_segment)}")
        return b"\n".join([key.hash.encode(), iv, segment])

    @classmethod
    @property
    def keychain(cls) -> KeyChain:
        return cls._keychain


class EncryptionServer(SubscriptionServer):
    def __init__(self, host: str, port: int, subscription_client: SubscriptionClient):
        super().__init__(host, port)
        self.subscription_client = subscription_client

    async def get_iterator(
        self, arguments: dict[str, str]
    ) -> Awaitable[AsyncIterator[bytes]]:
        if arguments.get("key_getter", False):
            encryption_logger.debug("Key getter requested")
            return Encoder.keychain.__aiter__()
        else:
            encryption_logger.debug("Encoder requested")
            encoder = Encoder(subscription_client=self.subscription_client, **arguments)
            await encoder.start()
            encryption_logger.debug("Encoder started")
            return encoder.__aiter__()


async def run(client: SubscriptionClient):
    server = EncryptionServer("0.0.0.0", 8082, subscription_client=client)
    await server.run()


async def main():
    client = SubscriptionClient("127.0.0.1", 8081)
    await client.run(run)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        asyncio.run(handle())