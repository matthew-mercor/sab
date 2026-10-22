"""SceneActBench Reconstruction verifier, scored as in the paper.

Reward = the paper's primary F@5% (obj_f@5%_matched), computed by the official scorer
(scorer/sab_official_metrics.py, unchanged; see scorer/paper_score.py): fixed-scale ICP over the
whole scene, DBSCAN splits the agent's points into objects, Hungarian matching pairs them with
answer-key objects, each matched cluster is moved onto its object's centre, and per-object F@5%
(5% of each object's diagonal; unmatched = 0) is averaged over the answer-key objects.
The agent's points are its mesh vertices read in Blender (<= 4,000 per mesh, before modifiers);
the answer key's are converted to Blender's Z-up, and its objects are kept by the official furniture-name
filter plus our added furniture types (see scorer/paper_score.py).
score.json also carries diagnostics that do not enter the reward: the alignment's turn and scale, and
the score with the alignment's starting turn fixed to 0 degrees (task_frame_f@5%).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scorer"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", required=True, help="dir containing scene/*_full.glb")
    ap.add_argument("--pred", required=True, help="agent scene .glb (Blender export, Z-up)")
    ap.add_argument("--verts", default=None, help="agent_verts.json from export_scene.py")
    ap.add_argument("--reward", required=True)
    ap.add_argument("--details", required=True)
    a = ap.parse_args()

    reward, details, parts = 0.0, {}, []
    try:
        import paper_score as PS
        Q, parts = PS.load_answer_key(a.golden)
        P = PS.load_agent_vertices(a.verts, a.pred)
        if len(P) < 10:
            raise ValueError("agent scene has fewer than 10 mesh vertices")
        sc = PS.score(P, Q, parts)
        if "error" in sc:
            raise ValueError(sc["error"])
        if "obj_f@5%_matched" not in sc:
            raise RuntimeError(f"object matching failed: {sc.get('match_error')}")
        reward = float(min(max(sc["obj_f@5%_matched"], 0.0), 1.0))
        per = [{"part": p["part"], "matched": p["matched"], "n_pred": p["n_cluster_pts"],
                "f@5%": p["f@5%_matched"], "precision": p.get("precision_matched", 0.0),
                "recall": p.get("recall_matched", 0.0), "pos_err_m": p["pos_err"]}
               for p in sc["per_object_matched"]]
        details = {
            "reward": reward,
            "metric": "obj_f@5%_matched (SceneActBench primary F@5%)",
            "per_object": per,
            "n_clusters": sc.get("n_clusters"),
            "match_rate": sc.get("match_rate"),
            "mean_pos_err_m": sc.get("mean_pos_err"),
            "points": {"agent_vertices": int(len(P)), "answer_key_vertices": int(len(Q)),
                       "agent_source": "agent_verts.json" if a.verts and os.path.isfile(a.verts) else "glb vertices"},
            # The paper's audit metrics (they do not enter the score):
            "audit": {"region_obj_f@5%": sc.get("obj_f@5%"), "object_coverage": sc.get("object_coverage"),
                      "scene_f@5%": sc.get("f@5%"), "scene_recall@5%": sc.get("recall@5%"),
                      "scene_prec@5%": sc.get("prec@5%"), "chamfer_aligned": sc.get("chamfer_aligned")},
        }
        # Diagnostics, not the reward: the turn the paper's alignment applied, and the same score with
        # its starting turn fixed to 0 degrees (see scorer/paper_score.py, score_task_frame).
        try:
            al = PS.alignment(P, Q)
            tf = PS.score_task_frame(P, Q, parts)
            details["diagnostics"] = {
                "alignment_yaw_deg": al["yaw_deg"], "alignment_scale": al["scale"],
                "alignment_turned_over_45deg": abs(al["yaw_deg"]) > 45,
                "task_frame_f@5%": tf.get("obj_f@5%_matched"),
                "task_frame_per_object": {p["part"]: p["f@5%_matched"] for p in tf.get("per_object_matched", [])},
            }
        except Exception as e:
            details["diagnostics"] = {"error": repr(e)}
    except Exception as e:  # any failure scores 0, every answer-key object unmatched
        details = {"reward": 0.0, "metric": "obj_f@5%_matched (SceneActBench primary F@5%)",
                   "per_object": [{"part": name, "matched": False, "n_pred": 0, "f@5%": 0.0, "precision": 0.0,
                                   "recall": 0.0, "pos_err_m": None} for name, _ in parts],
                   "error": repr(e)}
    os.makedirs(os.path.dirname(a.reward), exist_ok=True)
    open(a.reward, "w").write(f"{reward:.4f}\n")
    json.dump(details, open(a.details, "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in details.items() if k not in ("per_object", "diagnostics")}, default=float))
    dg = details.get("diagnostics", {})
    if "task_frame_f@5%" in dg:
        print(f"diagnostic (not the reward): alignment turned the scene {dg['alignment_yaw_deg']:.0f} deg; "
              f"score with the starting turn fixed to 0 deg = {dg['task_frame_f@5%']:.3f}")
    for p in details.get("per_object", []):
        print(f"  {p['part']:<16s} F={p['f@5%']:.2f}  P={p['precision']:.2f}  R={p['recall']:.2f}"
              f"  {'matched' if p['matched'] else 'UNMATCHED'}")


if __name__ == "__main__":
    main()
