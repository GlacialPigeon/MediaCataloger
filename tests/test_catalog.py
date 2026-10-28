# Media Cataloger
# Author: GlacialPigeon
# GitHub: https://github.com/GlacialPigeon

"""Fast checks without FFprobe: detection, names and version, database rename, paths, quotes, locks, localization."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import config, constants, localization, probe  # noqa: E402
from modules.database import Database, migrate_legacy_database  # noqa: E402
from modules.logger import RunLogger  # noqa: E402
from modules.platform_api import remove_outer_quotes  # noqa: E402

LINUX = sys.platform.startswith("linux")
IS_WINDOWS = sys.platform == "win32"


def quiet_logger() -> RunLogger:
    return RunLogger(None)


class BitDepth(unittest.TestCase):
    def test_pixel_format_names(self) -> None:
        expected = {
            "yuv410p": 8, "yuv420p": 8, "nv12": 8, "nv16": 8, "yuv420p10le": 10, "p010le": 10, "yuv444p12le": 12, "gray12le": 12,
            "yuva420p9le": 9, "yuv420p14le": 14, "gbrp16le": 16, "rgb48le": 16, "bgra64be": 16, "p416le": 16,
        }
        for name, depth in expected.items():
            self.assertEqual(probe.pixel_format_bit_depth(name), depth, name)

    def test_unknown_names_are_not_guessed(self) -> None:
        for name in ("nv20le", "rgb565le", "weird", "", None):
            self.assertIsNone(probe.pixel_format_bit_depth(name), name)

    def test_yuv410p_is_not_ten_bit(self) -> None:
        self.assertEqual(probe.derive_bit_depth({"pix_fmt": "yuv410p"}), 8)

    def test_a_declared_depth_that_does_not_fit_the_pixel_format_is_no_data(self) -> None:
        self.assertIsNone(probe.derive_bit_depth({"bits_per_raw_sample": "10", "pix_fmt": "yuv420p"}))

    def test_a_declared_depth_that_fits_is_used(self) -> None:
        self.assertEqual(probe.derive_bit_depth({"bits_per_raw_sample": "10", "pix_fmt": "yuv420p10le"}), 10)
        self.assertEqual(probe.derive_bit_depth({"bits_per_raw_sample": "8", "pix_fmt": "yuv420p10le"}), 8)
        self.assertEqual(probe.derive_bit_depth({"bits_per_raw_sample": "N/A", "pix_fmt": "yuv420p10le"}), 10)
        self.assertIsNone(probe.derive_bit_depth({}))


class Resolution(unittest.TestCase):
    def test_missing_or_impossible_sizes_are_unknown(self) -> None:
        for size in ((None, None), (None, 1080), (1920, None), (0, 0), (0, 1080), (-1, 720)):
            self.assertEqual(probe.resolution_category(*size), "UNKNOWN", size)

    def test_cropped_frames_keep_their_class(self) -> None:
        self.assertEqual(probe.resolution_category(1916, 1036), "1080p")
        self.assertEqual(probe.resolution_category(1904, 800), "1080p")
        self.assertEqual(probe.resolution_category(1280, 536), "720p")
        self.assertEqual(probe.resolution_category(3840, 1600), "4K")

    def test_standard_sizes_and_portrait(self) -> None:
        expected = {(720, 480): "SD", (1280, 720): "720p", (1920, 1080): "1080p", (2560, 1440): "1440p", (3840, 2160): "4K",
                    (7680, 4320): "8K", (1080, 1920): "1080p"}
        for size, category in expected.items():
            self.assertEqual(probe.resolution_category(*size), category, size)


class Hdr(unittest.TestCase):
    def test_pq_alone_is_not_called_hdr10(self) -> None:
        self.assertEqual(probe.classify_hdr({"color_transfer": "smpte2084"}, None), "HDR10 / PQ")

    def test_static_metadata_makes_it_hdr10(self) -> None:
        item = {"hdr_type": "HDR10 / PQ", "max_cll": 1000}
        probe.refine_hdr_type(item)
        self.assertEqual(item["hdr_type"], "HDR10")
        item = {"hdr_type": "HDR10 / PQ", "mastering_max_luminance": 1000.0}
        probe.refine_hdr_type(item)
        self.assertEqual(item["hdr_type"], "HDR10")
        item = {"hdr_type": "HDR10 / PQ"}
        probe.refine_hdr_type(item)
        self.assertEqual(item["hdr_type"], "HDR10 / PQ")

    def test_bt2020_without_a_transfer_is_unknown_not_hdr(self) -> None:
        self.assertEqual(probe.classify_hdr({"color_primaries": "bt2020"}, None), "UNKNOWN")
        self.assertEqual(probe.classify_hdr({"color_space": "bt2020nc", "color_transfer": "unknown"}, None), "UNKNOWN")

    def test_missing_color_information_is_unknown_not_sdr(self) -> None:
        self.assertEqual(probe.classify_hdr({}, None), "UNKNOWN")

    def test_known_transfers(self) -> None:
        self.assertEqual(probe.classify_hdr({"color_transfer": "arib-std-b67"}, None), "HLG")
        for transfer in ("bt709", "bt2020-10", "smpte170m"):
            self.assertEqual(probe.classify_hdr({"color_transfer": transfer, "color_primaries": "bt2020"}, None), "SDR", transfer)

    def test_dolby_vision_or_hdr10plus_upgrades_unknown_and_sdr(self) -> None:
        for kind in ("UNKNOWN", "SDR"):
            for flag in ("dolby_vision_present", "hdr10_plus_present"):
                item = {"hdr_type": kind, flag: 1}
                probe.refine_hdr_type(item)
                self.assertEqual(item["hdr_type"], "HDR", (kind, flag))

    def test_streams_with_unknown_type_get_the_second_pass(self) -> None:
        self.assertIn("UNKNOWN", probe.HDR_TYPES_TO_CHECK)
        self.assertNotIn("SDR", probe.HDR_TYPES_TO_CHECK)


def probe_json(stream: dict) -> dict:
    return {"format": {"format_name": "matroska,webm", "duration": "100.0"}, "streams": [{"codec_type": "video", "index": 0, **stream}]}


class FrameRate(unittest.TestCase):
    def parse(self, stream: dict) -> dict:
        result, ok = probe.parse_probe_data(probe_json(stream), "a.mkv", 1, run_hdr=False, timeout=1.0, hdr_runner=mock.Mock())
        self.assertTrue(ok)
        return result["video_streams"][0]

    def test_without_an_average_rate_the_frame_rate_is_unknown(self) -> None:
        video = self.parse({"width": 1920, "height": 1080, "r_frame_rate": "90000/1", "avg_frame_rate": "0/0"})
        self.assertIsNone(video["frame_rate"])

    def test_the_average_rate_is_used(self) -> None:
        video = self.parse({"width": 1920, "height": 1080, "r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001"})
        self.assertAlmostEqual(video["frame_rate"], 23.976, places=3)

    def test_unknown_values_stay_unknown_in_the_parsed_stream(self) -> None:
        video = self.parse({"codec_name": "h264"})
        self.assertEqual((video["resolution_category"], video["hdr_type"], video["bit_depth"]), ("UNKNOWN", "UNKNOWN", None))

    def test_hdr_second_pass_runs_for_unknown_type_and_refines_the_result(self) -> None:
        runner = mock.Mock(return_value=({"hdr10_plus_present": 1}, "OK"))
        result, _ = probe.parse_probe_data(probe_json({"width": 1920, "height": 1080}), "a.mkv", 1, run_hdr=True, timeout=1.0, hdr_runner=runner)
        runner.assert_called_once()
        self.assertEqual(result["video_streams"][0]["hdr_type"], "HDR")

    def test_hdr_second_pass_skipped_for_sdr(self) -> None:
        runner = mock.Mock()
        probe.parse_probe_data(probe_json({"width": 1920, "height": 1080, "color_transfer": "bt709"}), "a.mkv", 1, run_hdr=True, timeout=1.0, hdr_runner=runner)
        runner.assert_not_called()


class NamesAndVersion(unittest.TestCase):
    def test_name_and_version(self) -> None:
        self.assertEqual(constants.APP_NAME, "Media Cataloger")
        self.assertEqual(constants.APP_VERSION, "1.0.0")
        self.assertEqual(constants.DB_PATH.name, "MediaCataloger.db")
        self.assertEqual(constants.LEGACY_DB_PATH.name, "MediaCatalog.db")
        self.assertEqual(constants.MIN_PYTHON, (3, 10))

    def test_locale_files_carry_the_version(self) -> None:
        for path in sorted((ROOT / "locales").glob("*.json")):
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["_meta.version"], "1.0.0", path.name)

    def test_no_old_name_is_left_in_the_code(self) -> None:
        for path in sorted(ROOT.rglob("*.py")):
            if "__pycache__" in path.parts or path.name == "test_catalog.py":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("PROGRAM_VERSION", text, str(path))
            if path.name not in ("constants.py", "database.py"):          # these two name the old database on purpose
                self.assertNotRegex(text, r"MediaCatalog(?!er)", str(path))

    def test_every_python_file_has_the_author_header(self) -> None:
        expected = ["# Media Cataloger", "# Author: GlacialPigeon", "# GitHub: https://github.com/GlacialPigeon"]
        for path in sorted(ROOT.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[:3], expected, str(path.relative_to(ROOT)))

    def test_reports_carry_the_new_name(self) -> None:
        from modules.reports import report_excel, report_txt
        self.assertIn("MEDIA CATALOGER", Path(report_txt.__file__).read_text(encoding="utf-8"))
        self.assertIn("Media Cataloger Version", Path(report_excel.__file__).read_text(encoding="utf-8"))

    def test_the_menu_ends_with_exit_on_zero(self) -> None:
        from modules.ui import ConsoleUI
        localization.LOCALES.load_canonical()
        ui = ConsoleUI(mock.Mock(), mock.Mock(), mock.Mock(), quiet_logger(), mock.Mock(), mock.Mock(), xlsxwriter_available=False)
        out = io.StringIO()
        with mock.patch("builtins.input", return_value="0"), contextlib.redirect_stdout(out):
            ui.main_menu()
        shown = out.getvalue()
        self.assertIn("[0] Exit", shown)
        self.assertNotIn("[4]", shown)

    def test_four_is_no_longer_a_choice(self) -> None:
        from modules.ui import ConsoleUI
        localization.LOCALES.load_canonical()
        ui = ConsoleUI(mock.Mock(), mock.Mock(), mock.Mock(), quiet_logger(), mock.Mock(), mock.Mock(), xlsxwriter_available=False)
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=["4", "", "0"]), contextlib.redirect_stdout(out):
            ui.main_menu()
        self.assertIn(localization.t("common.invalid_choice"), out.getvalue())


class DatabaseRename(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.old = self.dir / "MediaCatalog.db"
        self.new = self.dir / "MediaCataloger.db"

    def make_legacy(self, rows: int = 3, keep_open: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self.old)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (n INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
        conn.commit()
        if not keep_open:
            conn.close()
        return conn

    def count(self, path: Path) -> int:
        conn = sqlite3.connect(path)
        try:
            return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            conn.close()

    def test_the_old_database_is_renamed_with_its_data(self) -> None:
        self.make_legacy(5)
        self.assertTrue(migrate_legacy_database(self.new, self.old, quiet_logger()))
        self.assertFalse(self.old.exists())
        self.assertEqual(self.count(self.new), 5)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.name.startswith("MediaCatalog.")), [])

    def test_data_still_in_the_write_ahead_log_is_not_lost(self) -> None:
        # What a program that stopped without closing the database leaves behind: the file and a -wal that was not merged yet.
        # The files are copied while the connection is still open (on Windows an open database cannot be renamed).
        crashed = self.dir / "crashed"
        crashed.mkdir()
        conn = self.make_legacy(4, keep_open=True)
        try:
            self.assertTrue((self.dir / "MediaCatalog.db-wal").exists())
            for suffix in ("", "-wal"):
                shutil.copy2(self.dir / f"MediaCatalog.db{suffix}", crashed / f"MediaCatalog.db{suffix}")
        finally:
            conn.close()
        for suffix in ("", "-wal", "-shm"):
            (self.dir / f"MediaCatalog.db{suffix}").unlink(missing_ok=True)
        new = crashed / "MediaCataloger.db"
        self.assertTrue(migrate_legacy_database(new, crashed / "MediaCatalog.db", quiet_logger()))
        self.assertEqual(self.count(new), 4)
        self.assertFalse((crashed / "MediaCatalog.db-wal").exists())

    def test_an_existing_new_database_is_never_replaced(self) -> None:
        self.make_legacy(2)
        conn = sqlite3.connect(self.new)
        conn.executescript("CREATE TABLE t (n INTEGER); INSERT INTO t VALUES (1);")
        conn.close()
        self.assertFalse(migrate_legacy_database(self.new, self.old, quiet_logger()))
        self.assertTrue(self.old.exists())
        self.assertEqual(self.count(self.new), 1)

    def test_nothing_to_do_without_an_old_database(self) -> None:
        self.assertFalse(migrate_legacy_database(self.new, self.old, quiet_logger()))
        self.assertFalse(self.new.exists())

    def test_a_failed_rename_puts_everything_back(self) -> None:
        keeper = self.make_legacy(2, keep_open=True)       # an open connection keeps the -wal / -shm files in place
        self.addCleanup(keeper.close)
        real = os.replace
        calls: list[str] = []

        def flaky(src: object, dst: object) -> None:
            calls.append(str(src))
            if len(calls) == 2:
                raise OSError("boom")
            real(src, dst)

        with mock.patch("os.replace", side_effect=flaky):
            moved = migrate_legacy_database(self.new, self.old, quiet_logger())
        self.assertFalse(moved)
        self.assertTrue(self.old.exists())
        self.assertFalse(self.new.exists())
        self.assertEqual(self.count(self.old), 2)

    def test_the_renamed_database_opens_as_a_catalog(self) -> None:
        self.old.unlink(missing_ok=True)
        db = Database(self.old, quiet_logger())
        db.open()
        db.close()
        self.assertTrue(migrate_legacy_database(self.new, self.old, quiet_logger()))
        reopened = Database(self.new, quiet_logger())
        reopened.open()
        reopened.close()
        self.assertTrue(self.new.exists())


class QuotesAndPaths(unittest.TestCase):
    def test_every_pair_of_quotes_is_removed(self) -> None:
        for raw in ('"/mnt/a b"', "'/mnt/a b'", "\u201c/mnt/a b\u201d", "\u2018/mnt/a b\u2019", '  "/mnt/a b"  ', "\"'/mnt/a b'\""):
            self.assertEqual(remove_outer_quotes(raw), "/mnt/a b", raw)

    def test_odd_input(self) -> None:
        self.assertEqual(remove_outer_quotes('"/mnt/a'), '"/mnt/a')
        self.assertEqual(remove_outer_quotes('"'), '"')
        self.assertEqual(remove_outer_quotes(None), "")

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_linux_source_must_be_a_full_path(self) -> None:
        from modules.platform_linux import LinuxPlatform
        adapter = LinuxPlatform()
        with tempfile.TemporaryDirectory() as tmp:
            descriptor = adapter.resolve_source(f"\u201c{tmp}\u201d", quiet_logger())
            self.assertEqual(os.path.realpath(tmp), descriptor.canonical_path)
            with self.assertRaises(ValueError) as caught:
                adapter.resolve_source("Movies", quiet_logger())
            self.assertEqual(str(caught.exception), "RELATIVE_SOURCE_PATH")
            with self.assertRaises(ValueError):
                adapter.resolve_source("../media", quiet_logger())

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_the_import_file_path_may_still_be_relative(self) -> None:
        from modules.platform_linux import LinuxPlatform
        resolved = LinuxPlatform().resolve_user_path('"lists/media.txt"')
        self.assertTrue(os.path.isabs(resolved))
        self.assertTrue(resolved.endswith("lists/media.txt"))

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_the_source_manager_reports_a_relative_path_with_its_own_message(self) -> None:
        from modules.platform_linux import LinuxPlatform
        from modules.sources import SourceError, SourceManager
        manager = SourceManager.__new__(SourceManager)
        manager.platform = LinuxPlatform()
        manager.logger = quiet_logger()
        manager.notice_callback = None
        with self.assertRaises(SourceError) as caught:
            manager.resolve_descriptor("Movies")
        self.assertEqual(caught.exception.key, "source.add.path_not_absolute")
        self.assertEqual(caught.exception.values, {"path": "Movies"})

    def test_windows_rejects_relative_names_and_completes_a_bare_drive(self) -> None:
        from modules import platform_windows
        adapter = platform_windows.WindowsPlatform()
        with self.assertRaises(ValueError) as caught:
            adapter.resolve_source("Movies", quiet_logger())
        self.assertEqual(str(caught.exception), "RELATIVE_SOURCE_PATH")
        seen: list[str] = []

        def stop(original: str, logger: object) -> None:
            seen.append(original)
            raise RuntimeError("stop here")

        with mock.patch.object(platform_windows, "_resolve_network_shortcut", side_effect=stop), self.assertRaises(RuntimeError):
            adapter.resolve_source("d:", quiet_logger())
        self.assertEqual(seen, ["d:\\"])

    def test_the_new_message_exists_in_every_language(self) -> None:
        for name in ("en-US", "sl-SI"):
            data = json.loads((ROOT / "locales" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertIn("{path}", data["source.add.path_not_absolute"], name)


class InstanceLock(unittest.TestCase):
    @unittest.skipUnless(LINUX, "needs Linux")
    def test_second_instance_is_refused_and_the_lock_is_reusable(self) -> None:
        from modules.platform_linux import LinuxPlatform
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmp}):
                first, second = LinuxPlatform().create_instance_lock(Path("x")), LinuxPlatform().create_instance_lock(Path("x"))
                self.assertEqual(first.path.parent, Path(tmp))
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                self.assertEqual(second.failure, "busy")
                first.release()
                self.assertTrue(second.acquire())
                second.release()

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_a_planted_symlink_is_not_followed(self) -> None:
        from modules.platform_linux import LinuxPlatform
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            victim = Path(tmp) / "victim.txt"
            victim.write_text("keep")
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmp}):
                lock = LinuxPlatform().create_instance_lock(Path("x"))
                lock.path.symlink_to(victim)
                self.assertFalse(lock.acquire())
                self.assertNotEqual(lock.failure, "busy")
                self.assertEqual(victim.read_text(), "keep")

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_an_unsafe_runtime_directory_falls_back_to_the_temp_directory(self) -> None:
        from modules.platform_linux import _LinuxInstanceLock
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmp}):
                self.assertEqual(_LinuxInstanceLock._lock_directory(os.getuid()), Path(tempfile.gettempdir()))

    def test_both_adapters_take_a_path_and_expose_failure(self) -> None:
        from modules import platform_windows
        lock = platform_windows.WindowsPlatform().create_instance_lock(Path("x"))
        self.assertIsNone(lock.failure)

    def test_protocol_names_are_the_shared_ones(self) -> None:
        for module in ("platform_api.py", "platform_linux.py", "platform_windows.py"):
            text = (ROOT / "modules" / module).read_text(encoding="utf-8")
            for name in ("create_instance_lock", "subprocess_process_options", "is_link_or_reparse_point"):
                self.assertIn(f"def {name}", text, f"{module}: {name}")
            self.assertNotIn("subprocess_creation_kwargs", text)
            self.assertNotIn("is_directory_link", text)


class AtomicWriteAndDefaults(unittest.TestCase):
    def test_atomic_write_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            config.atomic_write_text(target, "one\n")
            config.atomic_write_text(target, "two\n")
            self.assertEqual(target.read_text(), "two\n")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.txt"])

    def test_a_failed_swap_keeps_the_old_file_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            target.write_text("old")
            with mock.patch("os.replace", side_effect=OSError("boom")), self.assertRaises(OSError):
                config.atomic_write_text(target, "new")
            self.assertEqual(target.read_text(), "old")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.txt"])

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_permissions_of_the_replaced_file_are_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            target.write_text("old")
            target.chmod(0o640)
            config.atomic_write_text(target, "new")
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_default_excluded_folders_include_the_nas_ones_on_windows(self) -> None:
        from modules.platform_windows import WindowsPlatform
        names = {name.casefold() for name in WindowsPlatform().default_excluded_directories()}
        self.assertTrue({"@eadir", "#recycle", "#snapshot", "@recycle", ".@__thumb", "$recycle.bin", "system volume information"} <= names)

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_default_excluded_folders_include_the_nas_ones_on_linux(self) -> None:
        from modules.platform_linux import LinuxPlatform
        names = {name.casefold() for name in LinuxPlatform().default_excluded_directories()}
        self.assertTrue({"@eadir", "#recycle", "#snapshot", "@recycle", ".@__thumb", "$recycle.bin", "system volume information",
                         "lost+found", ".trash"} <= names)

    @unittest.skipUnless(LINUX, "needs Linux")
    def test_a_new_configuration_starts_with_those_defaults(self) -> None:
        from modules.platform_linux import LinuxPlatform
        adapter = LinuxPlatform()
        data = config.build_default_config(adapter.default_excluded_directories(), adapter.default_excluded_extensions())
        self.assertIn("@eaDir", data["scan"]["excluded_directories"])


class Localization(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = localization.LocaleManager(ROOT / "locales")
        self.assertTrue(self.manager.load_canonical(), self.manager.canonical_error)

    def test_numbers_follow_the_language(self) -> None:
        self.assertEqual(self.manager.number(10874), "10,874")
        self.assertEqual(self.manager.number(1234.5, 1), "1,234.5")
        self.assertTrue(self.manager.activate("sl-SI", log_warnings=False))
        self.assertEqual(self.manager.number(10874), "10.874")
        self.assertEqual(self.manager.number(1234.5, 1), "1.234,5")
        self.assertEqual(self.manager.number(0.5, 1), "0,5")
        self.assertTrue(self.manager.activate("en-US"))
        self.assertEqual(self.manager.number(10874), "10,874")

    def test_screens_do_not_format_numbers_by_hand(self) -> None:
        text = (ROOT / "modules" / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn(":,}", text)

    def test_plural_categories(self) -> None:
        sl = [localization.plural_category("sl-SI", n) for n in (1, 2, 3, 4, 5, 101, 102, 0)]
        self.assertEqual(sl, ["one", "two", "few", "few", "other", "one", "two", "other"])
        self.assertEqual([localization.plural_category("en-US", n) for n in (0, 1, 2)], ["other", "one", "other"])
        self.assertEqual([localization.plural_category("pl-PL", n) for n in (1, 2, 5, 12, 22)], ["one", "few", "many", "many", "few"])

    def write_locales(self, directory: Path, english: dict, other: dict | None = None) -> localization.LocaleManager:
        base = json.loads((ROOT / "locales" / "en-US.json").read_text(encoding="utf-8"))
        base.update(english)
        (directory / "en-US.json").write_text(json.dumps(base), encoding="utf-8")
        if other is not None:
            (directory / "sl-SI.json").write_text(json.dumps({"_meta.code": "sl", "_meta.locale": "sl-SI", "_meta.name": "Slovenščina",
                                                              "_meta.thousands": ".", "_meta.decimal": ",", **other}), encoding="utf-8")
        manager = localization.LocaleManager(directory)
        self.assertTrue(manager.load_canonical(), manager.canonical_error)
        return manager

    def test_plural_texts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = self.write_locales(Path(tmp), {"demo.files": {"one": "{count} file", "other": "{count} files"}},
                                         {"demo.files": {"one": "{count} datoteka", "two": "{count} datoteki", "few": "{count} datoteke", "other": "{count} datotek"}})
            self.assertEqual(manager.plural("demo.files", 1), "1 file")
            self.assertEqual(manager.plural("demo.files", 1500), "1,500 files")
            self.assertTrue(manager.activate("sl-SI", log_warnings=False))
            self.assertEqual([manager.plural("demo.files", n) for n in (1, 2, 3, 5)],
                             ["1 datoteka", "2 datoteki", "3 datoteke", "5 datotek"])
            self.assertEqual(manager.plural("demo.files", 1500), "1.500 datotek")
            with self.assertRaises(localization.LocaleError):
                manager.text("demo.files")

    def test_a_missing_plural_form_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = self.write_locales(Path(tmp), {"demo.files": {"one": "{count} file", "other": "{count} files"}},
                                         {"demo.files": {"other": "{count} datotek"}})
            manager.activate("sl-SI", log_warnings=False)
            self.assertEqual(manager.plural("demo.files", 2), "2 datotek")

    def test_a_plural_text_needs_the_form_other(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = json.loads((ROOT / "locales" / "en-US.json").read_text(encoding="utf-8"))
            base["demo.files"] = {"one": "{count} file"}
            (Path(tmp) / "en-US.json").write_text(json.dumps(base), encoding="utf-8")
            self.assertFalse(localization.LocaleManager(Path(tmp)).load_canonical())

    def test_plural_forms_must_use_the_same_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = json.loads((ROOT / "locales" / "en-US.json").read_text(encoding="utf-8"))
            base["demo.files"] = {"one": "{count} file", "other": "{number} files"}
            (Path(tmp) / "en-US.json").write_text(json.dumps(base), encoding="utf-8")
            self.assertFalse(localization.LocaleManager(Path(tmp)).load_canonical())

    def test_all_languages_have_the_same_keys_and_placeholders(self) -> None:
        english = json.loads((ROOT / "locales" / "en-US.json").read_text(encoding="utf-8"))
        slovenian = json.loads((ROOT / "locales" / "sl-SI.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(english), sorted(slovenian))
        for key, value in english.items():
            if key.startswith("_meta.") or not isinstance(value, str):
                continue
            self.assertEqual(localization._placeholder_names(value), localization._placeholder_names(slovenian[key]), key)

    def test_required_keys_exist(self) -> None:
        english = json.loads((ROOT / "locales" / "en-US.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(localization.REQUIRED_CANONICAL_KEYS - set(english)), [])

    def test_check_command(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(localization.check_command("sl-SI"), 0)
        self.assertIn("sl-SI:", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(localization.check_command("xx-XX"), 1)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
            self.assertEqual(localization.check_command("sl-SI", Path(tmp)), 2)

    def test_check_command_reports_a_wrong_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.write_locales(Path(tmp), {}, {"scan.stats.reused": "Ponovno uporabljeno: {stevilo}"})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(localization.check_command("sl-SI", Path(tmp)), 1)
            self.assertIn("scan.stats.reused", out.getvalue())

    def test_main_runs_the_check_without_starting_the_program(self) -> None:
        import main
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["main.py", "--check-language", "sl-SI"]), contextlib.redirect_stdout(out):
            self.assertEqual(main.main(), 0)


if __name__ == "__main__":
    unittest.main()
