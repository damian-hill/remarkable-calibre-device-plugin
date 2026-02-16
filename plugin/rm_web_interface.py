"""HTTP client for the reMarkable USB Web Interface.

Communicates with the device at http://{ip} when USB storage mode is enabled.
Endpoints: GET /documents/{id} for metadata, POST /upload for file transfer.
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import posixpath
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from urllib import request
from urllib.error import HTTPError
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Device document model
# ---------------------------------------------------------------------------

COLLECTION = "CollectionType"
DOCUMENT = "DocumentType"


@dataclass
class DeviceEntry:
    """A single file or folder on the reMarkable."""
    entry_id: str
    parent_id: str
    name: str
    entry_type: str  # "CollectionType" or "DocumentType"
    file_type: str

    @staticmethod
    def from_json(raw: dict) -> DeviceEntry:
        return DeviceEntry(
            entry_id=raw["ID"],
            parent_id=raw.get("Parent", ""),
            # Note: "VissibleName" is the actual field name in the reMarkable API (their typo)
            name=str(raw.get("VissibleName", "")),
            entry_type=str(raw.get("Type", DOCUMENT)),
            file_type=str(raw.get("fileType", "")),
        )

    @property
    def is_folder(self) -> bool:
        return self.entry_type == COLLECTION


@dataclass
class FileTree:
    """Recursive tree of device entries rooted at a folder."""
    entries: list[FileTreeNode] = field(default_factory=list)

    def all_files(self, prefix: str = "") -> list[tuple[str, DeviceEntry]]:
        """Return (path, entry) pairs for all non-folder entries, recursively."""
        result = []
        for node in self.entries:
            if node.entry.is_folder:
                sub_prefix = f"{prefix}{node.entry.name}/"
                result.extend(node.subtree.all_files(sub_prefix))
            else:
                result.append((f"{prefix}{node.entry.name}", node.entry))
        return result

    def all_file_names(self, prefix: str = "") -> list[str]:
        return [path for path, _ in self.all_files(prefix)]

    def all_file_ids(self) -> list[str]:
        """Return entry_id for all non-folder entries, recursively."""
        ids = []
        for node in self.entries:
            if node.entry.is_folder:
                ids.extend(node.subtree.all_file_ids())
            else:
                ids.append(node.entry.entry_id)
        return ids

    def all_folder_paths(self, prefix: str = "") -> list[str]:
        """Return paths of all folders, recursively."""
        result = []
        for node in self.entries:
            if node.entry.is_folder:
                path = f"{prefix}{node.entry.name}"
                result.append(path)
                result.extend(node.subtree.all_folder_paths(f"{path}/"))
        return result

    def folder_id_map(self, prefix: str = "") -> dict[str, str]:
        """Return {folder_path: entry_id} for all folders, recursively."""
        mapping = {}
        for node in self.entries:
            if node.entry.is_folder:
                path = f"{prefix}{node.entry.name}"
                mapping[path] = node.entry.entry_id
                mapping.update(node.subtree.folder_id_map(f"{path}/"))
        return mapping


@dataclass
class FileTreeNode:
    """A single node in the file tree (entry + optional children)."""
    entry: DeviceEntry
    subtree: FileTree = field(default_factory=FileTree)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_MIME_TYPES = {
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
}


def _build_multipart(filename: str, file_data: bytes, content_type: str | None = None) -> tuple[bytes, str]:
    """Build a multipart/form-data body for uploading a single file.

    Returns (body_bytes, content_type_header).
    """
    boundary = f"----remarkable-{uuid.uuid4().hex}"
    if content_type is None:
        ext = os.path.splitext(filename)[1].lower()
        content_type = _MIME_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    buf = io.BytesIO()
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    buf.write(f"Content-Type: {content_type}\r\n".encode())
    buf.write(b"\r\n")
    buf.write(file_data)
    buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())

    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def fetch_documents(ip: str, path_id: str, timeout: int = 10) -> list[dict]:
    """GET /documents/{path_id} — returns list of document metadata dicts."""
    url = f"http://{ip}/documents/{path_id}"
    req = request.Request(url, headers={
        "Content-Type": "application/json",
        "charset": "ISO-8859-1",
    })
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def is_reachable(ip: str) -> bool:
    """Quick connectivity check against the device."""
    try:
        fetch_documents(ip, "", timeout=2)
        return True
    except Exception:
        log.warning("Cannot reach reMarkable at %s", ip, exc_info=True)
        return False


def build_file_tree(ip: str, root_id: str, _depth: int = 0, max_depth: int = 20,
                    progress_cb=None, _counter: list | None = None) -> FileTree:
    """Recursively fetch the full document tree starting from root_id.

    progress_cb(message) is called after each HTTP fetch so the caller
    can update the UI.  _counter tracks total entries found across the
    recursion (internal).
    """
    if _depth >= max_depth:
        log.warning("Max folder depth (%d) reached, stopping recursion", max_depth)
        return FileTree()

    if _counter is None:
        _counter = [0]

    raw_list = fetch_documents(ip, root_id)
    entries = [DeviceEntry.from_json(r) for r in raw_list]
    entries.sort(key=lambda e: e.parent_id)
    _counter[0] += len(entries)

    if progress_cb:
        progress_cb(f"Scanning reMarkable... {_counter[0]} items found")

    tree = FileTree()
    for entry in entries:
        node = FileTreeNode(entry=entry)
        tree.entries.append(node)
        if entry.is_folder:
            node.subtree = build_file_tree(
                ip, entry.entry_id, _depth + 1, max_depth,
                progress_cb=progress_cb, _counter=_counter,
            )

    return tree


def find_folder_id(ip: str, folder_name: str) -> str:
    """Look up a folder's ID by name. Returns "" if not found or empty name."""
    if not folder_name:
        return ""
    try:
        tree = build_file_tree(ip, "", max_depth=3)
        folder_map = tree.folder_id_map()
        # Try exact match first, then case-insensitive
        if folder_name in folder_map:
            return folder_map[folder_name]
        for path, fid in folder_map.items():
            if path.lower() == folder_name.lower():
                return fid
        log.warning("Folder '%s' not found on device, uploading to root", folder_name)
    except Exception:
        log.warning("Failed to look up folder '%s'", folder_name, exc_info=True)
    return ""


