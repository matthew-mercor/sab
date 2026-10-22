# How this score was produced: golden

Task `recon-study-bedroom`. **Reward 0.982** (the paper's F@5%). Secondary scorer 0.982 (diagnostic, not the reward).

Every number below was recomputed with the official functions in `tests/scorer/sab_official_metrics.py` and the same random seeds, and checked against `score.json`.

## 1. Points read from the scene

`tests/export_scene.py` reads every mesh's world-space vertices in Blender, at most 4,000 per mesh (the official `READ_VERTS_CODE`): **6 meshes, 21,535 vertices** (`agent_verts.json`). The answer key (`tests/golden/scene/*_full.glb`, converted to Z-up) has 6 items and 660,162 vertices.

## 2. Whole-scene alignment (fixed-scale ICP)

`icp_sim3` samples 4,000 of the scene's points and 4,000 of the answer key's, scales the scene by the ratio of the two bounding-box diagonals (**×1.00**), then tries four starting turns (0/90/180/270°) and keeps the best fit. Result: the scene was turned **-0°**.

## 3. Splitting the scene into objects (DBSCAN)

Average answer-key item size 1.78 m. The scorer tries grouping distances (eps) from 0.10 to 0.40 × that and keeps the one whose cluster count is closest to 6 (clusters under 30 points are discarded):

| eps ratio | eps | clusters |
|---|---|---|
| 0.10 | 0.18 m | 8 |
| 0.15 | 0.27 m | 6 ← chosen |

6 clusters kept; 35 points left as noise.

| Cluster | Points | Made of the agent's meshes |
|---|---|---|
| c0 | 735 | `Desk` 100% |
| c1 | 728 | `Bed` 100% |
| c2 | 751 | `TV_Stand` 100% |
| c3 | 736 | `Desk_Chair` 100% |
| c4 | 724 | `Sofa` 100% |
| c5 | 291 | `Side_Table` 100% |

## 4. Pairing clusters with answer-key items (Hungarian matching)

Each item is paired with one cluster by centre distance; pairs farther than 0.6 × the scene diagonal (3.56 m) are rejected, and an unpaired item scores 0.

## 5. Shape score per item (F@5%)

The paired cluster is moved onto the item's centre (placement is not scored). Precision = share of the cluster's points within the tolerance of the item's surface points; recall = share of the item's points within the tolerance of the cluster; F = their harmonic mean. Tolerance = 5% of the item's bounding-box diagonal.

| Item | Tolerance | Paired with | Centre distance | Points | Precision | Recall | F@5% |
|---|---|---|---|---|---|---|---|
| TV_Stand | 9.5 cm | c2 (`TV_Stand` 100%) | 0.01 m | 751 | 1.00 | 0.96 | **0.98** |
| Side_Table | 4.4 cm | c5 (`Side_Table` 100%) | 0.05 m | 291 | 1.00 | 0.98 | **0.99** |
| Sofa | 10.1 cm | c4 (`Sofa` 100%) | 0.04 m | 724 | 1.00 | 0.92 | **0.96** |
| Desk_Chair | 6.0 cm | c3 (`Desk_Chair` 100%) | 0.03 m | 736 | 1.00 | 0.99 | **0.99** |
| Desk | 9.8 cm | c0 (`Desk` 100%) | 0.03 m | 735 | 1.00 | 0.99 | **1.00** |
| Bed | 13.5 cm | c1 (`Bed` 100%) | 0.06 m | 728 | 1.00 | 0.94 | **0.97** |

**Reward = average of the 6 F@5% values = 0.982.**

## Secondary scorer (diagnostic)

Same steps, but the alignment keeps only the 0° starting turn (the agent builds in the task's own world frame; the prompt gives every camera pose in it). Turn applied: -0°, 6 clusters (eps 0.27 m).

| Item | Paired with | F@5% |
|---|---|---|
| TV_Stand | `TV_Stand` 100% | 0.98 |
| Side_Table | `Side_Table` 100% | 0.99 |
| Sofa | `Sofa` 100% | 0.96 |
| Desk_Chair | `Desk_Chair` 100% | 0.99 |
| Desk | `Desk` 100% | 1.00 |
| Bed | `Bed` 100% | 0.97 |

**Secondary scorer = 0.982.**
