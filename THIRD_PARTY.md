# Third-party notices

The yym application source is MIT licensed; see LICENSE. This portable distribution
also uses the following unmodified runtime components under their own licenses:

* Python 3.12: PSF License. The build copies the interpreter's complete LICENSE.txt.
  Source: https://www.python.org/downloads/source/
* PySide6-Essentials 6.12.0, Shiboken6 6.12.0 and the included Qt libraries:
  LGPL-3.0 (with the applicable upstream exceptions and component notices).
  Copyright The Qt Company Ltd. and other contributors.
  License texts: licenses/LGPL-3.0-only.txt and licenses/GPL-3.0-only.txt.
  Binding source: https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.12.0
  Qt source: https://download.qt.io/archive/qt/6.12/6.12.0/
* PyInstaller 6.22.3 bootloader: GPL with the PyInstaller bootloader exception.
  The complete license and exception are copied to licenses/pyinstaller.
  Source: https://github.com/pyinstaller/pyinstaller/tree/v6.22.3

Qt, PySide6 and Shiboken are provided as separate DLLs and extension modules in
`_internal/PySide6` and `_internal/shiboken6`. Interface-compatible modified builds
can replace those files; no integrity check prevents their replacement. The yym
source and build instructions are provided in the source distribution. This
application imposes no restriction on debugging changes to these libraries.

Files named LicenseRef-Qt-Commercial.txt copied from upstream wheels describe an
alternative upstream license option; yym does not claim to grant a Qt commercial
license. Refer to the LGPL texts supplied here for the open-source distribution.
