"""Optional numeric differential test against one hash-identified PE32 sample.

Requires pefile + unicorn. The EXE is not launched; only documented, bounded numeric
fragments run in mapped x86 memory. No Windows APIs or original DLLs are loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import struct
from pathlib import Path

from gwy_photo_mac.core import REFERENCE_SHA256, PhotoError, Settings, calculate_crop, classify_hsi


def main():
    import pefile
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
    from unicorn.x86_const import (
        UC_X86_REG_EAX,
        UC_X86_REG_EBX,
        UC_X86_REG_ECX,
        UC_X86_REG_EDX,
        UC_X86_REG_ESI,
        UC_X86_REG_ESP,
        UC_X86_REG_FPCW,
        UC_X86_REG_FPSW,
        UC_X86_REG_FPTAG,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--cases", type=int, default=1000)
    args = parser.parse_args()
    content = args.exe.read_bytes()
    if hashlib.sha256(content).hexdigest() != REFERENCE_SHA256:
        raise SystemExit("Unknown reference SHA-256. Refusing to execute unreviewed instructions.")
    if not 1 <= args.cases <= 100000:
        raise SystemExit("--cases must be between 1 and 100000")
    pe = pefile.PE(data=content)
    emulator = Uc(UC_ARCH_X86, UC_MODE_32)
    emulator.mem_map(0x400000, 0xA00000)
    emulator.mem_write(0x400000, pe.get_memory_mapped_image())
    emulator.mem_map(0x2000000, 0x40000)
    stack, image, scratch, stop = 0x2010000, 0x2020000, 0x2030000, 0x2031000
    # _ftol replacement: save CW, select truncation, FISTP int64, restore CW, EDX:EAX.
    ftol = bytes.fromhex("83ec08d93c24668b0424660d000c6689442402d96c2402df3d")
    ftol += struct.pack("<I", scratch)
    ftol += bytes.fromhex("d92c2483c408a1") + struct.pack("<I", scratch)
    ftol += bytes.fromhex("8b15") + struct.pack("<I", scratch + 4) + b"\xc3"
    emulator.mem_write(0x441442, ftol)
    stopped = []

    def hook(uc, address, size, user_data):
        if address in (0x401BB6, 0x401C3F, 0x401C41):
            stopped.append(address)
            uc.emu_stop()

    emulator.hook_add(UC_HOOK_CODE, hook)

    def reset():
        emulator.reg_write(UC_X86_REG_ESP, stack)
        emulator.reg_write(UC_X86_REG_FPCW, 0x37F)
        emulator.reg_write(UC_X86_REG_FPSW, 0)
        emulator.reg_write(UC_X86_REG_FPTAG, 0xFFFF)
        stopped.clear()

    rng = random.Random(20241018)
    cfg = Settings.load()
    cases = [
        (h, s, i)
        for h in (0, 2.5, 4.5, 6.28318)
        for s in (0.049999, 0.05, 0.050001, 0.099999, 0.1, 0.100001)
        for i in (0.099999, 0.1, 0.100001, 0.699999, 0.7, 0.700001)
    ]
    cases += [(rng.random() * 6.28318, rng.random(), rng.random()) for _ in range(args.cases)]
    categories = {0: "white", 1: "blue", 3: "invalid"}
    for h, s, i in cases:
        reset()
        params = [
            h,
            s,
            i,
            cfg.blue_h_min,
            cfg.blue_h_max,
            cfg.red_h_min,
            cfg.red_h_max,
            cfg.i_min,
            cfg.i_max,
            cfg.s_min,
            cfg.s_max,
        ]
        emulator.mem_write(stack, struct.pack("<I11d", stop, *params))
        emulator.emu_start(0x401000, stop, count=1000)
        observed = categories[emulator.reg_read(UC_X86_REG_EAX)]
        expected = classify_hsi(h, s, i, cfg)
        if observed != expected:
            raise AssertionError((h, s, i, observed, expected))

    geometry_cases = [((180, 270, 660, 660), (1000, 1400))]
    for _ in range(args.cases):
        w, h = rng.randint(295, 2200), rng.randint(413, 3000)
        fw = rng.randint(30, min(w, h))
        fh = min(fw + rng.randint(-15, 15), h)
        face = (rng.randint(0, w - fw), rng.randint(0, h - fh), fw, fh)
        geometry_cases.append((face, (w, h)))
    for face, size in geometry_cases:
        reset()
        x, y, fw, fh = face
        w, h = size
        emulator.mem_write(stack, b"\0" * 256)

        def integer(offset, value):
            emulator.mem_write(stack + offset, struct.pack("<i", value))

        def double(offset, value):
            emulator.mem_write(stack + offset, struct.pack("<d", value))

        for offset, value in (
            (0x14, h),
            (0x1C, w),
            (0x20, image),
            (0x3C, x),
            (0x40, y),
            (0x44, fw),
            (0x48, fh),
            (0x50, cfg.dst_width),
            (0x58, cfg.dst_height),
        ):
            integer(offset, value)
        for offset, value in (
            (0x7C, cfg.ratio_x_min),
            (0x8C, cfg.ratio_x_max),
            (0xA4, cfg.ratio_y_min),
            (0xAC, cfg.ratio_y_max),
        ):
            double(offset, value)
        emulator.mem_write(image + 0x28, struct.pack("<i", w))
        emulator.emu_start(0x40196A, stop, count=10000)
        if not stopped:
            raise AssertionError("Reference did not reach an expected stop address")
        try:
            expected_geometry = calculate_crop(face, size, cfg)
        except PhotoError:
            if stopped[-1] == 0x401BB6:
                raise AssertionError(("Python rejected, EXE accepted", face, size)) from None
            continue
        if stopped[-1] != 0x401BB6:
            raise AssertionError(("Python accepted, EXE rejected", face, size))
        observed_crop = tuple(
            emulator.reg_read(reg)
            for reg in (UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ECX, UC_X86_REG_EBX)
        )
        if observed_crop != expected_geometry.crop:
            raise AssertionError((face, size, observed_crop, expected_geometry.crop))
    print(
        f"PASS: {len(cases)} HSI classifications and {len(geometry_cases)} crop/proportion cases."
    )
    print("This checks numeric fragments, not full Windows behavior or website acceptance.")


if __name__ == "__main__":
    main()
