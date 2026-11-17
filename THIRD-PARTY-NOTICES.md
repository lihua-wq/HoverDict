# Third-party components

HoverDict itself is released under the MIT license (see [LICENSE](LICENSE)).
A prebuilt release additionally bundles the following components — their
licenses apply to those parts, not to HoverDict's own source.

| Component | Version | License | Used for |
| --- | --- | --- | --- |
| [PySide6 / shiboken6](https://pypi.org/project/PySide6/) | 6.12 | **LGPL-3.0-only** (or GPL-2.0/3.0, or commercial) | Qt widgets, QtWebEngine popup |
| [Qt WebEngine](https://wiki.qt.io/QtWebEngine) (Chromium) | bundled with PySide6 | LGPL-3.0 + Chromium's BSD-style licenses | rendering dictionary entries |
| [winsdk](https://pypi.org/project/winsdk/) | 1.0.0b10 | MIT | Windows.Media.Ocr, Win32 helpers |
| [mdict-utils](https://github.com/liuyug/mdict-utils) | 1.3.14 | MIT | reading MDX/MDD files |
| [mss](https://pypi.org/project/mss/) | 10.2.0 | MIT | screen capture |
| [Pillow](https://pypi.org/project/Pillow/) | 13.0 | MIT-CMU (HPND) | converting captures to BGRA bitmaps |

## What this means if you redistribute a build

- **Qt/PySide6 is LGPL-3.0.** Shipping the prebuilt `dist\HoverDict` folder is
  fine as long as you:
  - keep Qt's license text and this notice alongside the build;
  - let users replace the Qt libraries — the one-folder build links Qt
    dynamically (`_internal\PySide6\*.dll`), so replacing those DLLs is possible
    and satisfies the relinking requirement; do **not** switch to a one-file
    build that hides them behind a self-extracting archive without also offering
    the unmodified Qt binaries;
  - state that Qt has not been modified (it hasn't).
- Qt's LGPL text: <https://www.gnu.org/licenses/lgpl-3.0.html>,
  Qt licensing overview: <https://www.qt.io/licensing/open-source-lgpl-obligations>.
- Qt WebEngine contains Chromium; its third-party notices ship with the Qt
  installation (`PySide6\translations`, `LICENSES` folder in the PySide6 wheel).
- The other dependencies are MIT/HPND: keep their copyright notices, which is
  what this file does.

## Dictionary data

No dictionary is bundled. MDX files you load stay on your machine and remain the
property of their publishers.
