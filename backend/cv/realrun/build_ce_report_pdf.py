#!/usr/bin/env python3
"""Build CE_PLAYER_VIDEO1_REPORT.pdf: run numbers + both debug images.

Size-capped so the PDF stays small enough to relay as a chat attachment.
"""
import io
from pathlib import Path

from PIL import Image
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent
CE_PATH = ROOT / "CE_PLAYER_VIDEO1_CE_VIEW.jpg"
VIZ_PATH = ROOT / "CE_PLAYER_VIDEO1_VIZ.jpg"
RUN_PATH = ROOT / "CE_PLAYER_VIDEO1_RUN.md"
OUT_PATH = ROOT / "CE_PLAYER_VIDEO1_REPORT.pdf"

CE_BUDGET = 50_000
VIZ_BUDGET = 28_000


def encode_fit(path, budget, max_width):
    im = Image.open(path).convert("RGB")
    if im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    for quality in (75, 68, 62, 56, 50, 45, 40):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= budget:
            break
    return buf.getvalue()


def clean(text):
    return text.encode("latin-1", "replace").decode("latin-1")


def main():
    ce = encode_fit(CE_PATH, CE_BUDGET, 1240)
    viz = encode_fit(VIZ_PATH, VIZ_BUDGET, 1100)
    run = clean(RUN_PATH.read_text()) if RUN_PATH.exists() else ""

    pdf = FPDF(format="A4")
    pdf.set_margins(14, 14, 14)
    pdf.set_auto_page_break(True, 14)

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, "CE_Player pipeline on video1 pictures - run report",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 4.6,
                   "Repo: jekeymer/terraquest-mint, cv/realrun. Frames: video1/pictures "
                   "image0009 -> image0020 (12 frames, 3280x2464, Feb 20 2020). "
                   "Delta t = 2 minutes per frame (Informe 1). Rendered by committed CI "
                   "scripts, regenerates on every CI run.\n")
    excerpt = "\n".join(run.splitlines()[:70])
    pdf.set_font("Courier", "", 7.6)
    pdf.multi_cell(0, 3.7, excerpt)

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "CE_Player diff view: white clusters, boxes, stats block",
             new_x="LMARGIN", new_y="NEXT")
    pdf.image(io.BytesIO(ce), w=182)

    pdf.add_page()
    pdf.cell(0, 7, "Track comparison: CE_Player vs TLD ground truth",
             new_x="LMARGIN", new_y="NEXT")
    pdf.image(io.BytesIO(viz), w=182)

    pdf.output(str(OUT_PATH))
    print(f"wrote {OUT_PATH} {OUT_PATH.stat().st_size} bytes")


if __name__ == "__main__":
    main()
