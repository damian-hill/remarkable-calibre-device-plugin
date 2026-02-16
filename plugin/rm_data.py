"""Data models for the reMarkable Calibre plugin."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import List

from calibre.devices.interface import BookList  # type: ignore


@dataclass
class PluginSettings:
    """Plugin configuration from Calibre's settings dialog."""
    IP: str
    model: str = "paper-pro"       # "rm2", "paper-pro", or "pro-move"
    preferred_format: str = "epub"  # "epub" or "pdf"
    target_folder: str = ""         # folder name on device, "" for root
    inject_cover: bool = True       # inject cover page into EPUBs
    pdf_margin: int = 0             # 0 = use model default
    pdf_font_size: int = 0          # 0 = use model default
    pdf_font: str = ""              # "" = system default serif
    embed_all_fonts: bool = True    # embed all fonts in PDF output


@dataclass
class DeviceInfo:
    """Describes a detected reMarkable device."""
    ip: str
    session_id: int = field(default_factory=lambda: random.randint(0, 9_999_999_999))

    def __str__(self) -> str:
        return f"reMarkable at http://{self.ip} (session={self.session_id})"


class DeviceBookList(BookList):
    """Calibre BookList implementation for the reMarkable."""

    def __init__(self, oncard="", prefix="", settings=""):
        super().__init__(oncard, prefix, settings)

    def supports_collections(self):
        return False

    def add_book(self, book, replace_metadata=None):
        self.append(book)

    def remove_book(self, book):
        self.remove(book)

    def get_collections(self, collection_attributes):
        return self


@dataclass
class Book:
    """A book tracked by the plugin (on device or in transit)."""
    title: str
    uuid: str
    rm_uuid: str = ""
    authors: list[str] = field(default_factory=list)
    author_sort: str = ""
    size: int = 0
    datetime: time.struct_time = field(default_factory=time.localtime)
    thumbnail: object = None
    tags: list[str] = field(default_factory=list)
    path: str = "/"
    device_collections: List = field(default_factory=list)
    in_library: str | None = None  # set by Calibre to indicate library match

    def __post_init__(self):
        if isinstance(self.datetime, (list, tuple)):
            self.datetime = time.struct_time(self.datetime)

    def __eq__(self, other):
        """Loose equality: two Books match if ANY shared identifier matches.

        Three tiers are checked in order:
          1. rm_uuid — the reMarkable device's internal document ID.
             Books from _books_from_tree have rm_uuid but uuid="".
          2. uuid — Calibre's library UUID.
             Books from add_books_to_metadata have uuid but rm_uuid="".
          3. path — display path on the device (excluding root "/").

        Because each tier requires BOTH sides to have a non-empty value,
        a device-scanned book (uuid="") and a Calibre-added book
        (rm_uuid="") will only match on path.  Books uploaded outside
        Calibre (e.g. via the reMarkable desktop app) get a device
        rm_uuid but no Calibre uuid, and their path is just the
        filename — so they match Calibre entries only when the display
        name is identical.  When names diverge, sync_booklists appends
        both, creating phantom duplicates.
        """
        if not isinstance(other, Book):
            return NotImplemented
        if self.rm_uuid and other.rm_uuid and self.rm_uuid == other.rm_uuid:
            return True
        if self.uuid and other.uuid and self.uuid == other.uuid:
            return True
        if self.path and other.path and self.path != "/" and other.path != "/" and self.path == other.path:
            return True
        return False
