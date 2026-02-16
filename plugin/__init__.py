"""Calibre device plugin for the reMarkable Paper tablet.

Sends ePub and PDF files to the reMarkable via its USB Web Interface.
No developer mode required.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import TYPE_CHECKING, List

from calibre.devices.interface import DevicePlugin  # type: ignore
from calibre.devices.usbms.deviceconfig import DeviceConfig  # type: ignore

from . import rm_web_interface
from .log_helper import trace_calls
from .rm_data import Book, DeviceBookList, DeviceInfo, PluginSettings

if TYPE_CHECKING:
    from calibre.ebooks.metadata.book.base import Metadata  # type: ignore

PLUGIN_NAME = "remarkable-calibre-device-plugin"
LOGGER = logging.getLogger(__name__)

# Screen dimensions by model (width × height in inches)
DEVICE_PAGE_SIZE: dict[str, tuple[float, float]] = {
    "rm2":       (6.2, 8.3),   # rM1/rM2: 1404×1872 @ 226 DPI
    "paper-pro": (7.1, 9.4),   # Paper Pro: 1620×2160 @ 229 DPI
    "pro-move":  (3.6, 6.4),   # Paper Pro Move: 954×1696 @ 264 DPI
}

# PDF conversion settings by model (margin and font_size in points)
DEVICE_PDF_SETTINGS: dict[str, dict[str, int]] = {
    "rm2":       {"margin": 36, "font_size": 18},
    "paper-pro": {"margin": 36, "font_size": 20},
    "pro-move":  {"margin": 18, "font_size": 14},
}

# Session state
_device: DeviceInfo | None = None
_ebook_convert_path: str | None = None


def _books_from_tree(tree: rm_web_interface.FileTree) -> list[Book]:
    """Convert a device file tree into Book entries for the booklist."""
    return [
        Book(title=entry.name or path, uuid="", rm_uuid=entry.entry_id, path=path)
        for path, entry in tree.all_files()
    ]


def _find_ebook_convert() -> str:
    """Locate Calibre's ebook-convert CLI tool (cached after first call)."""
    global _ebook_convert_path
    if _ebook_convert_path is not None:
        return _ebook_convert_path

    import shutil
    import sys

    # Walk up from sys.executable looking for ebook-convert
    d = os.path.abspath(sys.executable)
    while True:
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
        for name in ('ebook-convert', 'ebook-convert.exe'):
            path = os.path.join(d, name)
            if os.path.isfile(path):
                _ebook_convert_path = path
                return _ebook_convert_path

    # Fallback: system PATH
    _ebook_convert_path = shutil.which('ebook-convert') or 'ebook-convert'
    return _ebook_convert_path


def _convert_epub_to_pdf(epub_path: str, model: str, progress_cb=None,
                         margin_override: int = 0, font_size_override: int = 0,
                         font_override: str = "",
                         embed_all_fonts: bool = True) -> str:
    """Convert an EPUB to PDF with page dimensions matched to the device.

    Shells out to ebook-convert (Calibre's CLI) because the PDF output
    plugin requires Qt, which is unavailable in device threads.
    Returns path to the temporary PDF (caller must clean up).

    Override values (margin, font_size, font) take precedence when non-zero/non-empty.
    Zero/empty means use model defaults from DEVICE_PDF_SETTINGS.

    progress_cb, if provided, is called with a float 0.0..1.0 as
    ebook-convert reports its progress on stderr.
    """
    import re
    import subprocess
    import sys
    import time

    width_in, height_in = DEVICE_PAGE_SIZE.get(model, DEVICE_PAGE_SIZE["paper-pro"])
    pdf_settings = DEVICE_PDF_SETTINGS.get(model, DEVICE_PDF_SETTINGS["paper-pro"])
    margin = str(margin_override if margin_override else pdf_settings["margin"])
    font_size = str(font_size_override if font_size_override else pdf_settings["font_size"])

    fd, out_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    exe = _find_ebook_convert()
    cmd = [
        exe, epub_path, out_path,
        '--output-profile', 'generic_eink_hd',
        '--custom-size', f'{width_in}x{height_in}',
        '--pdf-page-margin-top', margin,
        '--pdf-page-margin-bottom', margin,
        '--pdf-page-margin-left', margin,
        '--pdf-page-margin-right', margin,
        '--pdf-default-font-size', font_size,
    ]
    if embed_all_fonts:
        cmd.append('--embed-all-fonts')
    if font_override:
        cmd.extend(['--pdf-serif-family', font_override])

    popen_kwargs: dict = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if sys.platform == 'win32':
        popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    pct_re = re.compile(r'(\d+)%')
    timeout_secs = 300

    try:
        LOGGER.info("Converting EPUB to PDF: %s", ' '.join(cmd))
        proc = subprocess.Popen(cmd, **popen_kwargs)
        deadline = time.monotonic() + timeout_secs

        # Read stderr line-by-line for progress updates.
        # ebook-convert writes progress like "33% Converting..." to stderr.
        for line in proc.stderr:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise TimeoutError(
                    f"ebook-convert timed out after {timeout_secs}s"
                )
            m = pct_re.search(line)
            if m and progress_cb is not None:
                progress_cb(int(m.group(1)) / 100.0)

        proc.wait()

        if proc.returncode != 0:
            # Collect any remaining stdout for diagnostics
            stdout_tail = (proc.stdout.read() or "")[:500]
            LOGGER.error("ebook-convert failed (rc=%d): %s", proc.returncode, stdout_tail)
            raise RuntimeError(f"Conversion failed (rc={proc.returncode}): {stdout_tail}")

        LOGGER.info("Converted EPUB to PDF: %s (%s, %.1fx%.1f in)", out_path, model, width_in, height_in)
        return out_path
    except Exception:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise


