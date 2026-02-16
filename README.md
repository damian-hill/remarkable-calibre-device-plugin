
# remarkable-calibre-device-plugin

A Calibre [Device Plugin](https://manual.calibre-ebook.com/plugins.html#module-calibre.devices.interface) for reMarkable tablets.

**No developer mode required.** Connect via USB, enable Settings > Storage, and go.

## Supported Devices

| Device | Screen | Status |
|--------|--------|--------|
| reMarkable 1 / 2 | 6.2" x 8.3" | Supported |
| Paper Pro | 7.1" x 9.4" | Supported |
| Paper Pro Move | 3.6" x 6.4" | Supported |

## Features

- **Upload** ePub and PDF files to your reMarkable
- **Auto-convert** EPUBs to PDF with page dimensions matched to your device model
- **Per-model PDF presets** — margins, font size, and font family tuned for each screen
- **Parallel conversion** — multiple EPUBs convert simultaneously when sending a batch
- **View** your device's book library from within Calibre
- **Cover injection** — automatically adds a cover page to EPUBs that are missing one
- **Target folder** — upload books into a specific folder on your device
- **Cross-platform** — works on macOS, Windows, Linux, and Docker (linuxserver/calibre)

### What Doesn't Work

- **Deleting books** — the USB web interface has no delete endpoint. Calibre will show a warning with the book names; delete them on your reMarkable directly.
- **Creating folders** — folders must already exist on the device. Create them on your reMarkable before configuring a target folder.

## Installation

1. Download the latest `.zip` from [Releases](https://github.com/damian-hill/remarkable-calibre-device-plugin/releases/latest)
2. In Calibre: **Preferences > Plugins > Load plugin from file**
3. Select the downloaded ZIP
4. Restart Calibre

Or from the command line:
```bash
calibre-customize -a remarkable-calibre-device-plugin.zip
```

## Setup

### 1. Create a "Calibre" folder on your reMarkable

On your reMarkable, create a folder called **Calibre** (or any name you like). This keeps your uploaded books organized and separate from notebooks.

### 2. Connect via USB

1. Plug in the USB cable
2. On your reMarkable: **Settings > Storage** — enable USB transfer
3. Open Calibre — a **Device** button appears in the toolbar

### 3. Configure the plugin

**Preferences > Plugins > Show only user installed plugins** > select the plugin > **Customize plugin**

| Setting | What it does |
|---------|-------------|
| **IP address** | Your reMarkable's IP (default: `10.11.99.1`) |
| **Device model** | Select your model — sets PDF page size to match your screen |
| **Preferred format** | **PDF** (recommended) auto-converts EPUBs; **EPUB** sends as-is |
| **Margin** | Page margin in points (model defaults: 36pt for rM2/Pro, 18pt for Move) |
| **Font size** | Default font size in points (model defaults: 18/20/14pt) |
| **Font** | Serif font family for body text (leave empty for system default) |
| **Embed all fonts** | Embed all fonts in PDF output (slower, higher fidelity). Disable for faster conversion. |
| **Target folder** | Name of an existing folder on your reMarkable (e.g., "Calibre") |
| **Inject cover** | Add a cover page to EPUBs that are missing one |

Switching device models auto-populates the PDF settings with that model's recommended values. Click **Reset to model defaults** to restore them.

### 4. Send books

Right-click a book and select **Send to device > Send to main memory**.

For batch sends, select multiple books first. EPUBs convert in parallel — sending 10 books is much faster than sending them one at a time.

## How It Works

The plugin communicates with your reMarkable over HTTP via the USB Web Interface at `http://10.11.99.1`. No SSH, no developer mode, no cloud account.

| Operation | How |
|-----------|-----|
| Device detection | `GET /documents/` — polls every 5 seconds |
| Book listing | Recursive `GET /documents/{id}` to build file tree |
| Upload | `POST /upload` with multipart file data |
| Folder targeting | `GET /documents/{folder_id}` to navigate, then `POST /upload` |
| EPUB → PDF | Shells out to `ebook-convert` with device-matched page dimensions |
| Delete | Not supported by web interface — raises a warning |

## Docker (linuxserver/calibre)

The plugin works in the [linuxserver/calibre](https://hub.docker.com/r/linuxserver/calibre) Docker image. Since it uses HTTP (not USB mass storage), you need network access to the reMarkable:

```yaml
services:
  calibre:
    image: lscr.io/linuxserver/calibre:latest
    network_mode: host  # required to reach 10.11.99.1
```

**Note:** [calibre-web](https://github.com/janeczku/calibre-web) is a web frontend for the Calibre library — it does not support device plugins.

## Troubleshooting

1. **No Device button?** — Make sure the USB web interface is accessible at http://10.11.99.1 in your browser
2. **Target folder not working?** — The folder must already exist on your reMarkable. Create it on the device first.
3. **"Cannot delete" warning?** — Expected. The USB web interface doesn't support deletion. Delete on your reMarkable directly.
4. **Connection logs** — Run `calibre-debug -g` to see detailed plugin logs
5. **Firmware issues** — Some firmware versions don't start the web interface reliably. Try reconnecting the USB cable.

## Building from Source

```bash
bash build.sh
```

Creates `remarkable-calibre-device-plugin.zip`, installs it, and restarts Calibre.

Syntax check without building:
```bash
calibre-debug -c "import py_compile; py_compile.compile('__init__.py', doraise=True); print('OK')"
```
