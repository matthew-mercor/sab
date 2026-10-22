# How this score was produced: kimi-k3-rollout1

Task `recon-study-bedroom`. **Reward 0.105** (the paper's F@5%). Secondary scorer 0.105 (diagnostic, not the reward).

Every number below was recomputed with the official functions in `tests/scorer/sab_official_metrics.py` and the same random seeds, and checked against `score.json`.

## 1. Points read from the scene

`tests/export_scene.py` reads every mesh's world-space vertices in Blender, at most 4,000 per mesh (the official `READ_VERTS_CODE`): **8 meshes, 2,816 vertices** (`agent_verts.json`). The answer key (`tests/golden/scene/*_full.glb`, converted to Z-up) has 6 items and 660,162 vertices.

## 2. Whole-scene alignment (fixed-scale ICP)

`icp_sim3` samples 2,816 of the scene's points and 4,000 of the answer key's, scales the scene by the ratio of the two bounding-box diagonals (**×0.70**), then tries four starting turns (0/90/180/270°) and keeps the best fit. Result: the scene was turned **32°**.

## 3. Splitting the scene into objects (DBSCAN)

Average answer-key item size 1.78 m. The scorer tries grouping distances (eps) from 0.10 to 0.40 × that and keeps the one whose cluster count is closest to 6 (clusters under 30 points are discarded):

| eps ratio | eps | clusters |
|---|---|---|
| 0.10 | 0.18 m | 19 |
| 0.15 | 0.27 m | 11 |
| 0.20 | 0.36 m | 10 |
| 0.25 | 0.44 m | 6 ← chosen |

6 clusters kept; 0 points left as noise.

| Cluster | Points | Made of the agent's meshes |
|---|---|---|
| c0 | 852 | `bed` 69%, `tv` 21%, `tv_cabinet` 10% |
| c1 | 42 | `bed` 100% |
| c2 | 42 | `bed` 100% |
| c3 | 1380 | `chair` 41%, `sofa` 32%, `desk` 14%, `monitor` 13% |
| c4 | 84 | `desk` 100% |
| c5 | 416 | `sidetable` 100% |

## 4. Pairing clusters with answer-key items (Hungarian matching)

Each item is paired with one cluster by centre distance; pairs farther than 0.6 × the scene diagonal (3.49 m) are rejected, and an unpaired item scores 0.

## 5. Shape score per item (F@5%)

The paired cluster is moved onto the item's centre (placement is not scored). Precision = share of the cluster's points within the tolerance of the item's surface points; recall = share of the item's points within the tolerance of the cluster; F = their harmonic mean. Tolerance = 5% of the item's bounding-box diagonal.

| Item | Tolerance | Paired with | Centre distance | Points | Precision | Recall | F@5% |
|---|---|---|---|---|---|---|---|
| TV_Stand | 9.5 cm | c0 (`bed` 69%, `tv` 21%) | 0.66 m | 852 | 0.46 | 0.19 | **0.27** |
| Side_Table | 4.4 cm | c3 (`chair` 41%, `sofa` 32%) | 2.05 m | 1380 | 0.00 | 0.00 | **0.00** |
| Sofa | 10.1 cm | c5 (`sidetable` 100%) | 0.98 m | 416 | 0.84 | 0.07 | **0.12** |
| Desk_Chair | 6.0 cm | c4 (`desk` 100%) | 0.70 m | 84 | 0.50 | 0.00 | **0.01** |
| Desk | 9.8 cm | c1 (`bed` 100%) | 1.09 m | 42 | 0.83 | 0.08 | **0.14** |
| Bed | 13.5 cm | c2 (`bed` 100%) | 1.03 m | 42 | 1.00 | 0.04 | **0.08** |

**Reward = average of the 6 F@5% values = 0.105.**

## Secondary scorer (diagnostic)

Same steps, but the alignment keeps only the 0° starting turn (the agent builds in the task's own world frame; the prompt gives every camera pose in it). Turn applied: 32°, 6 clusters (eps 0.44 m).

| Item | Paired with | F@5% |
|---|---|---|
| TV_Stand | `bed` 69%, `tv` 21% | 0.27 |
| Side_Table | `chair` 41%, `sofa` 32% | 0.00 |
| Sofa | `sidetable` 100% | 0.12 |
| Desk_Chair | `desk` 100% | 0.01 |
| Desk | `bed` 100% | 0.14 |
| Bed | `bed` 100% | 0.08 |

**Secondary scorer = 0.105.**