class RemarkableUsbDevice(DeviceConfig, DevicePlugin):
    VENDOR_ID = 0x04B3
    PRODUCT_ID = 0x4010

    name = PLUGIN_NAME
    description = "Send ePub and PDF files to reMarkable — no developer mode required"
    author = "Damian Hill"
    supported_platforms = ["linux", "windows", "osx"]
    version = (1, 3, 0)
    minimum_calibre_version = (0, 7, 53)

    FORMATS = ["epub", "pdf"]
    CAN_SET_METADATA: list[str] = []
    MANAGES_DEVICE_PRESENCE = True
    SUPPORTS_SUB_DIRS = False
    HIDE_FORMATS_CONFIG_BOX = True
    NEWS_IN_FOLDER = False
    USER_CAN_ADD_NEW_FORMATS = False
    MUST_READ_METADATA = False
    SUPPORTS_USE_AUTHOR_SORT = False

    EXTRA_CUSTOMIZATION_MESSAGE = [  # type: ignore
        "IP address:::"
        "<p>"
        "The IP address of your reMarkable device. Connect via USB and enable "
        "Settings &gt; Storage to use the USB web interface."
        "</p>",

        "Device model:::"
        "<p>"
        "Your reMarkable model: <b>rm2</b> (reMarkable 1/2), "
        "<b>paper-pro</b> (Paper Pro 11.8\"), or "
        "<b>pro-move</b> (Paper Pro Move 7.3\"). "
        "Sets PDF page size to match your screen."
        "</p>",

        "Preferred format:::"
        "<p>"
        "<b>epub</b> or <b>pdf</b>. When set to pdf, EPUBs are automatically "
        "converted with page dimensions optimized for your device model."
        "</p>",

        "Target folder:::"
        "<p>"
        "Name of a folder on your reMarkable to upload into. "
        "Leave empty to upload to the root. Example: <b>Calibre</b>"
        "</p>",

        "Inject cover page when missing",
    ]
    EXTRA_CUSTOMIZATION_DEFAULT = [  # type: ignore
        "10.11.99.1",
        "paper-pro",
        "pdf",
        "",
        True,
        0,     # pdf_margin: 0 = use model default
        0,     # pdf_font_size: 0 = use model default
        "",    # pdf_font: "" = system default serif
        True,  # embed_all_fonts: embed all fonts in PDF output
    ]

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def config_widget(self):
        from .config_widget import RemarkableConfigWidget
        return RemarkableConfigWidget(self)

    @classmethod
    def save_settings(cls, config_widget):
        cls._config().set('extra_customization', config_widget.commit())

    @classmethod
    def _settings(cls) -> PluginSettings:
        extra = cls.settings().extra_customization or []
        defaults = cls.EXTRA_CUSTOMIZATION_DEFAULT
        def _get(i, fallback):
            return extra[i] if i < len(extra) and extra[i] is not None else fallback
        return PluginSettings(
            IP=_get(0, defaults[0]),
            model=_get(1, defaults[1]),
            preferred_format=_get(2, defaults[2]),
            target_folder=_get(3, defaults[3]),
            inject_cover=_get(4, defaults[4]),
            pdf_margin=int(_get(5, defaults[5]) or 0),
            pdf_font_size=int(_get(6, defaults[6]) or 0),
            pdf_font=str(_get(7, defaults[7]) or ""),
            embed_all_fonts=bool(_get(8, defaults[8])),
        )

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    _last_detection_check: float = 0.0
    _DETECTION_INTERVAL: float = 5.0  # seconds between HTTP polls

    @trace_calls
    def startup(self):
        super().startup()
        cfg = self._settings()
        if cfg.preferred_format == "pdf":
            self.FORMATS = ["pdf", "epub"]
        else:
            self.FORMATS = ["epub", "pdf"]

    @trace_calls
    def detect_managed_devices(self, devices_on_system: List, force_refresh=False):
        import time
        global _device
        cfg = self._settings()

        now = time.monotonic()
        if not force_refresh and (now - self._last_detection_check) < self._DETECTION_INTERVAL:
            return _device
        self._last_detection_check = now

        try:
            if rm_web_interface.is_reachable(cfg.IP):
                if _device is None:
                    _device = DeviceInfo(cfg.IP)
                    LOGGER.info("Detected: %s", _device)
                return _device
        except Exception:
            LOGGER.warning("Device detection failed", exc_info=True)
            _device = None
        return None

    @trace_calls
    def debug_managed_device_detection(self, devices_on_system, output):
        result = self.detect_managed_devices(devices_on_system, True)
        if output:
            msg = f"reMarkable detected: {result is not None}\n"
            if result:
                msg += f"  Device: {result}\n"
            try:
                output.write(msg.encode("utf-8"))
            except TypeError:
                output.write(msg)
        return result

    @trace_calls
    def is_usb_connected(self, devices_on_system, debug=False, only_presence=False):
        return _device is not None, _device

    @trace_calls
    def eject(self):
        global _device
        _device = None

    @trace_calls
    def get_device_information(self, end_session=True):
        if _device is not None:
            return (str(_device), "", "", "application/epub")
        return ("reMarkable (not connected)", "", "", "")

    @trace_calls
    def get_device_uid(self):
        return str(_device.session_id) if _device else ""

    @trace_calls
    def total_space(self, end_session=True):
        return 999_999_999, -1, -1

    @trace_calls
    def free_space(self, end_session=True):
        return 999_999_999, -1, -1

    @trace_calls
    def card_prefix(self, end_session=True):
        return None, None

    # ------------------------------------------------------------------
    # Book listing & sync
    # ------------------------------------------------------------------

    @trace_calls
    def books(self, oncard=None, end_session=True):
        if oncard is not None:
            return DeviceBookList()
        bl = (DeviceBookList(), None, None)
        result, _, _ = self.sync_booklists(bl)
        return result

    @trace_calls
    def sync_booklists(self, booklists, end_session=True):
        cfg = self._settings()
        if booklists is None:
            return DeviceBookList(), None, None

        booklist, _, _ = booklists

        self.report_progress(0.01, "Connecting to reMarkable...")

        try:
            def _scan_progress(msg):
                # Parse "Scanning reMarkable... N items found" and map
                # N to a fraction between 0.1 and 0.7 (assume ~100 items max).
                import re
                m = re.search(r'(\d+)\s+items?\s+found', msg)
                if m:
                    count = int(m.group(1))
                    frac = 0.1 + min(count / 100.0, 1.0) * 0.6
                else:
                    frac = 0.1
                self.report_progress(frac, msg)

            tree = rm_web_interface.build_file_tree(
                cfg.IP, "", progress_cb=_scan_progress,
            )
            self.report_progress(0.8, "Building book list...")
            on_device = _books_from_tree(tree)
            LOGGER.info("Book list: %d entries", len(on_device))
        except Exception:
            LOGGER.warning("Failed to fetch book list", exc_info=True)
            on_device = []

        self.report_progress(0.9, "Syncing book list...")

        for book in booklist:
            if book not in on_device:
                on_device.append(book)

        for book in on_device:
            if book not in booklist:
                booklist.append(book)

        self.report_progress(1.0, "")
        return booklist, None, None

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    @trace_calls
    def upload_books(self, files_original, names, on_card=None, end_session=True, metadata: list[Metadata] = None):
        if not files_original:
            return ([], metadata or [], None)

        from concurrent.futures import ThreadPoolExecutor, as_completed

        cfg = self._settings()
        locations = []
        metadata = metadata or [None] * len(files_original)

        # Resolve target folder name to device folder ID.
        # The web server is stateful: GET /documents/{id} sets the "current
        # directory" and POST /upload places files there.  The folder must
        # already exist on the device (the web interface cannot create folders).
        folder_id = ""
        if cfg.target_folder:
            folder_id = rm_web_interface.find_folder_id(cfg.IP, cfg.target_folder)
            if folder_id:
                LOGGER.info("Uploading to folder: %s (id=%s)", cfg.target_folder, folder_id)
            else:
                LOGGER.warning(
                    "Folder '%s' not found on device — uploading to root. "
                    "Create the folder on your reMarkable first, then retry.",
                    cfg.target_folder,
                )

        n = len(files_original)

        # ------------------------------------------------------------------
        # Phase 1: Convert EPUBs to PDF in parallel (CPU-bound subprocesses)
        # ------------------------------------------------------------------
        # Build a list of (index, local_path, upload_name, needs_convert)
        # and pre-convert all EPUBs before uploading.
        upload_items: list[dict] = []
        for i, (local_path, visible_name, meta) in enumerate(zip(files_original, names, metadata)):
            upload_name = os.path.basename(visible_name)
            needs_convert = (cfg.preferred_format == "pdf"
                             and os.path.splitext(local_path)[1].lower() == ".epub")
            upload_items.append({
                "index": i,
                "local_path": local_path,
                "upload_name": upload_name,
                "visible_name": visible_name,
                "meta": meta,
                "needs_convert": needs_convert,
                "converted_path": None,  # filled by conversion phase
                "cleanup_path": None,
            })

        items_to_convert = [it for it in upload_items if it["needs_convert"]]
        if items_to_convert:
            # Scale workers: 1 per book, capped at CPU count (min 2, max 4)
            max_workers = min(max(os.cpu_count() or 2, 2), 4, len(items_to_convert))
            LOGGER.info("Converting %d EPUBs in parallel (%d workers)", len(items_to_convert), max_workers)
            self.report_progress(0.01, f"Converting {len(items_to_convert)} books...")

            convert_done = 0

            def _do_convert(item):
                return _convert_epub_to_pdf(
                    item["local_path"], cfg.model,
                    margin_override=cfg.pdf_margin,
                    font_size_override=cfg.pdf_font_size,
                    font_override=cfg.pdf_font,
                    embed_all_fonts=cfg.embed_all_fonts,
                )

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_item = {pool.submit(_do_convert, it): it for it in items_to_convert}
                for future in as_completed(future_to_item):
                    item = future_to_item[future]
                    try:
                        pdf_path = future.result()
                        item["converted_path"] = pdf_path
                        item["cleanup_path"] = pdf_path
                        item["local_path"] = pdf_path
                        item["upload_name"] = os.path.splitext(item["upload_name"])[0] + ".pdf"
                    except Exception:
                        LOGGER.error("Conversion failed for %s", item["upload_name"], exc_info=True)
                        raise
                    convert_done += 1
                    frac = 0.01 + (convert_done / len(items_to_convert)) * 0.39
                    self.report_progress(frac, f"Converted {convert_done}/{len(items_to_convert)}")

        # ------------------------------------------------------------------
        # Phase 2: Upload sequentially (device handles one at a time)
        # ------------------------------------------------------------------
        # Navigate to target folder once before the upload loop.
        if folder_id:
            try:
                rm_web_interface.fetch_documents(cfg.IP, folder_id)
            except Exception:
                LOGGER.warning("Pre-upload folder navigation failed", exc_info=True)

        upload_base = 0.40 if items_to_convert else 0.01

        for i, item in enumerate(upload_items):
            upload_frac_start = upload_base + (i / n) * (1.0 - upload_base)
            upload_frac_end = upload_base + ((i + 1) / n) * (1.0 - upload_base)

            self.report_progress(upload_frac_start, f"Uploading: {item['upload_name']}")

            def _upload_progress(frac, _s=upload_frac_start, _e=upload_frac_end):
                self.report_progress(_s + frac * (_e - _s),
                                     f"Uploading: {item['upload_name']}")

            try:
                locations.append(item["visible_name"])
                LOGGER.info("Uploading: %s as %s", item["local_path"], item["upload_name"])
                rm_web_interface.upload_file(
                    cfg.IP, item["local_path"], folder_id, item["upload_name"],
                    inject_cover=cfg.inject_cover,
                    progress_cb=_upload_progress,
                    navigate=False,  # already navigated above
                )
            finally:
                if item["cleanup_path"]:
                    try:
                        os.unlink(item["cleanup_path"])
                    except OSError:
                        pass

            self.report_progress(upload_frac_end, "")

        return (locations, metadata, None)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    @trace_calls
    def delete_books(self, paths, end_session=True):
        # The USB web interface only supports GET and POST — no DELETE endpoint.
        # We MUST raise here so Calibre shows the error to the user and does NOT
        # call remove_books_from_metadata (which would desync the booklist —
        # the book would vanish from Calibre then reappear on next sync).
        from calibre.devices.errors import UserFeedback

        book_names = "\n".join(f"  - {os.path.basename(p)}" for p in paths)
        raise UserFeedback(
            "Cannot delete via USB web interface",
            f"The reMarkable USB web interface does not support deleting books.\n\n"
            f"Please delete these directly on your reMarkable:\n{book_names}",
            UserFeedback.WARNING,
        )

    @classmethod
    def remove_books_from_metadata(cls, paths, booklists):
        bl: DeviceBookList = booklists[0]
        for book in [b for b in bl if b.path in paths]:
            bl.remove_book(book)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @classmethod
    @trace_calls
    def add_books_to_metadata(cls, locations, metadata: list[Metadata], booklists):
        bl = booklists[0]
        for i, meta in enumerate(metadata):
            pubdate = meta.get("pubdate")
            book = Book(
                title=meta.get("title"),
                uuid=meta.get("uuid"),
                authors=meta.get("authors"),
                size=meta.get("size"),
                datetime=pubdate.timetuple() if pubdate else None,
                tags=meta.get("tags"),
                path=locations[0][i],
            )
            if book not in bl:
                bl.append(book)

    # ------------------------------------------------------------------
    # Passthrough methods (Calibre API requires these exist)
    # ------------------------------------------------------------------

    def report_progress(self, x, y):
        """No-op default; replaced by Calibre via set_progress_reporter."""
        LOGGER.debug("report_progress(%.3f, %r) — using default no-op", x, y)
        return x

    @trace_calls
    def open(self, connected_device, library_uuid): pass

    @trace_calls
    def get_driveinfo(self): return super().get_driveinfo()

    @trace_calls
    def get_file(self, path, outfile, end_session=True): return super().get_file(path, outfile, end_session)

    @trace_calls
    def set_driveinfo_name(self, location_code, name): return super().set_driveinfo_name(location_code, name)

    @trace_calls
    def set_library_info(self, library_name, library_uuid, field_metadata): return super().set_library_info(library_name, library_uuid, field_metadata)

    @trace_calls
    def set_plugboards(self, plugboards, pb_func): return super().set_plugboards(plugboards, pb_func)

    @trace_calls
    def set_progress_reporter(self, report_progress):
        LOGGER.info("set_progress_reporter: %s", report_progress)
        self.report_progress = report_progress or (lambda x, y: x)

    @trace_calls
    def shutdown(self): return super().shutdown()

    @trace_calls
    def synchronize_with_db(self, db, book_id, book_metadata, first_call): return super().synchronize_with_db(db, book_id, book_metadata, first_call)

    @trace_calls
    def prepare_addable_books(self, paths): return super().prepare_addable_books(paths)

    @trace_calls
    def ignore_connected_device(self, uid): pass

    @trace_calls
    def post_yank_cleanup(self): return super().post_yank_cleanup()
