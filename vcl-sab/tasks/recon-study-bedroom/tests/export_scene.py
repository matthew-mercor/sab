"""Collect the agent's final Blender scene for scoring (stdlib only).

Writes two files from the same scene:
  - <out>.glb: meshes only, modifiers applied (renders and reports);
  - <out dir>/agent_verts.json: what the score uses. The official SceneActBench harness scores the
    world vertices of every mesh in the live Blender scene, at most 4,000 per mesh, read before
    modifiers (ob.data.vertices). This runs its READ_VERTS_CODE, taken verbatim from
    scorer/sab_official_metrics.py, inside Blender and saves the result.

Order: live headless Blender (socket) -> autosave .blend -> agent-saved scene.blend -> agent-saved
scene.glb (a GLB alone has no pre-modifier meshes; the verifier then reads the GLB's vertices).
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys

OUT = sys.argv[1]
PORT = int(os.environ.get("BLENDER_PORT", "9876"))
BLENDER = os.environ.get("BLENDER", "/opt/blender/blender")
EXPORT = (
    "import bpy\n"
    "bpy.ops.object.select_all(action='DESELECT')\n"
    "for o in bpy.data.objects: o.select_set(o.type=='MESH' and o.visible_get())\n"
    "n=sum(1 for o in bpy.context.selected_objects)\n"
    "print('MESHES', n)\n"
    "if n: bpy.ops.export_scene.gltf(filepath={out!r}, use_selection=True, export_format='GLB', export_apply=True)\n"
)


VERTS = os.path.join(os.path.dirname(OUT), "agent_verts.json")
_official = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scorer", "sab_official_metrics.py")).read()
READ_VERTS_CODE = re.search(r'READ_VERTS_CODE = r"""(.*?)"""', _official, re.S).group(1).format(sample=4000)
# Run the official reader in Blender and keep the JSON it prints between its markers.
DUMP_VERTS = (
    "import io, contextlib\n"
    "_buf = io.StringIO()\n"
    "with contextlib.redirect_stdout(_buf):\n"
    "    exec(" + repr(READ_VERTS_CODE) + ", {})\n"
    "_s = _buf.getvalue()\n"
    "open(" + repr(VERTS) + ", 'w').write(_s[_s.index('VERTS_JSON_BEGIN') + len('VERTS_JSON_BEGIN'):_s.index('VERTS_JSON_END')].strip())\n"
)


def code() -> str:
    return EXPORT.format(out=OUT) + DUMP_VERTS


def live():
    with socket.create_connection(("127.0.0.1", PORT), timeout=5) as s:
        s.settimeout(600)
        s.sendall(json.dumps({"type": "execute_code", "params": {"code": code()}}).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode())
            except json.JSONDecodeError:
                continue


def from_blend(path):
    script = "/tmp/_export_scene.py"
    open(script, "w").write(code())
    subprocess.run([BLENDER, "-b", path, "--python", script], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)


for stale in (OUT, VERTS):
    if os.path.exists(stale):
        os.remove(stale)
sources = [("live Blender", live),
           ("autosave", lambda: from_blend("/app/output/.autosave.blend") if os.path.exists("/app/output/.autosave.blend") else None),
           ("scene.blend", lambda: from_blend("/app/output/scene.blend") if os.path.exists("/app/output/scene.blend") else None),
           ("scene.glb", lambda: shutil.copy("/app/output/scene.glb", OUT) if os.path.exists("/app/output/scene.glb") else None)]
for name, fn in sources:
    try:
        fn()
    except Exception as e:
        print(f"[export] {name}: {e!r}")
        continue
    if os.path.exists(OUT) and os.path.getsize(OUT) > 0:
        print(f"[export] scene taken from: {name}; vertices: {'agent_verts.json' if os.path.exists(VERTS) else 'from the GLB'}")
        sys.exit(0)
print("[export] no scene found (no meshes in Blender and no saved scene)")
sys.exit(1)
