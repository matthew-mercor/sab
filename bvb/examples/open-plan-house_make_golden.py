"""Build the golden solution for bvb-open-plan-house: fixes to GLM 5.3 Flash's reconstruction (glm-run1).

The task's 11 questions check details that a guess or another room's video gets wrong. GLM's scene passes 6.
These fixes follow the source video:
  - Dining set: 1.2 m closer to the camera path (it never came into view) and 0.35 m back from the hall wall.
    The table gets two gold X-shaped trestle legs instead of two wooden slabs.
  - Camera: the same path, paced like the video (10 of the 16 judge frames before the hall), looking right at the
    start, then left over the dining area, then straight at the hallway; 20 mm lens.
  - Kitchen: the upper cabinets end lower, and a strip of six bright windows with black frames runs along
    the top of the right wall above them.
  - Living area: the sofa is rebuilt as a white 3-seat sofa facing the armchair (GLM's was a grey-blue row of blocks);
    the armchair's navy pillow is smaller and lighter; the rug is white with a blue grid.
  - Hall front wall: the abstract painting with yellow strokes moves to the wall left of the hallway opening,
    with a large black-framed window (trees outside) further left; the tall wood-framed mirror (wider frame, bright glass) moves
    to the pillar right of the opening. In the video the camera sees them in this order, left to right.
  - The sliding door near the start gets a black frame, as in the video.
Only primitives and single Principled BSDF materials with numeric values, as the task's rules require.
Applied with Blender 4.2:
  blender -b glm_open_plan_house.blend --python open-plan-house_make_golden.py -- "$PWD/golden.blend"
"""
import bpy, math, sys

out = sys.argv[sys.argv.index("--") + 1]
log = lambda *a: print("FIX", *a)
O = bpy.data.objects

