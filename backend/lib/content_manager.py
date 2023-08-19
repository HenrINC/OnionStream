from uuid import uuid4
import asyncio
import logging
import base64

from .connector import (
    SubscriptionClient,
    IdentifiableSingleton,
    TaskAsyncIterator,
    DataSetter,
)
from .structs import (
    Segment,
    SegmentRequest,
    Playlist,
    PlaylistRequest,
    EncryptionKey,
    EncryptionKeyRequest,
)
from .constants import (
    DEFAULT_HLS_SEGMENT_DURATION,
    DEFAULT_HLS_PLAYLIST_LENGTH,
    DEBUG_FORCE_IV,
    DEBUG_SHOW_KEY,
    MAX_KEY_RETRY,
    KEY_RETRY_TIMEOUT,
)

manager_logger = logging.getLogger("ManagerLogger")
manager_logger.setLevel(logging.DEBUG)
manager_logger.addHandler(logging.StreamHandler())
manager_logger.debug("ManagerLogger initialized")

if DEBUG_FORCE_IV:
    manager_logger.warning("IVs are being forced, this is not secure at all")

if DEBUG_SHOW_KEY:
    manager_logger.warning("Keys are being shown, this is not secure at all")


class ContentManager:
    """
    Class responsible for managing subscriptions and the segments they produce.
    This class does not implement any security measures, that's the role of the HTTP server.
    """

    def __init__(self, host: str, port: int):
        self.client = SubscriptionClient(host, port)
        self.subscriptions: dict[frozenset, list[str]] = {}
        self.data_setters: TaskAsyncIterator = TaskAsyncIterator()
        self.key_getters: TaskAsyncIterator = TaskAsyncIterator()
        self.segments: dict[str, Segment] = {}
        self.keys: list[EncryptionKey] = []

    async def get_segment(self, request: SegmentRequest) -> Segment:
        return self.segments[request.uuid]

    async def get_playlist(self, request: PlaylistRequest) -> Playlist:
        mutable_identifier: dict = request.dict(
            exclude_none=True,
            exclude_defaults=True,
            exclude_unset=True,
        )
        imutable_identifier: frozenset = IdentifiableSingleton.get_imutable_identifier(
            mutable_identifier
        )

        if imutable_identifier not in self.subscriptions:
            data_setter = DataSetter(
                arguments=mutable_identifier,
                identifier=mutable_identifier,
                iterator_getter=lambda arguments: self.client.subscribe(
                    arguments, arguments
                ),
            )

            await self.handle_segment(
                *(await data_setter.__anext__()),
            )  # Ensures the playlist has at least one segment
            self.data_setters.append(data_setter.__anext__())
        segments_uuids: list[str] = self.subscriptions[imutable_identifier]
        segments: list[Segment] = [self.segments[uuid] for uuid in segments_uuids]
        return Playlist(segments=segments)

    async def handle_segment(self, data_setter: DataSetter, segment: bytes):
        mutable_identifier: dict = data_setter._mutable_identifier
        imutable_identifier: frozenset = IdentifiableSingleton.get_imutable_identifier(
            mutable_identifier
        )
        if imutable_identifier not in self.subscriptions:
            self.subscriptions[imutable_identifier] = []
        mutable_identifier: dict = data_setter._mutable_identifier
        key_hash, iv, encrypted_segment = [base64.b64decode(i) for i in segment.split(b"\n", 2)]
        manager_logger.debug(f"Received segment {mutable_identifier}")
        manager_logger.debug(f"IV: {iv}")
        manager_logger.debug(f"Key hash: {key_hash}")
        manager_logger.debug(f"Segment_size:  {len(encrypted_segment)}")
        try:
            key = await self._get_key(key_hash=key_hash.decode())
        except:
            breakpoint()
            raise
        media_sequence = (
            self.segments[self.subscriptions[imutable_identifier][-1]].media_sequence
            + 1
            if self.subscriptions[imutable_identifier]
            else 1
        )
        segment_uid = uuid4().hex
        segment = Segment(
            duration=mutable_identifier.get("duration", DEFAULT_HLS_SEGMENT_DURATION),
            uid=segment_uid,
            encryption_key=key,
            iv=iv,
            media_sequence=media_sequence,
            bytes=encrypted_segment,
        )
        self.segments[segment_uid] = segment
        self.subscriptions[imutable_identifier].append(segment_uid)
        manager_logger.debug(f"Add segment to playlist {imutable_identifier}")
        await self.clean_subscription(imutable_identifier)

    async def clean_subscription(self, imutable_identifier: frozenset):
        while (
            len(self.subscriptions[imutable_identifier]) > DEFAULT_HLS_PLAYLIST_LENGTH
        ):
            uuid = self.subscriptions[imutable_identifier].pop(0)
            del self.segments[uuid]

    async def get_key(self, request: EncryptionKeyRequest) -> EncryptionKey:
        return await self._get_key(key_hash=request.key_hash)

    async def _get_key(self, key_hash: str) -> EncryptionKey:
        manager_logger.debug(f"Getting key with hash {key_hash}")
        for i in range(MAX_KEY_RETRY):
            for key in self.keys:
                manager_logger.debug(f"Key hash: {key.hash}")
                if key.hash == key_hash:
                    return key
            manager_logger.warning(
                f"Could not find key {key_hash}, retrying in {KEY_RETRY_TIMEOUT} seconds"
            )
            await asyncio.sleep(KEY_RETRY_TIMEOUT)
        raise KeyError(f"Key with hash {key_hash} not found")

    async def run_forever(self):
        await asyncio.gather(
            self.client.run(),
            self.loop(),
            self.key_loop(),
        )

    async def handle_key(self, key_getter, key_bytes):
        key = EncryptionKey.from_bytes(key_bytes)
        self.keys.append(key)
        manager_logger.debug(f"Received key {key.hash}")

    async def key_loop(self):
        manager_logger.debug("Started key loop")
        data_setter = DataSetter(
            arguments={"key_getter": "True"},
            identifier={"key_getter": "True"},
            iterator_getter=lambda arguments: self.client.subscribe(
                arguments, arguments
            ),
        )
        self.key_getters.append(data_setter.__anext__())
        manager_logger.debug("Key getter added to key getters")
        while True:
            if self.key_getters.is_empty():
                await asyncio.sleep(0.5)
            else:
                async for key_getter, key_bytes in self.key_getters:
                    manager_logger.debug("Received new key")
                    await self.handle_key(key_getter, key_bytes)
                    self.key_getters.append(key_getter.__anext__())

    async def loop(self):
        while True:
            if self.data_setters.is_empty():
                await asyncio.sleep(0.5)
            else:
                async for data_setter, segment in self.data_setters:
                    await self.handle_segment(data_setter, segment)
                    self.data_setters.append(data_setter.__anext__())
