# How this score was produced: kimi-k3-rollout3

Task `recon-study-bedroom`. **Reward 0.000** (the paper's F@5%). Secondary scorer 0.000 (diagnostic, not the reward).

Every number below was recomputed with the official functions in `tests/scorer/sab_official_metrics.py` and the same random seeds, and checked against `score.json`.

## 1. Points read from the scene

`tests/export_scene.py` reads every mesh's world-space vertices in Blender, at most 4,000 per mesh (the official `READ_VERTS_CODE`): **1 meshes, 8 vertices** (`agent_verts.json`). The answer key (`tests/golden/scene/*_full.glb`, converted to Z-up) has 6 items and 660,162 vertices.

## 2. Whole-scene alignment (fixed-scale ICP)

`icp_sim3` samples 8 of the scene's points and 4,000 of the answer key's, scales the scene by the ratio of the two bounding-box diagonals (**×1.68**), then tries four starting turns (0/90/180/270°) and keeps the best fit. Result: the scene was turned **-4°**.

## 3. Splitting the scene into objects (DBSCAN)

Average answer-key item size 1.78 m. The scorer tries grouping distances (eps) from 0.10 to 0.40 × that and keeps the one whose cluster count is closest to 6 (clusters under 30 points are discarded):

| eps ratio | eps | clusters |
|---|---|---|
| 0.10 | 0.18 m | 0 ← chosen |
| 0.15 | 0.27 m | 0 |
| 0.20 | 0.36 m | 0 |
| 0.25 | 0.44 m | 0 |
| 0.30 | 0.53 m | 0 |
| 0.40 | 0.71 m | 0 |

0 clusters kept; 8 points left as noise.

| Cluster | Points | Made of the agent's meshes |
|---|---|---|

## 4. Pairing clusters with answer-key items (Hungarian matching)

Each item is paired with one cluster by centre distance; pairs farther than 0.6 × the scene diagonal (3.49 m) are rejected, and an unpaired item scores 0.

## 5. Shape score per item (F@5%)

The paired cluster is moved onto the item's centre (placement is not scored). Precision = share of the cluster's points within the tolerance of the item's surface points; recall = share of the item's points within the tolerance of the cluster; F = their harmonic mean. Tolerance = 5% of the item's bounding-box diagonal.

| Item | Tolerance | Paired with | Centre distance | Points | Precision | Recall | F@5% |
|---|---|---|---|---|---|---|---|
| TV_Stand | 9.5 cm | nothing | — | — | — | — | **0.00** |
| Side_Table | 4.4 cm | nothing | — | — | — | — | **0.00** |
| Sofa | 10.1 cm | nothing | — | — | — | — | **0.00** |
| Desk_Chair | 6.0 cm | nothing | — | — | — | — | **0.00** |
| Desk | 9.8 cm | nothing | — | — | — | — | **0.00** |
| Bed | 13.5 cm | nothing | — | — | — | — | **0.00** |

**Reward = average of the 6 F@5% values = 0.000.**

## Secondary scorer (diagnostic)

Same steps, but the alignment keeps only the 0° starting turn (the agent builds in the task's own world frame; the prompt gives every camera pose in it). Turn applied: -4°, 0 clusters (eps 0.18 m).

| Item | Paired with | F@5% |
|---|---|---|
| TV_Stand | nothing | 0.00 |
| Side_Table | nothing | 0.00 |
| Sofa | nothing | 0.00 |
| Desk_Chair | nothing | 0.00 |
| Desk | nothing | 0.00 |
| Bed | nothing | 0.00 |

**Secondary scorer = 0.000.**