def mat(name, rgb, rough=0.8, emit=0.0, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = emit
    return m

fixes = bpy.data.collections.new("golden_fixes"); bpy.context.scene.collection.children.link(fixes)

def link(o, m, name):
    o.name = name; o.data.materials.clear(); o.data.materials.append(m)
    for col in o.users_collection: col.objects.unlink(o)
    fixes.objects.link(o); return o

def box(name, lo, hi, m, rot=(0, 0, 0)):
    c = [(a + b) / 2 for a, b in zip(lo, hi)]; s = [(b - a) for a, b in zip(lo, hi)]
    bpy.ops.mesh.primitive_cube_add(size=1, location=c, rotation=rot)
    o = bpy.context.active_object; o.scale = s; return link(o, m, name)

def bar(name, p0, p1, w, m):
    """A square bar of width w from p0 to p1 (both in the x-z plane at the same y)."""
    dx, dz = p1[0] - p0[0], p1[2] - p0[2]; L = math.hypot(dx, dz)
    c = [(a + b) / 2 for a, b in zip(p0, p1)]
    bpy.ops.mesh.primitive_cube_add(size=1, location=c, rotation=(0, -math.atan2(dz, dx), 0))
    o = bpy.context.active_object; o.scale = (L, w, w); return link(o, m, name)

def delete(*names):
    for n in names:
        bpy.data.objects.remove(O[n], do_unlink=True)

# 1) Dining set: +1.2 m in x (towards the camera path), -0.35 m in y; the rug +0.7 m in x so it stays clear of
#    the living-room rug. The two wooden leg slabs and the beam become two gold X-shaped trestles and a stretcher.
din = [n for n in O.keys() if n.startswith(("Din", "Chair")) and n != "DiningRug"]
for n in din:
    O[n].location.x += 1.2; O[n].location.y -= 0.35
O["DiningRug"].location.x += 0.7; O["DiningRug"].location.y -= 0.35
delete("DinLegF", "DinLegB", "DinBeam")
gold = mat("gold_legs", (0.85, 0.62, 0.15), rough=0.35)   # metallic renders near black without reflections
x0, x1, top = -1.95, -1.05, 0.71          # table top now x -2.05..-0.95, y 3.60..5.70, underside z 0.71
for i, y in enumerate((3.85, 5.45)):
    bar(f"DinX{i}a", (x0, y, 0.0), (x1, y, top), 0.06, gold)
    bar(f"DinX{i}b", (x0, y, top), (x1, y, 0.0), 0.06, gold)
box("DinStretcher", (-1.52, 3.85, 0.34), (-1.48, 5.45, 0.38), gold)
log("dining set +1.2 m x, -0.35 m y:", len(din), "objects; gold X legs")

# 2) Camera: pace, heading and lens as in the source video. The source spends its first 10 of 16 judge frames in the
#    living and dining area and only then walks down the hall; GLM's camera walked at one speed. Each key keeps its
#    position, only its time moves. Heading: at the start the camera looks right (sofa at the right edge), then left
#    over the dining table to the window and the painting, then straight at the hallway opening (painting left,
#    mirror right). From the hall on, GLM's heading is kept. Lens 24 mm -> 20 mm (the source is a wide lens).
sc = bpy.context.scene; cam = sc.camera; act = cam.animation_data.action
fs, fe = sc.frame_start, sc.frame_end
at = lambda i: fs + i * (fe - fs) / 15.0          # frame of judge frame i (0..15)
pace = [(0.0, 0), (0.9, 3), (1.5, 6), (2.1, 9), (3.5, 10), (5.5, 11), (7.0, 12), (8.5, 13), (9.6, 14), (10.5, 15)]
def when(y):
    for (y0, i0), (y1, i1) in zip(pace, pace[1:]):
        if y <= y1: return at(i0 + (i1 - i0) * max(0.0, y - y0) / (y1 - y0))
    return at(15)
fy = act.fcurves.find("location", index=1)
remap = {round(k.co[0]): when(k.co[1]) for k in fy.keyframe_points}
remap[min(remap)], remap[max(remap)] = fs, fe
for fc in act.fcurves:
    if fc.data_path in ("location", "rotation_euler"):
        for k in fc.keyframe_points:
            k.co[0] = remap[round(k.co[0])]
        fc.update()
yaw = act.fcurves.find("rotation_euler", index=2)
hall = at(9.5)
while any(k.co[0] < hall for k in yaw.keyframe_points):    # remove one at a time: removal shifts the others
    yaw.keyframe_points.remove(next(k for k in yaw.keyframe_points if k.co[0] < hall))
for i, v in ((0, -0.45), (1, -0.45), (2.5, 0.25), (5, 0.25), (6.3, 0.0), (9, 0.0)):
    yaw.keyframe_points.insert(at(i), v)
for fc in act.fcurves:
    if fc.data_path in ("location", "rotation_euler"):
        for k in fc.keyframe_points:
            k.interpolation = 'BEZIER'; k.handle_left_type = k.handle_right_type = 'AUTO_CLAMPED'
        fc.update()
cam.data.lens = 20.0
log("camera retimed (first 10 judge frames in the living/dining area), heading right then left then ahead, lens 20 mm")

# 3) Kitchen: upper cabinets end at z 2.30; six bright windows with black frames above them (z 2.36-2.92).
up = O["KitUpper"]; up.location.z = (1.85 + 2.30) / 2; up.scale.z = 2.30 - 1.85
delete("KitWinFrame0", "KitWinFrame1", "KitWinFrame2", "KitWinPane0", "KitWinPane1", "KitWinPane2")
sky = mat("clerestory_sky", (0.55, 0.75, 1.0), rough=0.2, emit=2.0)
blk = mat("black_frame", (0.02, 0.02, 0.02), rough=0.5)
y0, w, gap, n, z0, z1 = 1.40, 0.70, 0.06, 6, 2.36, 2.92
end = y0 + n * w + (n - 1) * gap
for i in range(n):
    a = y0 + i * (w + gap)
    box(f"ClerestoryPane{i}", (3.875, a, z0), (3.895, a + w, z1), sky)
box("ClerestoryFrameB", (3.85, y0 - 0.05, z0 - 0.05), (3.90, end + 0.05, z0), blk)
box("ClerestoryFrameT", (3.85, y0 - 0.05, z1), (3.90, end + 0.05, z1 + 0.05), blk)
box("ClerestoryMull0", (3.85, y0 - 0.05, z0), (3.90, y0, z1), blk)
box(f"ClerestoryMull{n}", (3.85, end, z0), (3.90, end + 0.05, z1), blk)
for i in range(1, n):
    a = y0 + i * w + (i - 1) * gap
    box(f"ClerestoryMull{i}", (3.85, a, z0), (3.90, a + gap, z1), blk)
log(f"upper cabinets end at 2.30; {n} windows y {y0:.2f}-{end:.2f}, z {z0}-{z1}")

# 4) Living area: white sofa; white rug with a blue grid of thin lines.
white = mat("sofa_white", (0.90, 0.90, 0.88), rough=0.9)
#    GLM's sofa was a row of blocks along x with its back in the middle; rebuild it as a 3-seat sofa along the right
#    side of the living area, facing the armchair (-x), as in the video.
delete(*[n for n in list(O.keys()) if n.startswith("Sofa")])
box("SofaBase", (2.55, 0.55, 0.08), (3.45, 3.00, 0.42), white)
box("SofaBack", (3.20, 0.55, 0.42), (3.45, 3.00, 0.88), white)
box("SofaArmS", (2.55, 0.40, 0.08), (3.45, 0.55, 0.62), white)
box("SofaArmN", (2.55, 3.00, 0.08), (3.45, 3.15, 0.62), white)
box("SofaCush1", (2.58, 0.57, 0.42), (3.18, 1.76, 0.52), white)
box("SofaCush2", (2.58, 1.79, 0.42), (3.18, 2.98, 0.52), white)
pil = mat("sofa_pillow", (0.86, 0.88, 0.93), rough=0.9)
box("SofaPil1", (3.02, 2.55, 0.50), (3.18, 2.95, 0.88), pil)
legs = bpy.data.materials["wood_m"]
for i, (x, y) in enumerate(((2.58, 0.43), (3.38, 0.43), (2.58, 3.08), (3.38, 3.08))):
    box(f"SofaLeg{i}", (x - 0.03, y - 0.03, 0.0), (x + 0.03, y + 0.03, 0.08), legs)
#    The armchair's pillow: smaller and a lighter blue (it filled the whole chair back in navy).
ap = O["ArmPillow"]; ap.scale.y *= 0.40 / 0.60; ap.scale.z *= 0.32 / 0.44; ap.location.z -= 0.04
ap.data.materials.clear(); ap.data.materials.append(mat("arm_pillow", (0.35, 0.50, 0.85), rough=0.8))
rugw = mat("rug_white", (0.92, 0.92, 0.90), rough=0.95)
blue = mat("rug_blue_lines", (0.10, 0.25, 0.65), rough=0.95)
r = O["LivingRug"]; r.data.materials.clear(); r.data.materials.append(rugw)
rx0, rx1, ry0, ry1 = 0.0, 3.4, 1.25, 3.75
k = 0; x = rx0 + 0.20
while x < rx1 - 0.1:
    box(f"RugLineX{k}", (x - 0.012, ry0 + 0.05, 0.001), (x + 0.012, ry1 - 0.05, 0.005), blue); x += 0.30; k += 1
k = 0; y = ry0 + 0.20
while y < ry1 - 0.1:
    box(f"RugLineY{k}", (rx0 + 0.05, y - 0.012, 0.001), (rx1 - 0.05, y + 0.012, 0.005), blue); y += 0.30; k += 1
log("sofa rebuilt in white facing the armchair; smaller, lighter armchair pillow; rug -> white with a blue grid")

# 5) Hall front wall (y 6.01, facing the camera): window | painting | opening | mirror, left to right.
delete("PaintCanvas", "PaintFrame", "PaintStripe1", "PaintStripe2", "PaintStripe3", "PaintStripe4",
       "MirrorRFrame", "MirrorRGlass")
canvas = bpy.data.materials["canvas"]
box("PaintFrame", (-2.85, 5.97, 1.05), (-1.95, 6.01, 1.95), O["ArtFrame"].data.materials[0])
box("PaintCanvas", (-2.81, 5.96, 1.09), (-1.99, 5.97, 1.91), canvas)
for i, (za, zb, mn) in enumerate(((1.62, 1.74, "art_dk"), (1.50, 1.60, "art_gy"), (1.40, 1.48, "art_yl"),
                                  (1.28, 1.38, "art_dk"), (1.18, 1.24, "art_yl"))):
    box(f"PaintStripe{i + 1}", (-2.77, 5.955, za), (-2.03, 5.96, zb), bpy.data.materials[mn])
box("HallWinFrame", (-3.95, 5.97, 0.45), (-3.05, 6.01, 2.45), blk)
box("HallWinPane", (-3.90, 5.96, 0.50), (-3.10, 5.97, 2.40), sky)
green = mat("trees_outside", (0.10, 0.28, 0.10), rough=0.9)
for i, (x, z, rr) in enumerate(((-3.70, 1.05, 0.30), (-3.35, 1.20, 0.32), (-3.55, 1.55, 0.28))):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=rr, location=(x, 5.955, z))
    o = bpy.context.active_object; o.scale = (1, 0.02, 1); link(o, green, f"HallWinTree{i}")
wood = bpy.data.materials["wood_l"]; mirror = bpy.data.materials["mirror"]
box("MirrorRFrame", (2.25, 5.97, 0.40), (3.15, 6.01, 2.30), wood)
# The glass shows a bright reflection (a metallic mirror renders near black against the plain world).
box("MirrorRGlass", (2.36, 5.96, 0.51), (3.04, 5.97, 2.19), mat("mirror_bright", (0.80, 0.85, 0.90), rough=0.1, emit=0.35))
log("painting on the wall left of the opening, black-framed window further left, mirror on the right pillar")

# 6) Sliding door near the start: black frame.
O["GlassDoorFrame"].data.materials.clear(); O["GlassDoorFrame"].data.materials.append(blk)

bpy.ops.wm.save_as_mainfile(filepath=out)
log("saved", out)
