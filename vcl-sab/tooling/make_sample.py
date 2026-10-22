"""Make a SceneActBench Reconstruction sample (and its Harbor task) from a .blend + scene.json.

  # 1. see what's in your .blend (to write the "items" section of scene.json)
  python tooling/make_sample.py --list samples/my-room/my_room.blend

  # 2. build the sample: golden solution, reference renders, Harbor task, golden check
  python tooling/make_sample.py samples/my-room/scene.json

  # rebuild every sample in samples/
  python tooling/make_sample.py --all

Needs Blender installed locally (set BLENDER=/path/to/blender if it isn't found).
See README.md ("Making a sample") for the scene.json format.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tooling"))
sys.path.insert(0, os.path.join(ROOT, "tooling", "scorer"))

BUILD = os.path.join(ROOT, "tooling", "blender", "build_scene.py")
LIST = os.path.join(ROOT, "tooling", "blender", "list_objects.py")
# A perfect copy does not always reach 1.0 under the paper's scorer: its DBSCAN step can drop items
# with few vertices and merge items that touch. The golden's score is the room's ceiling; below this
# value the sample is still built, with a warning (space the items apart, even out vertex counts).
MIN_GOLDEN = 0.9


def blender_bin():
    for c in (os.environ.get("BLENDER"), shutil.which("blender"),
              "/Applications/Blender.app/Contents/MacOS/Blender"):
        if c and os.path.exists(c):
            return c
    sys.exit("Blender not found. Install Blender 4.2+ or set BLENDER=/path/to/blender")


def list_objects(blend):
    r = subprocess.run([blender_bin(), "-b", blend, "--python", LIST], capture_output=True, text=True)
    out = r.stdout
    if "SCENEACTBENCH_LIST_BEGIN" not in out:
        sys.exit(f"could not read {blend}:\n{r.stderr[-2000:]}")
    print(out.split("SCENEACTBENCH_LIST_BEGIN\n", 1)[1].split("SCENEACTBENCH_LIST_END")[0])


def preview(renders, path):
    from PIL import Image
    ims = []
    for r in renders:
        im = Image.open(r).convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        ims.append(Image.alpha_composite(bg, im).convert("RGB").resize((512, 512)))
    canvas = Image.new("RGB", (512 * len(ims) + 10 * (len(ims) - 1), 512), (200, 200, 200))
    for i, im in enumerate(ims):
        canvas.paste(im, (i * 522, 0))
    canvas.save(path)


def golden_check(golden_glb):
    """The golden scored against itself with the paper's scorer (the room's ceiling)."""
    import tempfile
    import paper_score as PS
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "scene"))
        shutil.copy(golden_glb, os.path.join(d, "scene", "golden_full.glb"))
        Q, parts = PS.load_answer_key(d)
    sc = PS.score(PS.load_agent_vertices(None, golden_glb), Q, parts)
    return sc["obj_f@5%_matched"], {p["part"]: round(p["f@5%_matched"], 3) for p in sc["per_object_matched"]}


def make(scene_json):
    from make_harbor_task import build_task
    sample_dir = os.path.dirname(os.path.abspath(scene_json))
    cfg = json.load(open(scene_json))
    name = cfg["name"]
    title = cfg.get("title", name.replace("-", " ").capitalize())
    blend = os.path.join(sample_dir, cfg["source"])
    if not os.path.isfile(blend):
        sys.exit(f"source .blend not found: {blend}")
    build = os.path.join(sample_dir, "build")
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build)

    print(f"[{name}] building golden solution + reference views in Blender ...")
    r = subprocess.run([blender_bin(), "-b", blend, "--python", BUILD, "--", os.path.abspath(scene_json), build],
                       capture_output=True, text=True)
    rep_path = os.path.join(build, "report.json")
    if not os.path.isfile(rep_path):
        sys.exit(f"[{name}] Blender build failed:\n{(r.stdout + r.stderr)[-3000:]}")
    rep = json.load(open(rep_path))
    for w in rep["warnings"]:
        print(f"  warning: {w}")
    if not rep["ok"]:
        print(f"[{name}] FAILED - fix scene.json and run again:")
        for p in rep["problems"]:
            print(f"  - {p}")
        sys.exit(1)
    print(f"  {len(rep['items'])} items, room span {rep['room_span_m']} m")
    for item, info in rep["items"].items():
        print(f"    {item:<16} {info['objects']:>3} objects  size {info['size_m']} m  "
              f"visible per view {info['visible_fraction_per_view']}")

    golden = os.path.join(build, "golden.glb")
    import paper_score as PS
    dropped = PS.check_answer_key(golden)
    if dropped:
        sys.exit(f"[{name}] these items would not be graded: {dropped}. Rename them so the name contains "
                 f"a furniture word, or add their type to EXTRA_FURNITURE_WORDS in tooling/scorer/paper_score.py")
    reward, per = golden_check(golden)
    print(f"  golden check (the paper's scorer, golden vs itself): {reward:.3f}")
    if reward < MIN_GOLDEN:
        print(f"[{name}] WARNING: golden scores {reward:.3f} < {MIN_GOLDEN}; per item: {per}\n"
              "  items that touch get merged and items with few vertices get dropped by the scorer's\n"
              "  clustering: space the items apart and give each a similar, even vertex density")

    renders = sorted(glob.glob(os.path.join(build, "render_*.png")))
    preview(renders, os.path.join(build, "preview.png"))
    task_name = f"recon-{name}"
    task = build_task(task_name=task_name, title=title, golden_glb=golden,
                      golden_file=cfg.get("golden_file", f"{name}_full.glb"), renders=renders,
                      cameras_json=os.path.join(build, "cameras.json"), source_blend=blend,
                      item_names=list(rep["items"]),
                      blender_version=cfg.get("blender_version"))
    print(f"[{name}] OK -> {os.path.relpath(task, ROOT)}")
    print(f"  check the views:  {os.path.relpath(os.path.join(build, 'preview.png'), ROOT)}")
    print(f"  then validate:    harbor run -p {os.path.relpath(task, ROOT)} -a oracle   (expect ~{reward:.2f})")
    print(f"                    harbor run -p {os.path.relpath(task, ROOT)} -a nop      (expect 0.0)")
    return task


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene_json", nargs="?", help="samples/<name>/scene.json")
    ap.add_argument("--list", metavar="BLEND", help="list the objects in a .blend and exit")
    ap.add_argument("--all", action="store_true", help="rebuild every samples/*/scene.json")
    a = ap.parse_args()
    if a.list:
        list_objects(a.list)
    elif a.all:
        for s in sorted(glob.glob(os.path.join(ROOT, "samples", "*", "scene.json"))):
            make(s)
    elif a.scene_json:
        make(a.scene_json)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
