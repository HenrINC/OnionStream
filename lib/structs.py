import base64
from typing import Union, Optional, get_type_hints

from pydantic import BaseModel, validator


class TranscodingSettings(BaseModel):
    c__v: Optional[str] = "copy"  # Video codec (-c:v)
    c__a: Optional[str] = "copy"  # Audio codec (-c:a)
    preset: Optional[str]  # Encoding preset (-preset)
    tune: Optional[str]  # Encoding tuning (-tune)
    r: Optional[Union[str, int]]  # Frame rate (-r)
    s: Optional[str]  # Resolution (-s)
    b__v: Optional[str]  # Video bitrate (-b:v)
    b__a: Optional[str]  # Audio bitrate (-b:a)
    vf: Optional[str]  # Video filters (-vf)
    af: Optional[str]  # Audio filters (-af)
    map: Optional[str]  # Stream mapping (-map)
    ss: Optional[str]  # Start time offset (-ss)
    t: Optional[str]  # Recording time (-t)
    crf: Optional[Union[str, int]]  # Constant rate factor (-crf)
    maxrate: Optional[Union[str, int]]  # Maximum bitrate (-maxrate)
    bufsize: Optional[Union[str, int]]  # Buffer size (-bufsize)

    @validator("r")
    def validate_framerate(cls, v):
        if v is None:
            return None
        if isinstance(v, (int)) or (hasattr(v, "isdigit") and v.isdigit()):
            v = int(v)
            if v < 0 or v > 120:
                raise ValueError("Framerate must be between 0 and 120")
        else:
            raise ValueError("Framerate must be an integer")
        return v

    @validator("crf")
    def validate_crf(cls, v):
        if v is None:
            return None
        if isinstance(v, (int)) or (hasattr(v, "isdigit") and v.isdigit()):
            v = int(v)
            if v < 0 or v > 51:
                raise ValueError("CRF must be between 0 and 51")
        else:
            raise ValueError("CRF must be an integer")
        return v

    @validator("b__v", "b__a", "maxrate", "bufsize")
    def validate_bitrate(cls, v):
        if v is None:
            return None
        if isinstance(v, (int)) or (hasattr(v, "isdigit") and v.isdigit()):
            # Try to convert the bitrate to an integer. This will succeed
            # if the bitrate is specified in bits per second.
            bitrate = int(v)
        else:
            # If the bitrate is specified as a string with a suffix (e.g. "1k" or "1M"),
            # strip the suffix and convert the remaining part to an integer.
            suffix = v[-1].lower()
            bitrate = v[:-1]
            if not (suffix in ["k", "m", "g"] and bitrate.isdigit()):
                raise ValueError("Bitrate must be an integer or end with k, m, or g")

            bitrate = int(bitrate)
            if suffix == "k":
                bitrate *= 1000
            elif suffix == "m":
                bitrate *= 1000000
            elif suffix == "g":
                bitrate *= 1000000000

        if bitrate < 0:
            raise ValueError("Bitrate must be positive")

        # Adding a check to ensure the bitrate does not exceed 1 Mbps.
        if bitrate > 1000000:
            raise ValueError(
                "Bitrate must not exceed 1 Mbps to keep the Tor network safe"
            )

        return str(bitrate)  # Return the bitrate as a string


class EncryptionKey(BaseModel):
    salt: bytes
    bytes: bytes
    hash: str
    creation_time: int
    ttl: int

    def to_bytes(self) -> bytes:
        conversion = {
            bytes: lambda x: x,
            str: lambda x: x.encode(),
            int: lambda x: str(x).encode(),
        }
        return b"\n".join(
            [
                k.encode() + b":" + base64.b64encode(conversion[type(v)](v))
                for k, v in self.dict().items()
            ]
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "EncryptionKey":
        conversion = {
            bytes: lambda x: x,
            str: lambda x: x.decode(),
            int: lambda x: int(x.decode()),
        }
        types_hints = get_type_hints(cls)
        try:
            return cls(
                **{
                    k.decode(): conversion[types_hints[k.decode()]](base64.b64decode(v))
                    for k, v in [line.split(b":", 1) for line in data.split(b"\n")]
                }
            )
        except ValueError:
            breakpoint()
            raise


class Segment(BaseModel):
    duration: float
    uid: str
    encryption_key: EncryptionKey
    transcoding_settings: Optional[TranscodingSettings] = None
    iv: bytes
    media_sequence: int
    bytes: bytes


class Playlist(BaseModel):
    playlist_type: Optional[str] = "EVENT"
    segments: list[Segment]

    @property
    def media_sequence(self) -> int:
        return self.segments[0].media_sequence

    @property
    def bytes(self) -> bytes:
        lines: list[bytes] = [
            b"#EXTM3U",
            b"#EXT-X-VERSION:3",
            f"#EXT-X-PLAYLIST-TYPE:{self.playlist_type}".encode(),
            f"#EXT-X-MEDIA-SEQUENCE:{self.media_sequence}".encode(),
        ]
        for segment in self.segments:
            lines += [
                f'#EXT-X-KEY:METHOD=AES-128,URI="key.bin?key_hash={segment.encryption_key.hash}",IV=0x{segment.iv.hex().upper()}'.encode(),
                f"#EXTINF:{segment.duration},".encode(),
                f"segment.ts?uuid={segment.uid}&key_hash={segment.encryption_key.hash}".encode(),
            ]
        return b"\n".join(lines)

    @property
    def duration(self) -> float:
        return sum([segment.duration for segment in self.segments])


class Source(BaseModel):
    source: Optional[str]


class BaseRequest(Source, TranscodingSettings):
    pass


class PlaylistRequest(BaseRequest):
    pass


class SegmentRequest(BaseRequest):
    uuid: str
    key_hash: str


class EncryptionKeyRequest(BaseRequest):
    key_hash: str
