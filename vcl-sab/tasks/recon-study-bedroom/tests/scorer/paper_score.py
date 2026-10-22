"""SceneActBench Reconstruction score, as in the paper: primary F@5% (obj_f@5%_matched).

The scoring is the official code, unchanged: sab_official_metrics.score_reconstruction from
github.com/Feinaldo2/SceneActBench (src/harness/metrics.py, MIT License, commit 5b01037).
It runs fixed-scale ICP on the merged scene, splits the aligned prediction into objects with
DBSCAN, matches clusters to answer-key objects with the Hungarian method, moves each matched
cluster onto its object's centre, and averages per-object F@5% (tolerance 5% of each object's
bounding-box diagonal; an unmatched object scores 0). Paper: Section 3.5 and Appendix A.3.4.

What this file adds around it:
  - Agent points: the world vertices of every mesh in the agent's Blender scene, at most 4,000
    per mesh, read with the official READ_VERTS_CODE (export_scene.py saves them as
    agent_verts.json). If only a GLB exists, its mesh vertices are used the same way.
  - Answer key points: every vertex of every mesh in the curated answer key
    (tests/golden/scene/*_full.glb), as the official load_gt_furniture reads them, with a fix:
    they are converted from glTF's Y-up to Blender's Z-up. The released loader leaves them Y-up
    while the agent's vertices come from Blender in Z-up, so a perfect reconstruction is scored
    lying on its side (the alignment only searches rotations about the vertical axis); on 10 of
    the paper's own 3D-FRONT rooms that bug drops a perfect copy from 0.49 to 0.21 on average.
  - Answer-key objects are kept by the official loader's name filter (an object counts if its name
    contains one of the furniture words in load_gt_furniture, which is how the paper drops walls and
    floors from 3D-FRONT rooms), with furniture words added for our rooms (EXTRA_FURNITURE_WORDS:
    kitchen fittings, benches, ottomans). The filter decides only which objects count; how they are
    scored is unchanged. Every object in our answer keys must pass it (check_answer_key), so no
    built item is silently dropped.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sab_official_metrics as official  # noqa: E402  (the paper's scorer, unchanged)

VERTS_PER_MESH = 4000   # official read_predicted_verts(sample=4000)

# The furniture words of the official load_gt_furniture (a local there, so repeated here verbatim) ...
OFFICIAL_FURNITURE_WORDS = ("Bed", "Cabinet", "Lighting", "Chair", "Table", "Sofa", "Wardrobe",
                            "Desk", "Shelf", "Stool", "Nightstand", "Pendant", "Dressing", "TV",
                            "Wine", "Bookshelf", "Lamp", "Couch", "Stand")
# ... and the furniture types our rooms add, which the paper's 3D-FRONT rooms never named.
EXTRA_FURNITURE_WORDS = ("Counter", "Cooker", "Sink", "Fridge", "Heater", "Island", "Bench", "Ottoman")
FURNITURE_WORDS = OFFICIAL_FURNITURE_WORDS + EXTRA_FURNITURE_WORDS


def is_graded(name: str) -> bool:
    """Whether an answer-key object counts, by the official name test (substring, case-sensitive)."""
    return any(w in name for w in FURNITURE_WORDS)


def _yup_to_zup(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, float)
    return np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])


def _glb_mesh_vertices(path: str):
    import trimesh

    scene = trimesh.load(path)
    if not isinstance(scene, trimesh.Scene):
        return [("mesh", np.asarray(scene.vertices, float))]
    out = []
    for node in scene.graph.nodes_geometry:
        tf, name = scene.graph[node]
        g = scene.geometry[name]
        if isinstance(g, trimesh.Trimesh) and len(g.vertices):
            out.append((name, trimesh.transformations.transform_points(np.asarray(g.vertices), tf)))
    return out


def load_answer_key(golden_dir: str):
    """Answer-key vertices per object, in Blender Z-up. Returns (Q_all, [(name, (M,3)), ...])."""
    cand = glob.glob(os.path.join(golden_dir, "scene", "*_full.glb"))
    if not cand:
        raise FileNotFoundError(f"no scene/*_full.glb under {golden_dir}")
    parts = [(name[:24], _yup_to_zup(v)) for name, v in _glb_mesh_vertices(cand[0]) if is_graded(name)]
    if not parts:
        raise ValueError("answer key has no furniture meshes")
    return np.vstack([v for _, v in parts]), parts


def check_answer_key(glb: str) -> list:
    """Names of answer-key meshes the furniture filter would drop (should be empty)."""
    return [name for name, _ in _glb_mesh_vertices(glb) if not is_graded(name)]


def load_agent_vertices(verts_json: str | None, glb: str | None) -> np.ndarray:
    """The agent's world vertices, <= 4,000 per mesh, in Blender Z-up."""
    if verts_json and os.path.isfile(verts_json) and os.path.getsize(verts_json) > 0:
        raw = json.load(open(verts_json))
        meshes = [np.asarray(v, float) for v in raw.values() if v]
    elif glb and os.path.isfile(glb) and os.path.getsize(glb) > 0:
        # Same per-mesh cap and seed rule as READ_VERTS_CODE, on the exported GLB.
        import random
        random.seed(0)
        meshes = []
        for _, v in _glb_mesh_vertices(glb):
            v = _yup_to_zup(v)
            if len(v) > VERTS_PER_MESH:
                v = v[random.sample(range(len(v)), VERTS_PER_MESH)]
            meshes.append(v)
    else:
        raise FileNotFoundError("no agent scene to score")
    meshes = [m for m in meshes if len(m)]
    return np.vstack(meshes) if meshes else np.zeros((0, 3))


