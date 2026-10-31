"""Command-line interface. Reports omit filenames and absolute paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import COMPATIBILITY_NOTICE, PhotoError, Settings, process_photo, write_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="国考照片处理工具 macOS 版（非官方复现）", epilog=COMPATIBILITY_NOTICE
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    process = commands.add_parser("process", help="检查照片并生成带参考文件尾标记的JPEG")
    process.add_argument("source", type=Path)
    process.add_argument("-o", "--output", type=Path, required=True)
    process.add_argument("--config", type=Path, help="读取PhotoInfo配置；缺失项使用EXE内置默认值")
    process.add_argument(
        "--allow-png", action="store_true", help="额外接受不透明PNG（原版默认只接受JPEG）"
    )
    process.add_argument(
        "--overwrite", action="store_true", help="允许覆盖目标文件；仍禁止覆盖源照片"
    )
    process.add_argument(
        "--json", action="store_true", help="向标准输出写入处理报告，不包含个人路径"
    )
    args = parser.parse_args(argv)
    try:
        result = process_photo(args.source, Settings.load(args.config), allow_png=args.allow_png)
        write_output(result, args.output, overwrite=args.overwrite, source=args.source)
    except PhotoError as exc:
        if args.json:
            print(
                json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, ensure_ascii=False)
            )
        else:
            print(f"处理失败：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"ok": True, **result.report}, ensure_ascii=False, indent=2))
    else:
        width, height = result.report["output_dimensions"]
        print(f"已保存：{width}×{height} 像素，{len(result.jpeg) / 1024:.2f} KiB。")
        print(COMPATIBILITY_NOTICE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
