"""Photo and logo storage: local disk for development or S3-compatible storage in production.
Every image is re-encoded, which also strips EXIF data such as GPS locations of sensitive species."""
from __future__ import annotations

import io
import logging
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings

log = logging.getLogger("tripreports.storage")
Image.MAX_IMAGE_PIXELS = 60_000_000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class BadImage(Exception):
    pass


def process_image(data: bytes, max_side: int = 1800, quality: int = 84) -> tuple[bytes, int, int]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise BadImage("too_large")
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)  # no exif passed => stripped
        return out.getvalue(), im.width, im.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise BadImage("unreadable") from e


def new_key(org_id: str, kind: str = "p") -> str:
    return f"{org_id}/{kind}_{secrets.token_hex(12)}.jpg"


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("bad key")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.is_file() else None

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except ValueError:
            pass

    def url(self, key: str) -> str | None:
        return None  # served through the app


class S3Storage:
    def __init__(self):
        import boto3
        self.bucket = settings.s3_bucket
        self.s3 = boto3.client("s3", region_name=settings.s3_region or None,
                               endpoint_url=settings.s3_endpoint_url or None)

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="image/jpeg",
                           CacheControl="private, max-age=86400")

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception:
            return None

    def delete(self, key: str) -> None:
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            log.warning("S3 delete failed for %s: %s", key, e)

    def url(self, key: str) -> str | None:
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key},
                                              ExpiresIn=3600)


class DBStorage:
    """Keeps images in the database. Fine for a start (Postgres free tiers hold thousands of
    report photos); switch to S3/R2 when you outgrow it."""

    def _db(self):
        from ..db import SessionLocal
        return SessionLocal()

    def put(self, key: str, data: bytes) -> None:
        from ..models import Blob
        with self._db() as db:
            db.merge(Blob(key=key, data=data))
            db.commit()

    def get(self, key: str) -> bytes | None:
        from ..models import Blob
        with self._db() as db:
            b = db.get(Blob, key)
            return bytes(b.data) if b else None

    def delete(self, key: str) -> None:
        from ..models import Blob
        with self._db() as db:
            b = db.get(Blob, key)
            if b:
                db.delete(b)
                db.commit()

    def url(self, key: str) -> str | None:
        return None


_store = None


def store():
    global _store
    if _store is None:
        if settings.storage == "s3":
            _store = S3Storage()
        elif settings.storage == "db":
            _store = DBStorage()
        else:
            _store = LocalStorage(settings.upload_dir)
    return _store
