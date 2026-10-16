#!/usr/bin/env python3
"""Per-item diagnosis of a reconstruction against a task's answer key, using the verifier's exact
alignment and nearest-item assignment. Used to write GLM feedback and LOST_POINTS.md.

  python tooling/diagnose.py tasks/<task> <pred.glb> [--json out.json]
"""
import argparse, json, os, sys
import numpy as np, trimesh
from scipy.spatial import cKDTree
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "tooling", "scorer"))
import metrics as M  # noqa


def sample_named(glb):
    sc = trimesh.load(glb)
    pts, names = [], []
    geoms = ([(node, *sc.graph[node]) for node in sc.graph.nodes_geometry] if isinstance(sc, trimesh.Scene)
             else [("mesh", np.eye(4), None)])
    for i, (node, tf, gn) in enumerate(geoms):
        g = sc.geometry[gn] if gn is not None else sc
        if not isinstance(g, trimesh.Trimesh):
            continue
        m = g.copy(); m.apply_transform(tf)
        p = M._yup_to_zup(M._sample_surface(m, seed=1000 + i))
        pts.append(p); names += [node] * len(p)
    return np.vstack(pts), np.array(names)


def bbox(v):
    lo, hi = v.min(0), v.max(0)
    return (lo + hi) / 2, hi - lo


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("task"); ap.add_argument("pred"); ap.add_argument("--json")
    a = ap.parse_args()
    Q, parts = M.load_gt_furniture(os.path.join(a.task, "tests", "golden"))
    P = M.sample_scene_glb(a.pred)              # exactly what the verifier samples
    Pn, names = sample_named(a.pred)            # same points, with object names
    assert len(P) == len(Pn)
    sc = M.score_reconstruction(P, Q, gt_parts=parts)
    # reproduce the verifier's alignment (same rng/sample as score_reconstruction)
    rng = np.random.default_rng(0); sample = 4000
    Ps = P[rng.choice(len(P), sample, False)] if len(P) > sample else P
    Pa, _ = M.icp_sim3(Ps, Q, sample=sample, rng=rng)
    s, R, t = M.umeyama_sim3(Ps, Pa)
    PA = (s * (R @ P.T)).T + t
    yaw = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    Qp = [g for _, g in parts]
    owner = np.concatenate([np.full(len(g), i) for i, g in enumerate(Qp)])
    _, nn = cKDTree(np.vstack(Qp)).query(PA); lab = owner[nn]
    _, nn0 = cKDTree(np.vstack(Qp)).query(P); lab0 = owner[nn0]
    out = {"reward": sc["obj_f@5%_nn"], "align": {"scale": float(s), "yaw_deg": float(yaw), "t": t.tolist()},
           "no_align_reward": None, "items": []}
    fs0 = []
    for i, g in enumerate(Qp):
        pp = P[lab0 == i]; tau = 0.05 * np.linalg.norm(g.max(0) - g.min(0))
        fs0.append(M.f_score(pp, g, tau)["fscore"] if len(pp) >= 10 else 0.0)
    out["no_align_reward"] = float(np.mean(fs0))
    for i, ((name, g), pr) in enumerate(zip(parts, sc["per_object_nn"])):
        gc, gs = bbox(g)
        it = {"item": name, "f": pr["f@5%"], "precision": pr["precision"], "recall": pr["recall"],
              "n_pred": pr["n_pred"], "target_center": gc.round(3).tolist(), "target_size": gs.round(3).tolist(),
              "tolerance_m": round(float(0.05 * np.linalg.norm(gs)), 3)}
        m = lab == i
        if m.sum() >= 10:
            pc, psz = bbox(PA[m]); it["aligned_center"] = pc.round(3).tolist(); it["aligned_size"] = psz.round(3).tolist()
            rc, rsz = bbox(P[m]); it["raw_center"] = rc.round(3).tolist(); it["raw_size"] = rsz.round(3).tolist()
            objs, cnt = np.unique(names[m], return_counts=True)
            it["objects"] = {o: int(c) for o, c in sorted(zip(objs, cnt), key=lambda x: -x[1])}
            # points of those objects that went to other items
        out["items"].append(it)
    # which item each agent object mostly feeds
    obj_map = {}
    for o in np.unique(names):
        mm = names == o; l = lab[mm]; vals, c = np.unique(l, return_counts=True)
        obj_map[o] = {parts[v][0]: round(float(cc / mm.sum()), 2) for v, cc in zip(vals, c)}
    out["objects"] = obj_map
    print(f"reward {out['reward']:.3f}  (no alignment {out['no_align_reward']:.3f});  alignment scale x{s:.2f}, yaw {yaw:+.0f} deg, shift {np.round(t, 2)}")
    for it in out["items"]:
        print(f"\n{it['item']:<14s} F {it['f']:.2f}  P {it['precision']:.2f}  R {it['recall']:.2f}  pts {it['n_pred']}  tol {it['tolerance_m']*100:.0f} cm")
        print(f"   target  centre {it['target_center']}  size {it['target_size']}")
        if "aligned_center" in it:
            print(f"   aligned centre {it['aligned_center']}  size {it['aligned_size']}")
            print(f"   raw     centre {it['raw_center']}  size {it['raw_size']}")
            print(f"   from objects: {dict(list(it['objects'].items())[:8])}")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
