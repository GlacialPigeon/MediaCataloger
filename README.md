# Media Cataloger

**Know what is in your media library, without opening a single file.**

Media Cataloger scans your local and network media folders, analyzes every video with FFprobe, keeps a catalog on your own machine and writes **Excel, JSON and TXT reports**: codecs, resolution, HDR, audio, subtitles, languages, duration, bitrate and more. It is built for large libraries and needs no cloud service.

## What it does

* **Scans several sources at once**: local disks, mounted shares, and on Windows UNC paths, mapped drives and shortcuts.
* **Incremental scan**: files that have not changed are not analyzed again. *Force Reprobe* analyzes them again when you want it.
* **Recognizes the same place under different names.** `Z:\Movies` and `\\server\share\Movies` (Windows), or two mount points of one share (Linux), are one source, not two.
* **Protects the catalog from offline sources.** A disk or share that is not available is skipped, not treated as "every file was deleted".
* **Never invents values.** What FFprobe does not report is shown as unknown, not guessed.
* **Reports** as Excel, JSON and TXT, for all sources together, in separate files, or for one source.
* English and Slovenian interface; more languages can be added.

Your media files are only read, never changed.

## What you need

| | |
|---|---|
| Python | 3.10 or newer |
| FFprobe | Windows: `ffmpeg\bin\ffprobe.exe` next to `main.py`. Linux: the system FFmpeg, or `ffmpeg/bin/ffprobe` next to `main.py` |
| XlsxWriter | only for Excel reports: `python -m pip install XlsxWriter`. JSON and TXT reports work without it |

The program does not download FFmpeg.

## Install on Windows

1. Install Python from <https://www.python.org/downloads/>. Tick **Add python.exe to PATH** in the installer.
2. Download this project (green **Code** button, **Download ZIP**) and unpack it to a folder you plan to keep, for example `C:\MediaCataloger`.
3. Download an FFmpeg build from <https://www.gyan.dev/ffmpeg/builds/> and unpack it so that you get:
   ```
   MediaCataloger\
       main.py
       ffmpeg\
           bin\
               ffprobe.exe
   ```
   On Windows FFprobe is only taken from this folder, never from `PATH`.
4. For Excel reports run `python -m pip install XlsxWriter`.
5. Start it:
   ```
   py -3 main.py
   ```

## Install on Linux

1. Get the project:
   ```
   git clone https://github.com/GlacialPigeon/MediaCataloger.git
   cd MediaCataloger
   ```
2. Install Python, FFmpeg and XlsxWriter (XlsxWriter is only needed for Excel reports). Choose one of the two ways.

   **Packages from your distribution** (simplest):
   ```
   sudo apt install python3 ffmpeg python3-xlsxwriter        # Debian, Ubuntu
   sudo dnf install python3 ffmpeg-free python3-XlsxWriter   # Fedora
   ```
   Start it with:
   ```
   python3 main.py
   ```

   **Virtual environment** (keeps XlsxWriter out of the system):
   ```
   sudo apt install python3 python3-venv ffmpeg              # Debian, Ubuntu
   python3 -m venv .venv
   .venv/bin/pip install XlsxWriter
   ```
   Start it with:
   ```
   .venv/bin/python main.py
   ```

**Your own FFmpeg build (optional).** The system FFmpeg is enough. If you want a specific build instead, download a static one into the `ffmpeg/bin` folder next to `main.py`; `ffprobe` there is used before the system one. The same commands work on Debian, Ubuntu and Fedora (use `arm64` instead of `amd64` on a 64-bit ARM machine such as a Raspberry Pi):
```
sudo apt install curl xz-utils        # Debian, Ubuntu
sudo dnf install curl xz              # Fedora
cd MediaCataloger
mkdir -p ffmpeg/bin
curl -L -o ffmpeg.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar -xf ffmpeg.tar.xz --strip-components=1 -C ffmpeg/bin --wildcards '*/ffmpeg' '*/ffprobe'
rm ffmpeg.tar.xz
ffmpeg/bin/ffprobe -version
```

## First run

1. **Configuration > Paths > Add Source**: add the folders that hold your media. You can also import a list from a text file.
2. **Scan Media > Start Scan**: the first scan analyzes everything and takes a while; later scans only look at what changed.
3. **Generate Reports**: choose the format (Excel, JSON, TXT or all) and the scope. Reports land in `reports/`, grouped by date.

Press Ctrl+C once during a scan to stop gracefully.

## More

All the details (sources, scan modes, reports, settings, languages, logs, project layout) are in the [technical reference](technical.md).

### More tools

Three separate tools that work well together:

* Media Cataloger: this tool.
* [Media Diversity Sampler](https://github.com/GlacialPigeon/MediaDiversitySampler): picks a small, varied sample of your library, for example for testing.
* [Media Trickplay Generator](https://github.com/GlacialPigeon/MediaTrickplayGenerator): makes the seek-bar preview pictures for Jellyfin on your stronger PC.

## License

See [LICENSE](LICENSE).