class _ProgressBody:
    """File-like wrapper that reports upload progress as data is read."""

    def __init__(self, data: bytes, callback=None):
        self._data = data
        self._pos = 0
        self._cb = callback

    def read(self, size=-1):
        if size < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + size]
            self._pos += len(chunk)
        if self._cb and self._data:
            self._cb(self._pos / len(self._data))
        return chunk

    def __len__(self):
        return len(self._data)


def upload_file(ip: str, local_path: str, folder_id: str, display_name: str,
                inject_cover: bool = True, progress_cb=None, timeout: int = 120,
                navigate: bool = True) -> dict:
    """Upload a file to the reMarkable via POST /upload.

    Epubs are automatically re-packaged to fix ZIP compatibility issues
    and optionally inject a cover page if one is missing.
    progress_cb(fraction) is called as upload bytes are sent.
    Set navigate=False if the caller already navigated to the target folder.
    """
    base = f"http://{ip}"

    # The reMarkable web server is stateful — it needs a GET /documents/
    # before it will accept uploads. Navigate to the target folder (or root).
    if navigate:
        try:
            fetch_documents(ip, folder_id)
        except Exception:
            log.warning("Pre-upload navigation failed for folder=%s", folder_id, exc_info=True)

    # Prepare epub for reMarkable compatibility
    prepared_path, cleanup_path = _prepare_epub(local_path, inject_cover=inject_cover)

    try:
        with open(prepared_path, "rb") as fp:
            body, content_type = _build_multipart(display_name, fp.read())

        upload_data = _ProgressBody(body, progress_cb) if progress_cb else body
        req = request.Request(f"{base}/upload", data=upload_data, headers={
            "Origin": base,
            "Accept": "*/*",
            "Referer": f"{base}/",
            "Connection": "keep-alive",
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
        })
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            log.error("Upload HTTP %d: %s (file=%s, folder=%s, size=%d)",
                       exc.code, error_body, display_name, folder_id, len(body))
            raise RuntimeError(
                f"Upload failed (HTTP {exc.code}): {error_body or 'no details'} "
                f"[file={display_name}, size={len(body)}]"
            ) from exc
    finally:
        if cleanup_path:
            try:
                os.unlink(cleanup_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# EPUB preparation (ZIP fix + cover injection)
# ---------------------------------------------------------------------------

_OPF_NS = "http://www.idpf.org/2007/opf"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

_COVER_PAGE_HTML = """\
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Cover</title></head>
<body style="margin:0;padding:0;">
<div style="text-align:center;">
<img src="{href}" style="max-width:100%;max-height:100%;" alt="Cover"/>
</div>
</body>
</html>
"""


def _prepare_epub(path: str, inject_cover: bool = True) -> tuple[str, str | None]:
    """Re-package an epub for reMarkable compatibility.

    Fixes two issues:
    1. Strips ZIP data descriptor flags (bit 3) that reMarkable firmware
       cannot parse. Calibre sets these when modifying epubs.
    2. Optionally injects a cover page if the epub has a cover image in
       its manifest but no cover page in the reading spine. Without this,
       the device thumbnail shows a text-only first page instead of the
       cover art.

    Returns (path_to_upload, path_to_cleanup_or_none).
    Non-epub files pass through unchanged.
    """
    if not path.lower().endswith(".epub"):
        return path, None

    try:
        with zipfile.ZipFile(path, "r") as src:
            # Locate the OPF package file
            opf_path = _locate_opf(src)
            patched_opf = None
            new_files: dict[str, bytes] = {}

            if opf_path and inject_cover:
                try:
                    opf_bytes = src.read(opf_path)
                    patched_opf, new_files = _ensure_cover_page(src, opf_path, opf_bytes)
                except (KeyError, ET.ParseError):
                    pass

            # Write clean epub — mimetype MUST be first entry with no extra fields
            # per the EPUB OCF spec, otherwise devices reject it as a plain ZIP.
            out = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
            out_path = out.name
            out.close()

            with zipfile.ZipFile(out_path, "w") as dst:
                # Write mimetype first with a clean ZipInfo (no extra fields)
                mi = zipfile.ZipInfo("mimetype")
                mi.compress_type = zipfile.ZIP_STORED
                mi.extra = b""
                dst.writestr(mi, b"application/epub+zip")

                for item in src.infolist():
                    if item.filename == "mimetype":
                        continue  # already written above
                    data = src.read(item.filename)
                    if patched_opf and item.filename == opf_path:
                        data = patched_opf
                    dst.writestr(item.filename, data, compress_type=zipfile.ZIP_DEFLATED)

                for fname, fdata in new_files.items():
                    dst.writestr(fname, fdata, compress_type=zipfile.ZIP_DEFLATED)

            log.debug("Prepared epub: %s -> %s", path, out_path)
            return out_path, out_path

    except zipfile.BadZipFile:
        return path, None


def _locate_opf(zf: zipfile.ZipFile) -> str | None:
    """Find the OPF package document path inside an epub."""
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(f".//{{{_CONTAINER_NS}}}rootfile")
        if rootfile is not None:
            return rootfile.get("full-path")
    except (KeyError, ET.ParseError):
        pass
    for item in zf.infolist():
        if item.filename.endswith(".opf"):
            return item.filename
    return None


def _ensure_cover_page(zf: zipfile.ZipFile, opf_path: str, opf_bytes: bytes) -> tuple[bytes | None, dict[str, bytes]]:
    """If the epub has a cover image but no cover page, inject one.

    Returns (patched_opf_bytes_or_none, {new_filename: bytes}).
    """
    root = ET.fromstring(opf_bytes)

    # Find cover image ID from <meta name="cover" content="..."/>
    cover_img_id = None
    for meta in root.iter(f"{{{_OPF_NS}}}meta"):
        if meta.get("name") == "cover":
            cover_img_id = meta.get("content")
            break
    if not cover_img_id:
        for meta in root.iter("meta"):
            if meta.get("name") == "cover":
                cover_img_id = meta.get("content")
                break

    if not cover_img_id:
        return None, {}

    # Look up the manifest item
    manifest = root.find(f"{{{_OPF_NS}}}manifest")
    if manifest is None:
        return None, {}

    cover_href = None
    for item in manifest.findall(f"{{{_OPF_NS}}}item"):
        if item.get("id") == cover_img_id:
            media = item.get("media-type", "")
            if media.startswith("image/"):
                cover_href = item.get("href")
            break

    if not cover_href:
        return None, {}

    # Check whether the first spine page already shows the cover
    spine = root.find(f"{{{_OPF_NS}}}spine")
    if spine is None or len(spine) == 0:
        return None, {}

    first_ref_id = spine[0].get("idref", "")
    for item in manifest.findall(f"{{{_OPF_NS}}}item"):
        if item.get("id") == first_ref_id:
            href = item.get("href", "")
            opf_dir = posixpath.dirname(opf_path)
            full = posixpath.join(opf_dir, href) if opf_dir else href
            try:
                page_text = zf.read(full).decode("utf-8", errors="replace")
                if cover_href in page_text:
                    return None, {}  # Already has a cover page
            except KeyError:
                pass
            break

    # Build cover page XHTML
    page_id = "rm-cover-page"
    page_filename = "rm_cover.xhtml"
    opf_dir = posixpath.dirname(opf_path)
    page_zip_path = posixpath.join(opf_dir, page_filename) if opf_dir else page_filename

    xhtml = _COVER_PAGE_HTML.format(href=cover_href)

    # Patch manifest
    new_item = ET.SubElement(manifest, f"{{{_OPF_NS}}}item")
    new_item.set("id", page_id)
    new_item.set("href", page_filename)
    new_item.set("media-type", "application/xhtml+xml")

    # Patch spine — insert cover page first
    ref = ET.Element(f"{{{_OPF_NS}}}itemref")
    ref.set("idref", page_id)
    spine.insert(0, ref)

    # Add/create guide element
    guide = root.find(f"{{{_OPF_NS}}}guide")
    if guide is None:
        guide = ET.SubElement(root, f"{{{_OPF_NS}}}guide")
    guide_ref = ET.SubElement(guide, f"{{{_OPF_NS}}}reference")
    guide_ref.set("type", "cover")
    guide_ref.set("title", "Cover")
    guide_ref.set("href", page_filename)

    # Serialize
    ET.register_namespace("", _OPF_NS)
    ET.register_namespace("dc", _DC_NS)
    patched = ET.tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")

    return patched, {page_zip_path: xhtml.encode("utf-8")}
