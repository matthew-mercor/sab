#!/usr/bin/env python3
"""Bring existing Reconstruction tasks up to the paper's scoring, in place.

    python tooling/upgrade_tasks.py                  # every tasks/recon-*
    python tooling/upgrade_tasks.py recon-den

For each task this:
  - copies the verifier (tests/test.sh, verify.py, export_scene.py) from tooling/harbor_template/;
  - replaces tests/scorer/ with the paper's scorer (sab_official_metrics.py, unchanged) and its
    entry point (paper_score.py);
  - rewrites instruction.md from the official SceneActBench prompt (make_harbor_task.build_prompt),
    which restores the paper's grading section;
  - sets task.toml's reward_metric, and prints the golden's score under the paper's scorer
    (the room's ceiling).
Images, answer key, oracle and the rest of task.toml are kept.
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scorer"))
import make_harbor_task as MHT  # noqa: E402
from make_sample import golden_check  # noqa: E402

TEMPLATE_TESTS = os.path.join(HERE, "harbor_template", "tests")


def upgrade(task: str) -> float:
    tests = os.path.join(task, "tests")
    for f in ("test.sh", "verify.py", "export_scene.py"):
        shutil.copy(os.path.join(TEMPLATE_TESTS, f), os.path.join(tests, f))
    os.chmod(os.path.join(tests, "test.sh"), 0o755)
    scorer = os.path.join(tests, "scorer")
    shutil.rmtree(scorer, ignore_errors=True)
    os.makedirs(scorer)
    for f in MHT.SCORER_FILES:
        shutil.copy(f, os.path.join(scorer, os.path.basename(f)))

    cameras = json.load(open(os.path.join(tests, "golden", "cameras.json")))
    with open(os.path.join(task, "instruction.md"), "w") as f:
        f.write(MHT.build_prompt(cameras))

    import paper_score as PS
    dropped = PS.check_answer_key(os.path.join(task, "solution", "golden_scene.glb"))
    if dropped:
        sys.exit(f"{os.path.basename(task)}: these items would not be graded: {dropped}. Rename them or add "
                 f"their type to EXTRA_FURNITURE_WORDS in tooling/scorer/paper_score.py")
    reward, per = golden_check(os.path.join(task, "solution", "golden_scene.glb"))
    toml_path = os.path.join(task, "task.toml")
    toml = open(toml_path).read()
    metric = re.search(r'^reward_metric = .*$', MHT.TASK_TOML, re.M).group(0)
    toml = re.sub(r'^reward_metric = .*$', lambda _: metric, toml, flags=re.M)
    open(toml_path, "w").write(toml)
    low = {k: v for k, v in per.items() if v < 0.95}
    print(f"{os.path.basename(task):<32s} golden (room ceiling) {reward:.3f}   items below 0.95: {low or '-'}")
    return reward


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="*", help="task folder names under tasks/ (default: all recon-*)")
    a = ap.parse_args()
    tasks = [os.path.join(ROOT, "tasks", t) for t in a.tasks] or sorted(glob.glob(os.path.join(ROOT, "tasks", "recon-*")))
    for t in tasks:
        upgrade(t)


if __name__ == "__main__":
    main()
