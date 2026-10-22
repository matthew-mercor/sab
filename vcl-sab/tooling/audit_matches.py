"""Show how the paper's scorer sees an agent's objects: for each answer-key item, which DBSCAN
cluster it was matched to and which of the agent's meshes make up that cluster.
usage: python tooling/audit_matches.py . <task> <agent_verts.json | agent_scene.glb>
(run from SceneActBench-Final; agent_verts.json is exactly what the verifier scored)"""
import os, sys, random, warnings
import numpy as np
warnings.filterwarnings("ignore")
ROOT, task, glb = sys.argv[1:4]
sys.path.insert(0, os.path.join(ROOT, "tooling", "scorer"))
import paper_score as PS, sab_official_metrics as OFF
from sklearn.cluster import DBSCAN
from scipy.optimize import linear_sum_assignment
Q, parts = PS.load_answer_key(os.path.join(ROOT, "tasks", task, "tests", "golden"))
random.seed(0); P, lab_mesh = [], []
if glb.endswith(".json"):   # agent_verts.json from the verifier: exactly what was scored
    import json
    for n, v in json.load(open(glb)).items():
        if v: P.append(np.asarray(v, float)); lab_mesh += [n] * len(v)
else:
  for n, v in PS._glb_mesh_vertices(glb):
    v = PS._yup_to_zup(v)
    if len(v) > 4000: v = v[random.sample(range(len(v)), 4000)]
    P.append(v); lab_mesh += [n] * len(v)
P = np.vstack(P); lab_mesh = np.array(lab_mesh)
sc = PS.score(P, Q, parts)
if len(P) > 4000: lab_mesh = lab_mesh[np.random.default_rng(0).choice(len(P), 4000, False)]  # icp_sim3's subsample
Pa, Qs = OFF.icp_sim3(P, Q, sample=4000, rng=np.random.default_rng(0))
diagQ = float(np.linalg.norm(Qs.max(0) - Qs.min(0)))
avg = float(np.mean([np.linalg.norm(g.max(0) - g.min(0)) for _, g in parts])); K = len(parts)
best, best_pen, eps_b = None, 1e9, None
for r in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
    eps = max(0.04, r * avg); lab = DBSCAN(eps=eps, min_samples=10).fit(Pa).labels_
    ids = [c for c in set(lab) if c != -1 and (lab == c).sum() >= 30]
    diff = abs(len(ids) - K); pen = diff + (0.5 if len(ids) < K else 0)
    if pen < best_pen:
        best, best_pen, eps_b, best_lab = ids, pen, eps, lab
        if diff == 0 and len(ids) >= K: break
if not best:
    print(f"{os.path.relpath(glb, ROOT)}\n  reward {sc['obj_f@5%_matched']:.3f}   agent meshes {len(set(lab_mesh))}   "
          f"no clusters of 30+ points: nothing could be matched"); sys.exit(0)
gc = np.array([g.mean(0) for _, g in parts]); cc = np.array([Pa[best_lab == c].mean(0) for c in best])
C = np.linalg.norm(gc[:, None] - cc[None], axis=-1); Cp = C.copy(); M = 0.6 * diagQ; Cp[Cp > M] = M + 100
used = {r: c for r, c in zip(*linear_sum_assignment(Cp)) if C[r, c] <= M}
print(f"{os.path.relpath(glb, ROOT)}\n  reward {sc['obj_f@5%_matched']:.3f}   agent meshes {len(set(lab_mesh))}   "
      f"clusters {len(best)} for {K} items (eps {eps_b:.2f} m)")
al = PS.alignment(P, Q); tf = PS.score_task_frame(P, Q, parts).get("obj_f@5%_matched", 0.0)
print(f"  alignment turned the scene {al['yaw_deg']:.0f} deg, scale x{al['scale']:.2f}"
      f"{'  <- over 45 deg: pairing may be wrong' if abs(al['yaw_deg']) > 45 else ''}; task-frame diagnostic {tf:.3f}")
per = {p['part']: p for p in sc['per_object_matched']}
for gi, (name, _) in enumerate(parts):
    p = per[name]
    if gi not in used:
        print(f"  {name:<14s} F@5% 0.00  NOT MATCHED"); continue
    m = lab_mesh[best_lab == best[used[gi]]]
    u, cnt = np.unique(m, return_counts=True); o = np.argsort(-cnt)
    comp = ", ".join(f"{u[i][:22]} {cnt[i]/len(m):.0%}" for i in o[:4] if cnt[i]/len(m) >= 0.03)
    print(f"  {name:<14s} F@5% {p['f@5%_matched']:.2f}  (prec {p['precision_matched']:.2f} rec {p['recall_matched']:.2f}, "
          f"off by {p['pos_err']:.2f} m)  cluster = {comp}")
