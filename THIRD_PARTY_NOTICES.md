# Third-party notices / 第三方许可

本项目新增代码使用 MIT 许可。以下第三方内容保留各自许可，不适用本项目 MIT 许可。
未分发 Windows 原工具、DLL、界面位图或其使用说明文档。

## Haar cascade / 人脸分类器

`src/gwy_photo_mac/data/haarcascade_frontalface_alt2.xml` 为 OpenCV 人脸分类器，
取自参考工具分发包，保留原始文件及完整许可注释。创建者 Rainer Lienhart。

```text
Tree-based 20x20 gentle adaboost frontal face detector.
    Created by Rainer Lienhart.

////////////////////////////////////////////////////////////////////////////////////////

  IMPORTANT: READ BEFORE DOWNLOADING, COPYING, INSTALLING OR USING.

  By downloading, copying, installing or using the software you agree to this license.
  If you do not agree to this license, do not download, install,
  copy or use the software.


                        Intel License Agreement
                For Open Source Computer Vision Library

 Copyright (C) 2000, Intel Corporation, all rights reserved.
 Third party copyrights are property of their respective owners.

 Redistribution and use in source and binary forms, with or without modification,
 are permitted provided that the following conditions are met:

   * Redistribution's of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

   * Redistribution's in binary form must reproduce the above copyright notice,
     this list of conditions and the following disclaimer in the documentation
     and/or other materials provided with the distribution.

   * The name of Intel Corporation may not be used to endorse or promote products
     derived from this software without specific prior written permission.

 This software is provided by the copyright holders and contributors "as is" and
 any express or implied warranties, including, but not limited to, the implied
 warranties of merchantability and fitness for a particular purpose are disclaimed.
 In no event shall the Intel Corporation or contributors be liable for any direct,
 indirect, incidental, special, exemplary, or consequential damages
 (including, but not limited to, procurement of substitute goods or services;
 loss of use, data, or profits; or business interruption) however caused
 and on any theory of liability, whether in contract, strict liability,
 or tort (including negligence or otherwise) arising in any way out of
 the use of this software, even if advised of the possibility of such damage.
```

## Runtime and build dependencies

- Python: PSF License, https://www.python.org/psf/license/
- NumPy: BSD-3-Clause and bundled component notices, https://numpy.org/doc/stable/license.html
- Pillow: HPND and bundled component notices, https://pillow.readthedocs.io/en/stable/about.html#license
- OpenCV 4.11: Apache-2.0 and third-party notices, https://github.com/opencv/opencv/blob/4.11.0/LICENSE
- opencv-python: MIT for its packaging; OpenCV/codec component licenses also apply, https://github.com/opencv/opencv-python
- PySide6 / Shiboken6 / Qt: open-source LGPL/GPL terms or a commercial license, depending on component; this project uses QtCore, QtGui and QtWidgets from the open-source wheel. See https://doc.qt.io/qtforpython-6/licenses.html and https://www.qt.io/licensing/open-source-lgpl-obligations
- PyInstaller: GPL with a bootloader exception permitting distribution of the bundled application, https://pyinstaller.org/en/stable/license.html

The macOS build script copies license and notice files from installed dependency wheels into
the application resources under `licenses/`. The original XML license is also retained in the
model file. Qt is bundled as replaceable dynamic libraries/frameworks, not statically linked.
No Qt or PySide source is modified by this project. Source and rebuild instructions are available
from the upstream links and this repository; users may replace compatible Qt/PySide libraries
and rebuild/re-sign their own application. Do not remove dependency license texts from a
redistributed application. See `scripts/build_macos.py` for the exact packaging process.
