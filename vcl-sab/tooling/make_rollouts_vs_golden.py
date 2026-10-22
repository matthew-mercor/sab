#!/usr/bin/env python3
"""Build the golden-vs-rollouts comparison sheet (results/.../rollouts_vs_golden.png).

Layout follows the supplied example: one continuous white sheet; a small left-aligned
heading ABOVE each six-view row (no left label column, no centred title, no view-number
header strip, no table rules); six equally sized tiles per row in a fixed camera order;
and a compact three-panel top-down section beneath with its own left-aligned heading.
Tiles are only ever resized whole — never cropped or zoomed — so every camera's framing,
aspect ratio, and object positions are preserved exactly.

White backgrounds: the per-view renders are RGBA (tooling/blender/render_views.py requests
film_transparent=True). load_tile() alpha-composites each tile onto white BEFORE converting
to RGB and resizing; dropping alpha directly would expose the black RGB values stored under
transparent pixels. Black pixels are never threshold-replaced — black furniture is real.

Row headings read the exact reward from each rollout folder's score.json (never typed in
by hand): pass the score.json path as the third field of --row and the heading becomes
"<scene> — <label> (reward <score.json reward, 3 dp>)".

Inputs: the task's six reference renders (golden row) and, for each rollout, the six
per-view model renders produced by tooling/report.py (files model_view0..5.png).
report.py can be pointed at each packaged rollout folder (they contain score.json and
agent_scene.glb), e.g.:

    python tooling/report.py results/kimi-k3/recon-designer-bedroom-4item/rollout1 \
        --task tasks/recon-designer-bedroom-4item --out /tmp/views/rollout1 --model kimi-k3

Usage:

    python tooling/make_rollouts_vs_golden.py \
        --task tasks/recon-designer-bedroom-4item \
        --scene-name "Designer bedroom" \
        --row "KIMI K3 ROLLOUT 1:/tmp/views/rollout1:results/kimi-k3/recon-designer-bedroom-4item/rollout1/score.json" \
        --row "KIMI K3 ROLLOUT 2:/tmp/views/rollout2:results/kimi-k3/recon-designer-bedroom-4item/rollout2/score.json" \
        --row "KIMI K3 ROLLOUT 3:/tmp/views/rollout3:results/kimi-k3/recon-designer-bedroom-4item/rollout3/score.json" \
        -o results/kimi-k3/recon-designer-bedroom-4item/rollouts_vs_golden.png

With the scorer-aligned top-down section appended below the view rows (build it first with
tooling/make_topdown_comparison.py, without --title there — the sheet draws the heading):

    python tooling/make_rollouts_vs_golden.py --task tasks/recon-designer-bedroom-4item \
        --scene-name "Designer bedroom" \
        --row "KIMI K3 ROLLOUT 1:<views1>:<score1>" --row "KIMI K3 ROLLOUT 2:<views2>:<score2>" \
        --row "KIMI K3 ROLLOUT 3:<views3>:<score3>" \
        --topdown /tmp/topdown_compact.png \
        -o results/kimi-k3/recon-designer-bedroom-4item/rollouts_vs_golden.png
"""
import argparse
import glob
import json
import os

from PIL import Image, ImageDraw, ImageFont

T = 384            # tile edge (source renders are 768x768)
GAP = 8            # gap between tiles within a row
MARGIN = 24        # outer page margin
HEAD_H = 40        # heading band height above each row / the top-down section
ROW_GAP = 26       # vertical gap between the bottom of a row and the next heading
SEC_GAP = 30       # extra gap before the top-down section
BOTTOM = 24        # bottom margin

INK = (30, 38, 54)  # understated dark slate for headings


