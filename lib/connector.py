from typing import (
    Any,
    AsyncIterator,
    Callable,
    Optional,
    Union,
    AsyncIterable,
    Coroutine,
    Iterator,
    Awaitable,
)
from abc import ABC, abstractmethod
import asyncio
import logging

connection_logger = logging.Logger("ConnectionLogger")
connection_logger.setLevel(logging.DEBUG)
connection_logger.addHandler(logging.StreamHandler())
connection_logger.debug("Connector imported.")


class TaskAsyncIterator:
    def __init__(self, wait_for_futures: bool = False) -> None:
        self.futures: list[asyncio.Future] = []
        self.wait_for_futures = wait_for_futures

    def is_empty(self) -> bool:
        return not bool(len(self.futures))
    
    def _task_done_callback(self, future: asyncio.Future):
        self.futures.append(future)

    def append(self, obj: asyncio.Future | Coroutine):
        obj = asyncio.ensure_future(obj)
        connection_logger.debug(f"Appending future: {obj}")
        obj.add_done_callback(self._task_done_callback)

    def to_list(self):
        return self.futures.copy()

    def __aiter__(self):
        return self
    
    async def __anext__(self):
        if self.is_empty():
            if self.wait_for_futures:
                while self.is_empty():
                    await asyncio.sleep(0.5)
            else:
                raise StopAsyncIteration
        
        future = self.futures.pop(0)
        connection_logger.debug(f"Getting future: {future}")
        return future.result()

class SubscriptionProtocol(ABC):
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.delimiter = b"-<][OnionStream message delimiter][>-"
        self.ready: bool = False

    def set_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        assert (
            self.reader is None and self.writer is None
        ), "Can only use one connection at a time for security reasons."
        self.reader = reader
        self.writer = writer

    async def start(self) -> Awaitable[None]:
        return None

    @abstractmethod
    async def handle_message(self, message: bytes) -> None:
        raise NotImplementedError()

    async def _await_ready(self) -> Awaitable[None]:
        while (not self.ready) or (self.reader is None) or (self.writer is None):
            await asyncio.sleep(0.5)

    async def await_ready(self, timeout: int = 0) -> Awaitable[None]:
        if timeout:
            try:
                await asyncio.wait_for(self._await_ready(), timeout=timeout)
            except TimeoutError:
                raise TimeoutError(
                    "Could not get the connection ready in time. Please ensure self.start is running in the background."
                )
        else:
            await self._await_ready()
        connection_logger.debug("Connection ready.")
        

    async def loop(self) -> Awaitable[None]:
        await self.await_ready(30)
        while True:
            message = await self.reader.readuntil(separator=self.delimiter)
            message = message[: -len(self.delimiter)]
            connection_logger.debug(f"Received message, length: {len(message)}")
            await self.handle_message(message)

    async def run(self) -> Awaitable[None]:
        await asyncio.gather(self.start(), self.loop())

    def write(self, message: bytes) -> None:
        self.writer.write(message + self.delimiter)


