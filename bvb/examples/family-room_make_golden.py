"""Build the golden solution for bvb-family-room: fixes to GLM 5.3 Flash's reconstruction (glm-run1).

The judge lost 2 of 15 questions on GLM's scene:
  920007 (white curtains on the right windows): the curtains had the wall's off-white colour and read as "nothing".
  920009 (sofa colour gray): the sofa was tan and read as "white".
GLM's camera also drifted 1.6 m left and turned 12 degrees left, so the right-wall windows left the frame;
the video's camera stays near one spot and slowly pushes forward with the curtains in view on the right.
Applied with Blender 4.2:
  blender -b glm_family_room.blend --python family-room_make_golden.py -- "$PWD/golden.blend"
"""
import bpy, sys

out = sys.argv[sys.argv.index("--") + 1]
log = lambda *a: print("FIX", *a)

def mat(name, rgb, rough=0.8, emit=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = emit
    return m

fixes = bpy.data.collections.new("golden_fixes"); bpy.context.scene.collection.children.link(fixes)

def cyl(name, r, h, loc, m):
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=r, depth=h, location=loc)
    o = bpy.context.active_object; o.name = name; o.data.materials.append(m)
    for c in o.users_collection: c.objects.unlink(o)
    fixes.objects.link(o); bpy.ops.object.shade_smooth(); return o

# 1) Sofa: tan -> medium gray (the video's sofa is gray microfiber).
sofa = bpy.data.materials["sofa_tan"].node_tree.nodes["Principled BSDF"]
sofa.inputs["Base Color"].default_value = (0.20, 0.19, 0.20, 1)
log("sofa colour -> gray")

# 2) Curtains: floor-length white folds across the right-wall windows, in front of a tan wall
#    (the video shows white curtains against the yellow wall). The old off-white panels go.
for n in ("curt_L", "curt_R", "sheer"):
    bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
white = mat("curtain_white", (0.95, 0.95, 0.95), rough=0.9, emit=0.12)
y = 0.45
while y <= 3.36:
    cyl(f"curtain_fold_{y:.2f}", 0.065, 2.5, (2.68, y, 1.30), white)
    y += 0.12
tan = bpy.data.materials["tan_wall"]
for n in ("wall_right_a", "wall_right_b", "wall_right_c", "wall_right_d"):
    o = bpy.data.objects[n]; o.data.materials.clear(); o.data.materials.append(tan)
log("curtains -> white folds; right wall -> tan")

# 3) Camera: near one spot, a slow push forward, the right-wall curtains in view (as in the video).
import math
cam = bpy.context.scene.camera
cam.animation_data_clear()
fs, fe = bpy.context.scene.frame_start, bpy.context.scene.frame_end
for f, loc, rot in ((fs, (1.60, -3.00, 1.55), (83.0, 0.0, 24.0)), (fe, (1.35, -2.30, 1.52), (82.0, 0.0, 26.0))):
    cam.location = loc; cam.rotation_euler = tuple(math.radians(a) for a in rot)
    cam.keyframe_insert("location", frame=f); cam.keyframe_insert("rotation_euler", frame=f)
log("camera -> slow push from (1.60, -3.00) to (1.35, -2.30), yaw 24 -> 26 deg")

bpy.ops.wm.save_as_mainfile(filepath=out)
log("saved", out)
