#!/bin/bash
# SceneActBench Reconstruction verifier: export the agent's final Blender scene (a GLB, plus its mesh
# vertices as the official harness reads them), score it with the paper's scorer, write the reward.
mkdir -p /logs/verifier /app/output
python3 /tests/export_scene.py /app/output/agent_scene.glb 2>&1 | tee /logs/verifier/export.log
/opt/sceneactbench/venv/bin/python /tests/verify.py \
    --golden /tests/golden \
    --pred /app/output/agent_scene.glb \
    --verts /app/output/agent_verts.json \
    --reward /logs/verifier/reward.txt \
    --details /logs/verifier/score.json
cp -f /app/output/agent_scene.glb /logs/verifier/agent_scene.glb 2>/dev/null || true
cp -f /app/output/agent_verts.json /logs/verifier/agent_verts.json 2>/dev/null || true
