# Media Cataloger: technical reference

The short introduction and the setup are in the [README](README.md). This file holds the details: sources, scan modes, how media is classified, reports, settings, languages, logs and the project layout.

> Version `1.0.0`.

## Media sources

You can scan several sources into one catalog (Configuration > Paths: Add Source, Remove Source, Import Sources from File, Export Sources to File). Sources are normalized so equivalent paths are cataloged once. When you add or import a source the program detects duplicates, equivalent aliases, overlapping sources, sources already covered by a broader one and unavailable sources. A configured source that is temporarily unavailable is kept, not silently removed.

Sources must be **absolute** paths (or `~/...` on Linux). A relative path is refused with a message, because it would mean a different folder depending on where the program was started. Surrounding quotes (also typographic ones) are removed from what you type. On Windows a bare `D:` becomes `D:\`.

An import file is UTF-8 text with one source per line; imported sources go through the same checks as typed ones. Exports are written to `pathlists/`.

### Windows

* Local drives and folders, UNC paths, mapped network drives and Windows Network Shortcuts (`.lnk`).
* Mapped drives, UNC paths and shortcuts that lead to the same share resolve to one canonical network source, so aliases are never cataloged as separate libraries.

### Linux

* Local folders, mounted filesystems, CIFS and NFS shares, symbolic links, `~` paths.
* Paths follow POSIX rules and are case-sensitive; redundant separators and trailing slashes are normalized.
* Symbolic links are resolved to their real target, so a source is not cataloged twice through a link and its target.
* Local filesystems are identified by a stable storage identity where one exists, so a changed device name does not look like a new storage. CIFS and NFS sources are identified by server and share (IPv6 aware), not by where they are mounted, so several mount points of one share are one storage. Bind mounts are followed to the real directory. systemd automounts are triggered when the source is read.

### Folders that are never scanned

Recycle bins, trash and system folders are skipped by default: `$RECYCLE.BIN`, `System Volume Information`, `lost+found`, `.Trash`, `.Trash-<uid>`, and the folders of NAS boxes: `@eaDir`, `#recycle`, `#snapshot`, `@Recycle`, `.@__thumb`.

## Scanning

Before a scan the program checks that the configured sources and FFprobe are available. Unavailable sources are shown in this check and skipped.

* **Normal Scan**: media that has not changed (same size and modification time) reuses its stored metadata; new and changed media is analyzed with FFprobe. Files earlier found to be non-video are reused from the cache too. A failed probe is not stored as success, so it is tried again on the next scan.
* **Force Reprobe**: runs FFprobe again on the media candidates, for all sources or for a single one. Useful after changing FFmpeg, to rebuild metadata or to troubleshoot.

At the end the statistics show: files seen, media candidates, reused entries, cached non-video entries, probed files, successful and failed probes, non-video results, and new, changed and missing entries.

A source that goes offline is never treated as a library where every file vanished; this protects against false mass-missing results from disconnected disks, unavailable shares, mount failures and permission problems.

Ctrl+C once asks for a graceful stop; a second Ctrl+C forces an emergency exit.

### What is read from each file

FFprobe is asked for the format and all streams: video, audio and subtitles, codecs, resolution, frame rate, bit depth, HDR, languages, duration, bitrate and other stream data.

**Unknown stays unknown.** A value FFprobe does not report is stored as unknown and shown as such; it is never replaced by a guess.

* **Resolution category**: SD, 720p, 1080p, 1440p, 4K, 8K, decided from both sides of the picture so a cropped widescreen file gets the class of its width. A missing or zero size gives `UNKNOWN`.
* **Frame rate**: the average frame rate FFprobe reports. There is no fallback to the nominal rate.
* **Bit depth**: the explicit stream value, or the depth of the pixel format when there is none (`yuv420p10le` is 10, `nv12` is 8). If the explicit value is larger than the pixel format allows, the depth is unknown.
* **HDR type**: `HDR10 / PQ` for the PQ transfer, `HLG`, `SDR` for known SDR transfers, and `UNKNOWN` for everything else, including BT.2020 colours without a transfer function. Dolby Vision or HDR10+ side data turns `UNKNOWN` / `SDR` into `HDR`; mastering display luminance or MaxCLL turns `HDR10 / PQ` into `HDR10`. Streams that might be HDR get a second FFprobe pass for the frame side data.

Rows stored by an earlier version keep their old labels until the file is probed again (Force Reprobe).

## Reports

