#!/usr/bin/env python3
"""Write SCORE.md for a graded scene: every step of the paper's scoring, with this scene's numbers.

    python tooling/explain_score.py tasks/<task> results/paper-scoring/<task>/kimi-k3-rollout1
    python tooling/explain_score.py tasks/<task> results/paper-scoring/<task>/golden --verts <agent_verts.json>

The folder needs agent_verts.json (the points the verifier scored) and score.json (the verifier's
output); --verts points elsewhere for the first. The steps are re-run with the official functions and
the same random seeds, and the result is checked against score.json's reward before anything is written.
"""
import argparse
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scorer"))
import paper_score as PS  # noqa: E402
import sab_official_metrics as OFF  # noqa: E402


def trace(P, names, Q, parts, icp):
    """Re-run score_reconstruction's matched-F@5% path step by step with the given ICP function."""
    rng = np.random.default_rng(0)
    idx = rng.choice(len(P), 4000, False) if len(P) > 4000 else np.arange(len(P))
    Pa, Qs = icp(P, Q, sample=4000, rng=np.random.default_rng(0))
    lab_mesh = names[idx]
    s, R, _ = OFF.umeyama_sim3(P[idx], Pa)
    yaw = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    diagQ = float(np.linalg.norm(Qs.max(0) - Qs.min(0)))
    from sklearn.cluster import DBSCAN
    from scipy.optimize import linear_sum_assignment
    K = len(parts)
    avg = float(np.mean([np.linalg.norm(g.max(0) - g.min(0)) for _, g in parts]))
    scan, best, best_pen, best_eps, best_lab = [], None, 1e9, None, None
    for ratio in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        eps = max(0.04, ratio * avg)
        lab = DBSCAN(eps=eps, min_samples=10).fit(Pa).labels_
        ids = [c for c in set(lab) if c != -1 and (lab == c).sum() >= 30]
        diff = abs(len(ids) - K)
        pen = diff + (0.5 if len(ids) < K else 0)
        scan.append((ratio, eps, len(ids)))
        if pen < best_pen:
            best, best_pen, best_eps, best_lab = ids, pen, eps, lab
            if diff == 0 and len(ids) >= K:
                break
    clusters = []
    for c in best or []:
        m = best_lab == c
        u, n = np.unique(lab_mesh[m], return_counts=True)
        clusters.append({"pts": Pa[m], "comp": sorted(zip(u, n), key=lambda x: -x[1])})
    noise = int((best_lab == -1).sum()) if best_lab is not None else len(Pa)
    pairs, items = {}, []
    if clusters:
        gc = np.array([g.mean(0) for _, g in parts]); cc = np.array([c["pts"].mean(0) for c in clusters])
        C = np.linalg.norm(gc[:, None] - cc[None], axis=-1); M = 0.6 * diagQ
        Cp = C.copy(); Cp[Cp > M] = M + 100.0
        for r, c in zip(*linear_sum_assignment(Cp)):
            if C[r, c] <= M:
                pairs[r] = (c, float(C[r, c]))
    for gi, (name, g) in enumerate(parts):
        tau = 0.05 * float(np.linalg.norm(g.max(0) - g.min(0)))
        if gi not in pairs:
            items.append({"name": name, "tau": tau, "matched": False, "f": 0.0}); continue
        c, dist = pairs[gi]; pts = clusters[c]["pts"]
        fr = OFF.f_score(pts - pts.mean(0) + g.mean(0), g, tau)
        items.append({"name": name, "tau": tau, "matched": True, "cluster": c, "dist": dist, "n": len(pts),
                      "prec": fr["precision"], "rec": fr["recall"], "f": fr["fscore"]})
    return {"n_sub": len(idx), "scale": float(s), "yaw": yaw, "diagQ": diagQ, "avg": avg, "scan": scan,
            "eps": best_eps, "clusters": clusters, "noise": noise, "items": items,
            "score": float(np.mean([it["f"] for it in items]))}


def comp_text(comp, total, k=4):
    return ", ".join(f"`{n}` {c / total:.0%}" for n, c in comp[:k] if c / total >= 0.03)


