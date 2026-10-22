"""Why does a room's golden score below 1.0 under the paper's scorer?

Re-runs the official clustering step on the golden-vs-itself and reports, per answer-key item:
vertex count, size, internal point spacing, gap to the nearest other item, and which DBSCAN
clusters its points fell into (merged with another item / split into pieces / dropped).
usage: python tooling/diagnose_ceiling.py . <task>...   (run from SceneActBench-Final)
"""
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, "tooling", "scorer"))
import paper_score as PS  # noqa: E402
import sab_official_metrics as OFF  # noqa: E402
from sklearn.cluster import DBSCAN  # noqa: E402


def diagnose(task):
    tdir = os.path.join(ROOT, "tasks", task)
    Q, parts = PS.load_answer_key(os.path.join(tdir, "tests", "golden"))
    P = PS.load_agent_vertices(None, os.path.join(tdir, "solution", "golden_scene.glb"))
    sc = PS.score(P, Q, parts)
    rng = np.random.default_rng(0)
    Pa, _ = OFF.icp_sim3(P, Q, sample=4000, rng=rng)

    # same clustering loop as the official scorer
    diags = [float(np.linalg.norm(g.max(0) - g.min(0))) for _, g in parts]
    avg = float(np.mean(diags))
    K = len(parts)
    best, best_eps, best_pen, best_lab = None, None, 1e9, None
    for ratio in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        eps = max(0.04, ratio * avg)
        lab = DBSCAN(eps=eps, min_samples=10).fit(Pa).labels_
        cls = [c for c in set(lab) if c != -1 and (lab == c).sum() >= 30]
        diff = abs(len(cls) - K)
        pen = diff + (0.5 if len(cls) < K else 0)
        if pen < best_pen:
            best, best_eps, best_pen, best_lab = cls, eps, pen, lab
            if diff == 0 and len(cls) >= K:
                break

    owner = np.concatenate([np.full(len(g), i) for i, (_, g) in enumerate(parts)])
    who = owner[cKDTree(Q).query(Pa)[1]]   # which answer-key item each aligned point belongs to

    print(f"\n=== {task}: ceiling {sc['obj_f@5%_matched']:.3f}   items {K}   avg item size {avg:.2f} m   "
          f"chosen eps {best_eps:.3f} m   clusters kept {len(best)} (need {K})")
    trees = [cKDTree(g) for _, g in parts]
    per = {p["part"]: p for p in sc["per_object_matched"]}
    print(f"  {'item':<24s} {'verts':>6s} {'size m':>6s} {'spacing p95/max':>16s} {'gap to nearest':>22s}  "
          f"{'F@5%':>5s}  clusters (share of item's points)")
    for i, (name, g) in enumerate(parts):
        nn = cKDTree(g).query(g, k=2)[0][:, 1]
        gaps = [(float(trees[j].query(g)[0].min()), parts[j][0]) for j in range(K) if j != i]
        gap, other = min(gaps) if gaps else (float("nan"), "-")
        mine = best_lab[who == i]
        shares = []
        for c in sorted(set(mine), key=lambda c: -(mine == c).sum()):
            frac = (mine == c).mean()
            if frac < 0.03:
                continue
            if c == -1 or c not in best:
                shares.append(f"dropped {frac:.0%}")
            else:
                others = {parts[j][0][:12] for j in set(who[best_lab == c]) if j != i
                          and (who[best_lab == c] == j).mean() > 0.05}
                tag = f"c{c}" + (f"+merged with {','.join(sorted(others))}" if others else "")
                shares.append(f"{tag} {frac:.0%}")
        print(f"  {name:<24s} {len(g):>6d} {diags[i]:>6.2f} {np.percentile(nn, 95):>7.3f}/{nn.max():<7.3f}  "
              f"{gap:>6.2f} m ({other[:12]:<12s})  {per[name]['f@5%_matched']:>5.2f}  " + "; ".join(shares))


for t in sys.argv[2:]:
    diagnose(t)