def _font(size):
    """DejaVu Sans (bundled with matplotlib, already a tooling dependency)."""
    try:
        import matplotlib
        p = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans.ttf")
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    except Exception:
        pass
    for p in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load_tile(path):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(white, im)
    im = im.convert("RGB")
    if im.size != (T, T):
        im = im.resize((T, T), Image.LANCZOS)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="task dir (for environment/input/render_*.png)")
    ap.add_argument("--scene-name", default="Scene",
                    help="display name used in every heading, e.g. 'Designer bedroom'")
    ap.add_argument("--row", action="append", required=True,
                    help="'label:dir[:score.json]' — dir holds model_view0..5.png; the optional "
                         "score.json appends ' (reward X.XXX)' read from the file; repeatable")
    ap.add_argument("--row-note", action="append", default=[],
                    help="'N:text' — draw text in small subdued red after the heading of the "
                         "N-th --row (1-based), e.g. a display-image disclaimer; repeatable")
    ap.add_argument("--golden-heading", default=None,
                    help="heading for the first row "
                         "(default: '<scene> — GOLDEN REFERENCE (source answer key)')")
    ap.add_argument("--topdown", default=None,
                    help="optional topdown_comparison.png to append below the view rows")
    ap.add_argument("--topdown-heading", default=None,
                    help="heading above the top-down section (default: '<scene> — TOP-DOWN as "
                         "the scorer sees each rollout (after aligning the whole room)')")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    golden_heading = a.golden_heading or f"{a.scene_name} — GOLDEN REFERENCE (source answer key)"
    td_heading = a.topdown_heading or (
        f"{a.scene_name} — TOP-DOWN as the scorer sees each rollout "
        "(after aligning the whole room)")

    notes = {}
    for spec in a.row_note:
        n, text = spec.split(":", 1)
        notes[int(n)] = text.strip()

    rows = [(golden_heading, None, os.path.join(a.task, "environment", "input"), "render_%04d.png")]
    for i, spec in enumerate(a.row, start=1):
        parts = spec.split(":")
        if len(parts) == 2:
            label, d = parts
        elif len(parts) == 3:
            label, d, score_path = parts
            sj = json.load(open(score_path))
            label = f"{label} (reward {sj['reward']:.3f}"
            tf = (sj.get("diagnostics") or {}).get("task_frame_f@5%")
            label += f" · secondary scorer {tf:.3f})" if tf is not None else ")"
        else:
            raise SystemExit(f"bad --row spec (expected 'label:dir[:score.json]'): {spec!r}")
        rows.append((f"{a.scene_name} — {label}", notes.get(i), d, "model_view%d.png"))

    n_cols = len(glob.glob(os.path.join(a.task, "environment", "input", "render_*.png")))  # 6 or 11 views
    content_w = n_cols * T + (n_cols - 1) * GAP
    W = content_w + 2 * MARGIN
    H = MARGIN + len(rows) * (HEAD_H + T) + (len(rows) - 1) * ROW_GAP
    td = None
    if a.topdown:
        td = Image.open(a.topdown)
        if "A" in td.getbands():
            td = td.convert("RGBA")
            white = Image.new("RGBA", td.size, (255, 255, 255, 255))
            td = Image.alpha_composite(white, td)
        td = td.convert("RGB")
        td_h = int(td.height * content_w / td.width)
        td = td.resize((content_w, td_h), Image.LANCZOS)
        H += SEC_GAP + HEAD_H + td_h
    H += BOTTOM
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    head_font = _font(26)
    note_font = _font(20)
    NOTE_INK = (158, 41, 41)  # subdued red, matching the top-down transform lines

    y = MARGIN
    for heading, note, ddir, pat in rows:
        ty = y + (HEAD_H - 26) / 2
        d.text((MARGIN, ty), heading, fill=INK, font=head_font)
        if note:
            nx = MARGIN + d.textlength(heading, font=head_font) + 18
            d.text((nx, ty + 3), note, fill=NOTE_INK, font=note_font)
        y += HEAD_H
        x = MARGIN
        for c in range(n_cols):
            sheet.paste(load_tile(os.path.join(ddir, pat % c)), (x, y))
            x += T + GAP
        y += T + ROW_GAP
    if td is not None:
        y += SEC_GAP - ROW_GAP
        d.text((MARGIN, y + (HEAD_H - 26) / 2), td_heading, fill=INK, font=head_font)
        y += HEAD_H
        sheet.paste(td, (MARGIN, y))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out)
    print(f"wrote {a.out} ({W}x{H}, {len(rows)} rows x {n_cols} views"
          f"{', top-down section appended' if td is not None else ''})")


if __name__ == "__main__":
    main()
