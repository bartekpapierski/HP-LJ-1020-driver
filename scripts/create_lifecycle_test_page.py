#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Rebuild the public calibration fixture (development-only ReportLab dependency)."""

import argparse
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas


def create_page(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    page = Canvas(str(output), pagesize=(210 * mm, 297 * mm),
                  pageCompression=0, invariant=1)
    page.setTitle("HP LaserJet 1020 lifecycle calibration")
    page.setAuthor("HP-LJ-1020-driver")

    def label(x: float, y: float, text: str, size: int = 10) -> None:
        page.setFont("Helvetica", size)
        page.drawString(x * mm, y * mm, text)

    # Centers, not outer tips, are exactly 20 mm from each paper edge.
    page.setLineWidth(0.2 * mm)
    for x in (20, 190):
        for y in (20, 277):
            page.line((x - 3) * mm, y * mm, (x + 3) * mm, y * mm)
            page.line(x * mm, (y - 3) * mm, x * mm, (y + 3) * mm)
    label(30, 268, "HP LaserJet 1020 - lifecycle calibration", 14)
    label(30, 256, "A4 portrait / actual size / one page per submission")
    label(30, 248, "Four cross centers: 20 mm from their nearest paper edges.")
    label(30, 240, "Cross spans: 170 mm horizontally; 257 mm vertically.")

    label(30, 220, "100 mm ruler: measure between the two end ticks.", 11)
    page.line(40 * mm, 205 * mm, 140 * mm, 205 * mm)
    for i in range(101):
        length = 5 if i % 10 == 0 else (3 if i % 5 == 0 else 1.5)
        page.line((40 + i) * mm, 205 * mm, (40 + i) * mm, (205 + length) * mm)
        if i % 10 == 0:
            label(39 + i, 199, str(i), 8)

    label(30, 180, "Fine line checks: evenly spaced, no missing or broken lines.")
    for column, width in enumerate((0.25, 0.5, 0.75, 1.0)):
        x = 30 + column * 40
        label(x, 171, f"{width:g} mm", 9)
        page.setLineWidth(width * mm)
        for i in range(8):
            page.line(x * mm, (164 - i * 2) * mm, (x + 25) * mm, (164 - i * 2) * mm)

    label(30, 130, "Density ramp: smooth blocks, no discontinuities.")
    for i in range(10):
        page.setFillGray(1 - (i + 1) / 10)
        page.rect((30 + i * 15) * mm, 108 * mm, 15 * mm, 15 * mm, fill=1, stroke=0)
    page.setFillGray(0)
    label(30, 91, "Readable text: ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789", 9)
    label(30, 82, "Readable text: abcdefghijklmnopqrstuvwxyz 0123456789", 7)
    label(30, 64, "Scale error (%) = absolute(measured ruler length in mm - 100).", 9)
    label(30, 56, "Position error: largest absolute(edge-to-cross-center mm - 20).", 9)
    label(30, 48, "Measure both nearest edges at every cross; use maxima over all pages.", 9)
    label(30, 35, "Synthetic fixture only. No firmware, identities, or private job content.", 8)
    page.showPage()
    page.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    create_page(parser.parse_args().output)
