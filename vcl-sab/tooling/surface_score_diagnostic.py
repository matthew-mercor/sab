"""Diagnostic only: score with surface samples (the paper TEXT's 'sampled surface points')
instead of mesh vertices (the paper CODE). Same official score_reconstruction otherwise.
Not the reward. usage: python tooling/surface_score_diagnostic.py . <task> <scene.glb>..."""
import os, sys, glob, warnings
import numpy as np, trimesh
warnings.filterwarnings("ignore")
ROOT, task = sys.argv[1:3]; preds = sys.argv[3:]
sys.path.insert(0, os.path.join(ROOT, "tooling", "scorer"))
import paper_score as PS
def meshes(path):
    sc = trimesh.load(path); out = []
    for node in sc.graph.nodes_geometry:
        tf, name = sc.graph[node]; g = sc.geometry[name]
        if isinstance(g, trimesh.Trimesh) and len(g.faces):
            m = g.copy(); m.apply_transform(tf); m.vertices = PS._yup_to_zup(m.vertices); out.append((name, m))
    return out
def surf(m, n=4000, seed=0):
    return np.asarray(trimesh.sample.sample_surface(m, n, seed=seed)[0], float)
gt = glob.glob(os.path.join(ROOT, "tasks", task, "tests", "golden", "scene", "*_full.glb"))[0]
parts = [(n[:24], surf(m, 4000, i)) for i, (n, m) in enumerate(meshes(gt))]
Q = np.vstack([v for _, v in parts])
for p in preds:
    P = np.vstack([surf(m, 4000, 100 + i) for i, (_, m) in enumerate(meshes(p))])
    sc = PS.score(P, Q, parts)
    print(f"{p[-60:]}: surface-sample F@5% {sc['obj_f@5%_matched']:.3f}  clusters {sc['n_clusters']}  ",
          {q['part'][:12]: round(q['f@5%_matched'], 2) for q in sc['per_object_matched']})