Excel (`.xlsx`), JSON and TXT, or all in one go. Scopes: *All Sources - Combined*, *All Sources - Separate Files* and *Select Source*.

Reports are saved under `reports/`, grouped by date and by report operation:

```
reports/
└── 2026-10-07/
    └── 065122_All_Combined/
        ├── MediaCataloger_All.xlsx
        ├── MediaCataloger_All.json
        └── MediaCataloger_All.txt
```

Excel needs XlsxWriter; without it JSON and TXT reports still work. Reports are always written in English with `,` as the thousands separator, whatever language the screen uses.

## Settings

* **Language** (Configuration > Language): `en-US` English and `sl-SI` Slovenščina are included. English is the fallback.
* **FFprobe settings**: workers (default 8, range 1 to 32), timeout (default 30 s per attempt) and retries (default 1, so a failing probe is tried at most twice).
* **Logging level** in `data/config.json`, `"logging": {"level": "..."}`:
  * `error_only`: warnings, failures and essential session info.
  * `normal` (default): regular activity, enough to review scans, reports and source handling.
  * `full`: detailed diagnostics for source resolution, scanning, FFprobe failures and path handling.
  * `full_with_excluded_file`: `full`, plus a separate file listing the files excluded by extension.

The main menu has `[1] Scan Media`, `[2] Generate Reports`, `[3] Configuration` and `[0] Exit`.

## Languages

The texts on screen come from the files in `locales/`. `en-US.json` is canonical and holds every text. Reports, logs and saved files are always English.

To add a language, copy `en-US.json` to a new file (for example `de-DE.json`), set `_meta.code`, `_meta.locale` and `_meta.name`, and translate the values, not the keys. The file does not have to be complete: a missing or empty entry is shown in English, and an entry that does not fit (a changed `{placeholder}`, text where a plural form belongs) is ignored alone. Keep the `{placeholders}` exactly as they are. Texts with a number have plural forms (`one`, `two`, `few`, `many`, `other`; `other` is required). `_meta.thousands` and `_meta.decimal` set the number format of the screen. Then run

```
python main.py --check-language de-DE
```

to see what is missing or wrong. The new language then appears in Configuration > Language.

## Saved files and the old name

Everything is saved next to `main.py`; nothing is written elsewhere.

```
data/MediaCataloger.db    the catalog (SQLite)
data/config.json          settings and sources
data/backups/             backups
reports/                  generated reports
pathlists/                exported source lists
logs/                     session logs
```

The tool used to be called MediaCatalog and stored its catalog in `data/MediaCatalog.db`. On the first start, when the new database does not exist and the old one does, the old database is checkpointed and renamed together with its `-wal` and `-shm` files; if anything fails the rename is rolled back and the old database stays as it was.

Writes of the configuration are atomic: a temporary file in the same folder, `fsync`, `os.replace`, then an `fsync` of the folder. Only one instance can run at a time (a lock file on Linux, a global mutex on Windows).

## Platform design

All operating system specific code is in two adapters. `main.py` chooses one.

```
modules/platform_api.py       the contract and thin module-level functions
modules/platform_windows.py   Windows adapter
modules/platform_linux.py     Linux adapter
```

The three tools (Media Cataloger, Media Diversity Sampler, Media Trickplay Generator) use the same names for what they share: `create_instance_lock(path)`, `subprocess_process_options()` and `is_link_or_reparse_point(path)`.

## Project layout

```
main.py                  entry point; chooses the platform adapter; --check-language
modules/
  application.py         startup, instance lock, database migration
  ui.py                  console menus
  sources.py             source add, import, normalization
  scan.py probe.py       scanning and FFprobe analysis
  database.py            SQLite catalog
  reports/               Excel, JSON and TXT reports
  config.py              configuration, atomic writes
  localization.py        languages, plural forms, number format
  logger.py datetime_helpers.py constants.py
  platform_api.py platform_windows.py platform_linux.py
locales/                 en-US.json (canonical), sl-SI.json
tests/                   unittest suite
```

## Troubleshooting

* **CIFS or NFS source unavailable (Linux)**: check that the share is mounted and readable outside the program, for example `ls /mnt/media`. With systemd automount, reading the path triggers the mount.
* **Permission denied**: the user running the program must be able to read and traverse the whole source. An inaccessible source is treated as unavailable, never as "all media missing".

## Tests

```
python3 -m unittest discover -s tests -v
```

Fast and independent of FFmpeg. They cover the detection rules, names and versions, the database rename, source paths, locks, atomic writes and localization.

## License

See [LICENSE](LICENSE).