class SubscriptionServer(SubscriptionProtocol):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(host=host, port=port)
        self.data_iterators: TaskAsyncIterator = TaskAsyncIterator()
        self.data_setters: list[DataSetter] = []

    def parse_message(self, message: bytes) -> tuple[dict[str, str], dict[str, str]]:
        return [
            dict([i.split(":", 1) for i in part.decode().split("\n")])
            for part in message.split(b"\n\n")
        ]

    async def handle_message(self, message: bytes) -> None:
        identifier, arguments = self.parse_message(message)
        connection_logger.debug(f"Handling subscription for {identifier} with {arguments}")
        if arguments == {"RESERVED_COMMAND": "DELETE"}:
            raise NotImplementedError()
        else:
            data_setter = await self.handle_subscription(identifier, arguments)
            self.data_setters.append(data_setter)
            self.data_iterators.append(data_setter.__aiter__().__anext__())

    def build_message(self, identifier: dict[str, str], payload: bytes) -> bytes:
        return b"\n\n".join(
            [
                b"\n".join(
                    [f"{key}:{value}".encode() for key, value in identifier.items()]
                ),
                payload,
            ]
        )

    async def set_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> Awaitable[None]:
        return super().set_connection(reader, writer)

    async def start(self) -> Awaitable[None]:
        server = await asyncio.start_server(self.set_connection, self.host, self.port)
        self.ready = True
        addr = server.sockets[0].getsockname()
        connection_logger.info(f"{self.__class__.__name__} ready and serving on {addr}")
        async with server:
            await server.serve_forever()

    async def update_data_iterators(self):
        data_setter: DataSetter
        payload: bytes
        while True:
            if self.data_iterators.is_empty():
                await asyncio.sleep(0.5)
            else:
                async for data_setter, payload in self.data_iterators:
                    if data_setter in self.data_setters:
                        self.data_iterators.append(data_setter.__anext__())
                    self.write(
                        self.build_message(data_setter._mutable_identifier, payload)
                    )
                connection_logger.debug("All setters awaited")

    async def loop(self) -> Awaitable[None]:
        connection_logger.debug("Starting subscription server loop.")
        await self.await_ready(30)
        connection_logger.debug("Subscription server loop ready.")
        await asyncio.gather(super().loop(), self.update_data_iterators())

    async def handle_subscription(
        self, identifier: dict[str, str], arguments: dict[str, str]
    ) -> "DataSetter":
        connection_logger.debug(f"Handling subscription to: {identifier}")
        return DataSetter(identifier, arguments, self.get_iterator)

    async def get_iterator(
        self, arguments: dict[str, str]
    ) -> Awaitable[AsyncIterable[bytes]]:
        raise NotImplementedError(
            "Please implement this method in a subclass. Or override handle_subscription."
        )


class SubscriptionClient(SubscriptionProtocol):
    def parse_message(self, message: bytes) -> tuple[dict[str, str], bytes]:
        identifier, payload = message.split(b"\n\n", 1)
        return dict([i.split(":", 1) for i in identifier.decode().split("\n")]), payload

    async def handle_message(self, message: bytes) -> None:
        identifier, payload = self.parse_message(message)
        connection_logger.debug(f"Adding payload of length {len(payload)} to data processor for {identifier}")
        DataProcessor(identifier).add_data(payload)

    def build_message(
        self, identifier: dict[str, str], arguments: dict[str, str]
    ) -> bytes:
        return b"\n\n".join(
            [
                b"\n".join([f"{key}:{value}".encode() for key, value in i.items()])
                for i in [identifier, arguments]
            ]
        )

    async def start(self) -> Awaitable[None]:
        reader, writer = await asyncio.open_connection(
            self.host, self.port, limit=10 * 2**20
        )
        connection_logger.info(f"Connected to {self.host}:{self.port}")
        self.set_connection(reader, writer)
        self.ready = True

    async def subscribe(
        self, identifier: dict[str, str], arguments: dict[str, str]
    ) -> Awaitable[AsyncIterable[str]]:
        await self.await_ready(30)
        self.write(self.build_message(identifier, arguments))
        return DataProcessor(identifier).__aiter__()

    async def run(
        self, callback: Optional[Callable[["SubscriptionClient"], Awaitable[None]]] = None
    ) -> Awaitable[None]:
        if callback is not None:
            await asyncio.gather(super().run(), callback(self))
        else:
            await super().run()


class IdentifiableSingleton:
    _instances: dict[
        frozenset[Union[str, tuple[str, str]]] : "IdentifiableSingleton"
    ] = {}
    _imutable_identifier: frozenset[Union[str, tuple[str, str]]]
    _mutable_identifier: dict[str, str]

    def __new__(cls, identifier: dict[str, str], *args, **kwargs) -> Any:
        imutable_identifier = cls.get_imutable_identifier(identifier)
        if imutable_identifier not in cls._instances:
            new_instance = super().__new__(cls)
            new_instance._imutable_identifier = imutable_identifier
            new_instance._mutable_identifier = identifier
            cls._instances[imutable_identifier] = new_instance
        return cls._instances[imutable_identifier]

    @classmethod
    def get_imutable_identifier(
        cls, identifier: Union[dict[str, str], frozenset[Union[str, tuple[str, str]]]]
    ) -> frozenset:
        if isinstance(identifier, frozenset):
            return identifier
        return frozenset((cls.__name__, *identifier.items()))
    
    def __hash__(self) -> int:
        return hash(self._imutable_identifier)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            other = self.get_imutable_identifier(other)
        if hasattr(other, "__hash__"):
            other = hash(other)
        else:
            raise TypeError(f"Cannot compare {type(other)} to {type(self)}")

        return hash(self._imutable_identifier) == other