def write(task, folder, verts, label):
    Q, parts = PS.load_answer_key(os.path.join(task, "tests", "golden"))
    raw = json.load(open(verts))
    names = np.concatenate([[n] * len(v) for n, v in raw.items() if v])
    P = np.vstack([np.asarray(v, float) for v in raw.values() if v])
    sj = json.load(open(os.path.join(folder, "score.json")))
    t = trace(P, names, Q, parts, OFF.icp_sim3)
    if abs(t["score"] - sj["reward"]) > 1e-4:
        sys.exit(f"trace {t['score']:.4f} != score.json reward {sj['reward']:.4f}; not writing")
    d = trace(P, names, Q, parts, PS._icp_task_frame)
    L = [f"# How this score was produced: {label}", "",
         f"Task `{os.path.basename(os.path.normpath(task))}`. **Reward {sj['reward']:.3f}** (the paper's F@5%). "
         f"Secondary scorer {d['score']:.3f} (diagnostic, not the reward).", "",
         "Every number below was recomputed with the official functions in "
         "`tests/scorer/sab_official_metrics.py` and the same random seeds, and checked against `score.json`.", "",
         "## 1. Points read from the scene", "",
         f"`tests/export_scene.py` reads every mesh's world-space vertices in Blender, at most 4,000 per mesh "
         f"(the official `READ_VERTS_CODE`): **{len(raw)} meshes, {len(P):,} vertices** "
         f"(`agent_verts.json`). The answer key (`tests/golden/scene/*_full.glb`, converted to Z-up) has "
         f"{len(parts)} items and {len(Q):,} vertices.", "",
         "## 2. Whole-scene alignment (fixed-scale ICP)", "",
         f"`icp_sim3` samples {t['n_sub']:,} of the scene's points and 4,000 of the answer key's, scales the scene "
         f"by the ratio of the two bounding-box diagonals (**×{t['scale']:.2f}**), then tries four starting turns "
         f"(0/90/180/270°) and keeps the best fit. Result: the scene was turned **{t['yaw']:.0f}°**."
         + (" That is a large turn: the pieces may be paired with the wrong items (see the secondary scorer)."
            if abs(t["yaw"]) > 45 else ""), "",
         "## 3. Splitting the scene into objects (DBSCAN)", "",
         f"Average answer-key item size {t['avg']:.2f} m. The scorer tries grouping distances (eps) from "
         f"0.10 to 0.40 × that and keeps the one whose cluster count is closest to {len(parts)} "
         "(clusters under 30 points are discarded):", "",
         "| eps ratio | eps | clusters |", "|---|---|---|"]
    L += [f"| {r:.2f} | {e:.2f} m | {n}{' ← chosen' if abs(e - t['eps']) < 1e-9 else ''} |" for r, e, n in t["scan"]]
    L += ["", f"{len(t['clusters'])} clusters kept; {t['noise']} points left as noise.", ""]
    L += ["| Cluster | Points | Made of the agent's meshes |", "|---|---|---|"]
    L += [f"| c{i} | {len(c['pts'])} | {comp_text(c['comp'], len(c['pts']))} |" for i, c in enumerate(t["clusters"])]
    L += ["", "## 4. Pairing clusters with answer-key items (Hungarian matching)", "",
          f"Each item is paired with one cluster by centre distance; pairs farther than 0.6 × the scene diagonal "
          f"({0.6 * t['diagQ']:.2f} m) are rejected, and an unpaired item scores 0.", "",
          "## 5. Shape score per item (F@5%)", "",
          "The paired cluster is moved onto the item's centre (placement is not scored). Precision = share of the "
          "cluster's points within the tolerance of the item's surface points; recall = share of the item's points "
          "within the tolerance of the cluster; F = their harmonic mean. Tolerance = 5% of the item's "
          "bounding-box diagonal.", "",
          "| Item | Tolerance | Paired with | Centre distance | Points | Precision | Recall | F@5% |",
          "|---|---|---|---|---|---|---|---|"]
    for it in t["items"]:
        if not it["matched"]:
            L.append(f"| {it['name']} | {it['tau'] * 100:.1f} cm | nothing | — | — | — | — | **0.00** |"); continue
        c = t["clusters"][it["cluster"]]
        L.append(f"| {it['name']} | {it['tau'] * 100:.1f} cm | c{it['cluster']} ({comp_text(c['comp'], len(c['pts']), 2)}) | "
                 f"{it['dist']:.2f} m | {it['n']} | {it['prec']:.2f} | {it['rec']:.2f} | **{it['f']:.2f}** |")
    L += ["", f"**Reward = average of the {len(parts)} F@5% values = {t['score']:.3f}.**", "",
          "## Secondary scorer (diagnostic)", "",
          "Same steps, but the alignment keeps only the 0° starting turn (the agent builds in the task's own world "
          "frame; the prompt gives every camera pose in it). "
          f"Turn applied: {d['yaw']:.0f}°, {len(d['clusters'])} clusters (eps {d['eps']:.2f} m).", "",
          "| Item | Paired with | F@5% |", "|---|---|---|"]
    for it in d["items"]:
        c = d["clusters"][it["cluster"]] if it["matched"] else None
        L.append(f"| {it['name']} | {comp_text(c['comp'], len(c['pts']), 2) if c else 'nothing'} | {it['f']:.2f} |")
    L += ["", f"**Secondary scorer = {d['score']:.3f}.**", ""]
    open(os.path.join(folder, "SCORE.md"), "w").write("\n".join(L))
    print(f"wrote {os.path.join(folder, 'SCORE.md')}  reward {t['score']:.3f}  secondary {d['score']:.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task"); ap.add_argument("folder")
    ap.add_argument("--verts", help="agent_verts.json (default: <folder>/agent_verts.json)")
    ap.add_argument("--label", help="heading (default: the folder name)")
    a = ap.parse_args()
    write(a.task, a.folder, a.verts or os.path.join(a.folder, "agent_verts.json"), a.label or os.path.basename(os.path.normpath(a.folder)))


if __name__ == "__main__":
    main()
