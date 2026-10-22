#!/usr/bin/env python3
"""Answer key next to every rollout: 6 views per row (answer key = the task's reference images; each
rollout = the OUTPUT row of its input_vs_output.png), plus each rollout's top-down view after the
verifier's whole-room alignment.

  python tooling/compare_rollouts.py tasks/<task> results/<model>/<task> <title> [--rollouts rollout1 rollout2 rollout3] [--label "KIMI K3"]
"""
import argparse, glob, os, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "tooling", "scorer"))
import metrics as M  # noqa
PALETTE = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 170, 170),
           (240, 50, 230), (160, 120, 40), (0, 0, 128), (128, 128, 0), (100, 100, 100), (170, 110, 195)]
W = 300


def flat(im):
    im = im.convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


def output_row(ivo, n):
    im = Image.open(ivo).convert("RGB")
    cell = (im.width - 10 * (n + 1)) // n           # report.py: W*n + 10*(n+1) wide, 2*(W+36)+10 tall
    y0 = cell + 2 * 36 + 10
    return [im.crop((10 + i * (cell + 10), y0, 10 + i * (cell + 10) + cell, y0 + cell)).resize((W, W)) for i in range(n)]


def aligned(P, Q):
    rng = np.random.default_rng(0); sample = 4000
    Ps = P[rng.choice(len(P), sample, False)] if len(P) > sample else P
    Pa, _ = M.icp_sim3(Ps, Q, sample=sample, rng=rng)
    s, R, t = M.umeyama_sim3(Ps, Pa)
    yaw = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    tilt = np.degrees(np.arccos(np.clip(R[2, 2], -1, 1)))
    return (s * (R @ P.T)).T + t, s, yaw, tilt


def topdown(Q, parts, PA, lab, lo, hi, S, title, sub):
    Wd, H = int((hi[0] - lo[0]) * S), int((hi[1] - lo[1]) * S)
    im = Image.new("RGB", (Wd, H + 56), "white"); d = ImageDraw.Draw(im)
    d.text((6, 4), title, fill="black"); d.text((6, 18), sub, fill=(180, 30, 30))
    d.text((6, 32), "faint = answer-key item, bold = model's version (same colour)", fill=(90, 90, 90))
    px = lambda p: (int((p[0] - lo[0]) * S), int(56 + (hi[1] - p[1]) * S))
    for gx in range(int(np.ceil(lo[0])), int(hi[0]) + 1):
        d.line([px((gx, lo[1])), px((gx, hi[1]))], fill=(235, 235, 235))
    for gy in range(int(np.ceil(lo[1])), int(hi[1]) + 1):
        d.line([px((lo[0], gy)), px((hi[0], gy))], fill=(235, 235, 235))
    rng = np.random.default_rng(1)
    for i, (name, g) in enumerate(parts):
        c = PALETTE[i % len(PALETTE)]; faint = tuple(int(255 - (255 - v) * 0.3) for v in c)
        for p in g[rng.choice(len(g), min(len(g), 3000), False)]:
            d.point(px(p), fill=faint)
        a, b = g.min(0), g.max(0); d.rectangle([px((a[0], b[1])), px((b[0], a[1]))], outline=faint)
        d.text(px((a[0], b[1])), name, fill=c)
    if PA is not None:
        for i in range(len(parts)):
            pp = PA[lab == i]
            if len(pp):
                for p in pp[rng.choice(len(pp), min(len(pp), 4000), False)]:
                    d.point(px(p), fill=PALETTE[i % len(PALETTE)])
    return im


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("task"); ap.add_argument("results"); ap.add_argument("title")
    ap.add_argument("--rollouts", nargs="+", default=["rollout1", "rollout2", "rollout3"])
    ap.add_argument("--label", default="KIMI K3"); ap.add_argument("--out")
    a = ap.parse_args()
    refs = sorted(glob.glob(os.path.join(a.task, "environment", "input", "render_*.png")))
    n = len(refs)
    Q, parts = M.load_gt_furniture(os.path.join(a.task, "tests", "golden"))
    rows, tds = [], []
    lo, hi = Q.min(0) - 0.4, Q.max(0) + 0.4
    rows.append((f"{a.title} - ANSWER KEY (the reference images)", [flat(Image.open(r)).resize((W, W)) for r in refs]))
    import json
    Qp = [g for _, g in parts]; owner = np.concatenate([np.full(len(g), i) for i, g in enumerate(Qp)])
    tree = cKDTree(np.vstack(Qp))
    for r in a.rollouts:
        rd = os.path.join(a.results, r)
        rew = json.load(open(os.path.join(rd, "score.json")))["reward"]
        rows.append((f"{a.title} - {a.label} {r.upper()}  (reward {rew:.3f})", output_row(os.path.join(rd, "input_vs_output.png"), n)))
        P = M.sample_scene_glb(os.path.join(rd, "agent_scene.glb"))
        PA, s, yaw, tilt = aligned(P, Q)
        _, nn = tree.query(PA); lab = owner[nn]
        tds.append((r, rew, PA, lab, s, yaw, tilt))
    cw = n * (W + 10) + 10
    S = min(90, int((cw / len(tds) - 20) / (hi[0] - lo[0]))) if tds else 90
    td_imgs = [topdown(Q, parts, PA, lab, lo, hi, S, f"{r} (reward {rew:.3f}) - after alignment",
                       f"scorer turned the room {yaw:+.0f} deg, tilted {tilt:.0f} deg, scaled x{s:.2f}")
               for r, rew, PA, lab, s, yaw, tilt in tds]
    th = max([im.height for im in td_imgs] + [0])
    H = len(rows) * (W + 40) + (th + 40 if td_imgs else 0) + 10
    canvas = Image.new("RGB", (cw, H), "white"); d = ImageDraw.Draw(canvas)
    y = 10
    for title, ims in rows:
        d.text((10, y), title, fill="black"); y += 25
        for i, im in enumerate(ims):
            canvas.paste(im, (10 + i * (W + 10), y))
        y += W + 15
    if td_imgs:
        d.text((10, y), f"{a.title} - TOP-DOWN as the scorer sees each run (after aligning the whole room)", fill="black"); y += 25
        x = 10
        for im in td_imgs:
            canvas.paste(im, (x, y)); x += im.width + 10
    out = a.out or os.path.join(a.results, "rollouts_vs_golden.png")
    canvas.save(out); print(out)


if __name__ == "__main__":
    main()
