"""Analyze a graded rollout GLB the way the scorer sees it, for LOST_POINTS.md
and scorer-aligned top-down overlays.

  python tooling/analyze_rollout.py <agent_scene.glb> <golden_dir> <map.json> <score.json> <out_prefix>

- Re-runs the verifier's deterministic pipeline (tooling/scorer/metrics.py, rng 0)
  on a display copy of the scene and ABORTS if the reproduced obj_f@5%_nn differs
  from score.json's reward by > 1e-6 (the submitted graded GLB is never modified).
- map.json: {"<golden item>": ["node_name", ...], "unmapped": [...]} — documented
  per-run assignment of GLB node names to golden items (by name + centroid evidence).
- Writes <out_prefix>_analysis.json: alignment (scale/yaw/tilt/translation),
  unaligned score, and per-item stats (f/p/r, n_pred, top source nodes of the
  points the scorer assigned to each item, per mapped group: centre offset and
  size ratio vs the golden part).
- Writes <out_prefix>_topdown.png: golden parts (colour) vs the aligned prediction
  (black), 1 m grid — the scene as the scorer sees it.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tooling"))
sys.path.insert(0, os.path.join(ROOT, "tooling", "scorer"))
import metrics as M  # noqa: E402
import trimesh  # noqa: E402

PALETTE = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 170, 170)]


def per_node_samples(glb_path):
    """Same traversal/seeds as metrics.sample_scene_glb, but tagged by node name.
    trimesh appends a random _XXXXXX suffix to DUPLICATE node names on load
    (nondeterministic); strip it so tags are stable across runs."""
    import re
    scene = trimesh.load(glb_path)
    out = []
    geoms = ([(node, scene.graph[node]) for node in scene.graph.nodes_geometry]
             if isinstance(scene, trimesh.Scene) else [("scene", (np.eye(4), scene))])
    for i, (node, (tf, gn)) in enumerate(geoms):
        g = scene.geometry[gn] if isinstance(scene, trimesh.Scene) else scene
        if not isinstance(g, trimesh.Trimesh):
            continue
        m = g.copy()
        m.apply_transform(tf)
        tag = re.sub(r"_[0-9a-f]{6}$", "", node)
        out.append((tag, M._yup_to_zup(M._sample_surface(m, seed=1000 + i))))
    return out


def nn_partition(P_full, parts):
    Q_all = np.vstack([g for _, g in parts])
    owner = np.concatenate([np.full(len(g), i) for i, (_, g) in enumerate(parts)])
    _, nn = cKDTree(Q_all).query(P_full)
    return owner[nn]


def per_item_f(P_full, parts, lab):
    rows = []
    for i, (name, gv) in enumerate(parts):
        Pp = P_full[lab == i]
        tau = 0.05 * float(np.linalg.norm(gv.max(0) - gv.min(0)))
        fr = M.f_score(Pp, gv, tau) if len(Pp) >= 10 else {"fscore": 0.0, "precision": 0.0, "recall": 0.0}
        rows.append({"part": name, "n_pred": int(len(Pp)), "f@5%": fr["fscore"],
                     "precision": fr["precision"], "recall": fr["recall"]})
    return rows


def main():
    glb, golden_dir, map_path, score_path, out_prefix = sys.argv[1:6]
    item_map = json.load(open(map_path))
    score = json.load(open(score_path))

    tagged = per_node_samples(glb)
    P = np.vstack([p for _, p in tagged])
    tags = np.concatenate([np.full(len(p), n) for n, p in tagged])
    Q, parts = M.load_gt_furniture(golden_dir)

    # exact verifier pipeline (rng 0, sample 4000)
    rng = np.random.default_rng(0)
    Ps = P[rng.choice(len(P), 4000, False)] if len(P) > 4000 else P
    Pa, Qs = M.icp_sim3(Ps, Q, sample=4000, rng=rng)
    s_al, R_al, t_al = M.umeyama_sim3(Ps, Pa)
    P_full = (s_al * (R_al @ P.T)).T + t_al

    lab = nn_partition(P_full, parts)
    repro = per_item_f(P_full, parts, lab)
    repro_reward = float(np.mean([r["f@5%"] for r in repro]))
    if abs(repro_reward - score["reward"]) > 1e-6:
        raise SystemExit(f"repro mismatch: {repro_reward:.10f} vs score.json {score['reward']:.10f}")

    # unaligned score (same NN partition, raw P)
    lab0 = nn_partition(P, parts)
    unaligned = float(np.mean([r["f@5%"] for r in per_item_f(P, parts, lab0)]))

    # alignment decomposition
    yaw = float(np.degrees(np.arctan2(R_al[1, 0], R_al[0, 0])))
    z_rot = R_al @ np.array([0, 0, 1.0])
    tilt = float(np.degrees(np.arccos(np.clip(z_rot[2], -1, 1))))
    align = {"scale": s_al, "yaw_deg": yaw, "tilt_deg": tilt,
             "translation_m": [round(float(v), 4) for v in t_al]}

    # per mapped group: aligned points
    groups = {}
    for item, nodes in item_map.items():
        if item == "unmapped":
            continue
        mask = np.isin(tags, nodes)
        groups[item] = {"n": int(mask.sum()), "aligned": P_full[mask] if mask.any() else np.zeros((0, 3))}

    items = []
    for i, (name, gv) in enumerate(parts):
        row = dict(repro[i])
        Pp_tags = tags[lab == i]
        if len(Pp_tags):
            uniq, cnt = np.unique(Pp_tags, return_counts=True)
            order = np.argsort(-cnt)
            row["pred_points_from"] = [{"node": str(uniq[j]), "pct": round(100 * cnt[j] / len(Pp_tags), 1)}
                                       for j in order[:4]]
        else:
            row["pred_points_from"] = []
        g = groups.get(name)
        gc = (gv.max(0) + gv.min(0)) / 2
        if g and g["n"] >= 10:
            pc = (g["aligned"].max(0) + g["aligned"].min(0)) / 2
            row["built_nodes"] = [n for n in item_map[name]]
            row["centre_offset_m"] = [round(float(v), 3) for v in (pc - gc)]
            row["centre_offset_abs_m"] = round(float(np.linalg.norm(pc - gc)), 3)
            row["size_ratio"] = round(float(np.linalg.norm(g["aligned"].max(0) - g["aligned"].min(0)) /
                                          np.linalg.norm(gv.max(0) - gv.min(0))), 3)
        else:
            row["built_nodes"] = []
        items.append(row)

    analysis = {"glb": glb, "reward_score_json": score["reward"], "reward_repro": repro_reward,
                "alignment": align, "unaligned_obj_f@5%_nn": unaligned,
                "item_map": item_map, "items": items}
    with open(out_prefix + "_analysis.json", "w") as f:
        json.dump(analysis, f, indent=1)

    # aligned top-down overlay (golden colour vs aligned pred black, 1 m grid)
    S = 70
    lo = np.minimum(P_full.min(0), Q.min(0)) - 0.3
    hi = np.maximum(P_full.max(0), Q.max(0)) + 0.3
    Wd, H = int((hi[0] - lo[0]) * S), int((hi[1] - lo[1]) * S)
    title_lines = ["Top-down as the scorer sees it (after whole-scene alignment):",
                   "golden (colour) vs model (black), 1 m grid"]
    d_tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_w = max(int(d_tmp.textlength(t)) for t in title_lines) + 16
    Wd = max(Wd, title_w)
    im = Image.new("RGB", (Wd, H + 48), "white")
    d = ImageDraw.Draw(im)
    for k, t in enumerate(title_lines):
        d.text((8, 6 + 14 * k), t, fill="black")
    HDR = 48
    for gx in range(int(np.ceil(lo[0])), int(hi[0]) + 1):
        x = (gx - lo[0]) * S
        d.line([(x, HDR), (x, H + HDR)], fill=(235, 235, 235))
    for gy in range(int(np.ceil(lo[1])), int(hi[1]) + 1):
        y = H - (gy - lo[1]) * S + HDR
        d.line([(0, y), (Wd, y)], fill=(235, 235, 235))
    for a, b in zip((P_full[::4, 0] - lo[0]) * S, H - (P_full[::4, 1] - lo[1]) * S):
        d.point((a, b + HDR), fill=(40, 40, 40))
    for i, (n, g) in enumerate(parts):
        x, y = (g[::4, 0] - lo[0]) * S, H - (g[::4, 1] - lo[1]) * S
        col = PALETTE[i % len(PALETTE)]
        for a, b in zip(x, y):
            d.point((a, b + HDR), fill=col)
        d.text((x.mean() + 4, y.mean() + HDR), n, fill=col)
    im.save(out_prefix + "_topdown.png")

    print(f"repro OK: {repro_reward:.10f} == score.json {score['reward']:.10f}")
    print(f"alignment: scale {s_al:.4f}, yaw {yaw:+.1f} deg, tilt {tilt:.1f} deg, "
          f"t {align['translation_m']}; unaligned score {unaligned:.4f}")
    print(f"wrote {out_prefix}_analysis.json and {out_prefix}_topdown.png")


if __name__ == "__main__":
    main()