class DataIterator(AsyncIterable[bytes]):
    def __init__(self, data_processor: "DataProcessor") -> None:
        self.data_processor = data_processor
        self.last_data_state = frozenset()

    def __iter__(self) -> Iterator[Optional[bytes]]:
        return self
    
    def __next__(self) -> Optional[bytes]:
        data = self.data_processor.get_data()
        imutable_data = frozenset(data)
        if imutable_data != self.last_data_state:
            self.last_data_state = imutable_data
            return data[-1]
        return None
    
    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> Awaitable[bytes]:
        while True:
            data = next(self)
            if data is not None:
                return data        
            await asyncio.sleep(0.5)


class DataProcessor(IdentifiableSingleton):
    _data: dict[frozenset[Union[str, tuple[str, str]]] : bytes] = {}
    _queue_size: int = 5

    def add_data(self, data: bytes) -> None:
        connection_logger.debug(f"Adding data of length {len(data)} to {self._imutable_identifier}")
        if self._imutable_identifier not in self._data:
            self._data[self._imutable_identifier] = []
        self._data[self._imutable_identifier] = [
            *self._data[self._imutable_identifier][-self._queue_size :],
            data,
        ]

    def get_data(self) -> list[bytes]:
        if self._imutable_identifier not in self._data:
            self._data[self._imutable_identifier] = []
        return self._data[self._imutable_identifier]

    def __aiter__(self) -> AsyncIterator[bytes]:
        return DataIterator(self)


class DataProtocol(IdentifiableSingleton):
    """
    Base class for data getters and setters.
    """

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DataProtocol):
            other = other._imutable_identifier
        else:
            other = IdentifiableSingleton.get_imutable_identifier(dict(other))
        return self._imutable_identifier == other

    def __aiter__(self) -> AsyncIterable[bytes]:
        return self


class DataGetter(DataProtocol):
    def __init__(
        self,
        identifier: dict[str, str],
        arguments: dict[str, str],
        subscription_client: SubscriptionClient,
    ) -> None:
        self.subscription_client = subscription_client
        self.arguments = arguments
        self.iterator: Optional[AsyncIterable[bytes]] = None

    async def setup(self) -> None:
        self.iterator = await self.subscription_client.subscribe(
            identifier=self._mutable_identifier, arguments=self.arguments
        )

    async def __anext__(self) -> Awaitable[bytes]:
        if self.iterator is None:
            await self.setup()
        return await self.iterator.__anext__()


class DataSetter(DataProtocol):
    def __init__(
        self,
        identifier: dict[str, str],
        arguments: dict[str, str],
        iterator_getter: Callable[[dict[str, str]], Awaitable[AsyncIterable[bytes]]],
    ) -> None:
        self.identifier = identifier
        self.arguments = arguments
        self.iterator_getter = iterator_getter
        self.iterator: Optional[AsyncIterable[bytes]] = None
        connection_logger.debug(f"Created data setter for {self.identifier}")

    async def setup(self) -> Awaitable[None]:
        connection_logger.debug(f"Setting up {self.identifier}")
        self.iterator = await self.iterator_getter(self.arguments)
        connection_logger.debug(f"Set up of {self.identifier} successful")

    async def __anext__(self) -> Awaitable[bytes]:
        if self.iterator is None:
            await self.setup()
        else:
            connection_logger.debug(f"No need to set up {self.identifier}")
        return self, await self.iterator.__anext__()
