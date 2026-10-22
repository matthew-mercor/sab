"""Score any reconstruction against a task's answer key with the paper's scorer (same as the Harbor verifier).

  python tooling/verify.py tasks/recon-gaming-room --pred my_scene.glb            # score a reconstruction
  python tooling/verify.py tasks/recon-gaming-room --pred my_scene.glb --verts agent_verts.json
  python tooling/verify.py tasks/recon-gaming-room --golden-check                 # golden vs itself (the room's ceiling)

Reward = obj_f@5%_matched, the paper's primary F@5% (see scorer/paper_score.py). The verifier scores the
agent's Blender vertices (agent_verts.json, written by export_scene.py, <= 4,000 per mesh before
modifiers). With only a .glb (a Blender export, Z-up), its mesh vertices are used instead.
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scorer"))
import paper_score as PS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir", help="tasks/<task>")
    ap.add_argument("--pred", help="reconstruction .glb to score")
    ap.add_argument("--verts", help="agent_verts.json from the verifier (preferred over the .glb's vertices)")
    ap.add_argument("--golden-check", action="store_true", help="score the golden solution against itself")
    ap.add_argument("--json", help="also write the full score dict here")
    a = ap.parse_args()

    golden_dir = os.path.join(a.task_dir, "tests", "golden")
    golden_glb = os.path.join(a.task_dir, "solution", "golden_scene.glb")
    if a.golden_check:
        pred = golden_glb
    elif a.pred or a.verts:
        pred = a.pred
    else:
        ap.error("give --pred <file.glb> (and/or --verts) or --golden-check")

    Q, parts = PS.load_answer_key(golden_dir)
    P = PS.load_agent_vertices(a.verts, pred)
    sc = PS.score(P, Q, parts)

    print(f"task   : {os.path.basename(os.path.normpath(a.task_dir))}")
    print(f"scored : {a.verts or pred}  ({len(P)} vertices)")
    print(f"\nREWARD  paper F@5% (obj_f@5%_matched) = {sc['obj_f@5%_matched']:.3f}"
          f"   ({sc.get('n_clusters')} clusters for {len(parts)} items, match rate {sc.get('match_rate', 0):.2f})")
    print("\nper item                F@5%   precision  recall  matched  tolerance")
    for p, (_, g) in zip(sc["per_object_matched"], parts):
        tol = 5 * np.linalg.norm(g.max(0) - g.min(0))
        print(f"  {p['part']:<20s} {p['f@5%_matched']:.2f}    {p.get('precision_matched', 0):.2f}       "
              f"{p.get('recall_matched', 0):.2f}    {'yes' if p['matched'] else 'NO ':<7s}  {tol:.0f} cm")
    print(f"\naudit (not in the reward): region F@5% {sc.get('obj_f@5%', float('nan')):.3f}, "
          f"whole-room F@5% {sc.get('f@5%', float('nan')):.2f}, mean centroid error {sc.get('mean_pos_err', float('nan')):.2f} m")
    if a.golden_check:
        print(f"\ngolden check: {sc['obj_f@5%_matched']:.3f} is this room's ceiling under the paper's scorer"
              f"{'' if sc['obj_f@5%_matched'] >= 0.9 else ' (below 0.9: space items apart, even out vertex counts)'}")
    if a.json:
        json.dump(sc, open(a.json, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