def score(P: np.ndarray, Q: np.ndarray, parts) -> dict:
    """Official scoring. Returns the official result dict; the reward is obj_f@5%_matched."""
    return official.score_reconstruction(P, Q, gt_parts=parts)


# ---------------------------------------------------------------- diagnostic, not the reward
# The official fixed-scale ICP tries four starting turns (0/90/180/270 degrees) and keeps the best
# fit. With sparse agent points it can pick a wrong turn (e.g. -85 degrees for a correct layout),
# which then pairs the agent's objects with the wrong answer-key objects. In these tasks the agent
# builds in the same world frame as the answer key (the prompt gives every camera pose in it), so the
# diagnostic below keeps only the 0-degree start: same scale, same ICP refinement, same clustering,
# matching and F@5%. It is reported next to the reward and never replaces it.

def _icp_task_frame(P, Q, iters=30, sample=4000, rng=None):
    """official.icp_sim3 with only the 0-degree starting turn."""
    rng = rng or np.random.default_rng(0)
    P = np.asarray(P, float); Q = np.asarray(Q, float)
    if len(P) > sample: P = P[rng.choice(len(P), sample, False)]
    if len(Q) > sample: Q = Q[rng.choice(len(Q), sample, False)]

    def diag(X): return np.linalg.norm(X.max(0) - X.min(0))
    from scipy.spatial import cKDTree
    s_fixed = diag(Q) / (diag(P) + 1e-9)
    treeQ = cKDTree(Q)
    Pa = s_fixed * (P - official._center(P)) + official._center(Q)
    prev = 1e18
    for _ in range(iters):
        _, idx = treeQ.query(Pa)
        A, B = Pa, Q[idx]
        muA, muB = A.mean(0), B.mean(0)
        U, _, Vt = np.linalg.svd((A - muA).T @ (B - muB))
        S = np.eye(3)
        if np.linalg.det(Vt.T @ U.T) < 0:
            S[2, 2] = -1
        R = Vt.T @ S @ U.T
        Pa = (R @ Pa.T).T + (muB - R @ muA)
        d, _ = treeQ.query(Pa)
        if abs(prev - d.mean()) < 1e-5:
            break
        prev = d.mean()
    return Pa, Q


def alignment(P: np.ndarray, Q: np.ndarray, sample: int = 4000) -> dict:
    """Turn (degrees about the vertical) and scale the official alignment applied to the agent scene."""
    P = np.asarray(P, float)
    rng = np.random.default_rng(0)
    idx = rng.choice(len(P), sample, False) if len(P) > sample else np.arange(len(P))
    Pa, _ = official.icp_sim3(P, Q, sample=sample, rng=np.random.default_rng(0))
    s, R, _ = official.umeyama_sim3(P[idx], Pa)
    return {"yaw_deg": float(np.degrees(np.arctan2(R[1, 0], R[0, 0]))), "scale": float(s)}


def score_task_frame(P: np.ndarray, Q: np.ndarray, parts) -> dict:
    """Diagnostic: the official score with the alignment's starting turn fixed to 0 degrees."""
    orig = official.icp_sim3
    official.icp_sim3 = _icp_task_frame
    try:
        return official.score_reconstruction(P, Q, gt_parts=parts)
    finally:
        official.icp_sim3 = orig
