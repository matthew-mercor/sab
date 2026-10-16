#!/usr/bin/env python3
"""Copy a (local) task for a GLM feedback round: add the model's previous scene as
environment/input/previous_scene.glb (-> /app/input/previous_scene.glb) and append a feedback
section (read from a markdown file) to instruction.md.

  python tooling/make_feedback_task.py <task_dir> <previous_scene.glb> <feedback.md> <out_dir>
"""
import shutil, sys
from pathlib import Path
src, glb, fb, dst = map(Path, sys.argv[1:5])
if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst)
shutil.copy(glb, dst / "environment" / "input" / "previous_scene.glb")
ins = dst / "instruction.md"
ins.write_text(ins.read_text().rstrip() + "\n\n---\n\n" + fb.read_text().strip() + "\n")
print(dst)
