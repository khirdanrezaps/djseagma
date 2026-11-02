"""
Build the "videotron" logo animation for DJ Seagma 2026.blend.

Recreates the look of the reference (REFERENSI VIDEO FOR DJ SEAGMA.mp4):
  0-4s    fade in on a close-up of the cloud-covered gate surface
  4-17s   camera pulls back, revealing the seam between two cloud gates;
          light tubes start flickering through the seam
  17-28s  the gates slide open while the camera keeps dollying back,
          revealing the chrome logo letter by letter
  28-45s  wide hold: logo between the pillars, hanging-cloud back wall,
          thin wires, cloud floor, light tubes strobing on the beat

Usage
  Inside Blender: open DJ Seagma 2026.blend, Scripting tab, open this file, Run Script.
  Headless:       blender -b "DJ Seagma 2026.blend" -P scripts/build_logo_anim.py -- --save
Re-running is safe: everything it creates lives in the "SEAGMA_ANIM" collection
and is rebuilt from scratch each time. The logo mesh itself is left untouched.
"""
import math
import random
import sys

import bpy

FPS = 24
FRAME_END = 1080           # 45 s
BPM = 150
COLL_NAME = "SEAGMA_ANIM"
LOGO_NAME = "memories.001"
LOGO_EMPTY = "logo"

# Timeline (frames)
F_FADE_END = 96            # 4 s
F_PULL_END = 408           # 17 s
F_TUBES_START = 300        # 12.5 s
F_GATE_OPEN_START = 420    # 17.5 s
F_GATE_OPEN_END = 660      # 27.5 s
F_HOLD = 672               # 28 s

rng = random.Random(2026)


# --------------------------------------------------------------------------- helpers
def get_collection():
    coll = bpy.data.collections.get(COLL_NAME)
    if coll:
        for ob in list(coll.objects):
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
    else:
        coll = bpy.data.collections.new(COLL_NAME)
        bpy.context.scene.collection.children.link(coll)
    return coll


def link(ob, coll):
    coll.objects.link(ob)
    return ob


def box_mesh(name, sx, sy, sz):
    """Axis-aligned box centred on origin with full sizes sx, sy, sz."""
    me = bpy.data.meshes.new(name)
    x, y, z = sx / 2, sy / 2, sz / 2
    v = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
         (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    f = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (3, 2, 1, 0), (4, 5, 6, 7)]
    me.from_pydata(v, [], f)
    me.update()
    return me


def plane_mesh(name, sx, sz, facing_neg_y=True):
    """Vertical plane in XZ, normal pointing to -Y (towards camera)."""
    me = bpy.data.meshes.new(name)
    x, z = sx / 2, sz / 2
    v = [(-x, 0, -z), (x, 0, -z), (x, 0, z), (-x, 0, z)]
    me.from_pydata(v, [], [(0, 1, 2, 3)] if facing_neg_y else [(3, 2, 1, 0)])
    me.update()
    return me


def floor_mesh(name, sx, sy):
    me = bpy.data.meshes.new(name)
    x, y = sx / 2, sy / 2
    me.from_pydata([(-x, -y, 0), (x, -y, 0), (x, y, 0), (-x, y, 0)], [], [(0, 1, 2, 3)])
    me.update()
    return me


def cylinder_mesh(name, radius, height, segs=12):
    me = bpy.data.meshes.new(name)
    verts, faces = [], []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        verts.append((radius * math.cos(a), radius * math.sin(a), -height / 2))
        verts.append((radius * math.cos(a), radius * math.sin(a), height / 2))
    for i in range(segs):
        j = (i + 1) % segs
        faces.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
    me.from_pydata(verts, [], faces)
    for p in me.polygons:
        p.use_smooth = True
    me.update()
    return me


def ensure_material(name):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    return mat, nt


def set_inputs(node, **vals):
    for k, v in vals.items():
        node.inputs[k.replace("_", " ")].default_value = v


# --------------------------------------------------------------------------- materials
def mat_wire():
    mat, nt = ensure_material("SEAGMA_Wire")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_inputs(bsdf, Base_Color=(0.35, 0.35, 0.35, 1), Roughness=0.4, Metallic=1.0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def mat_tube():
    """Emission driven by the per-object custom property ["glow"]."""
    mat, nt = ensure_material("SEAGMA_LightTube")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "OBJECT"
    attr.attribute_name = '["glow"]'
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_inputs(bsdf, Base_Color=(0.03, 0.03, 0.03, 1), Roughness=0.3)
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.97, 0.93, 1)
    nt.links.new(attr.outputs["Fac"], bsdf.inputs["Emission Strength"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def upgrade_logo_chrome():
    """Brushed-chrome look from the reference: bright metal, slightly rough, smudges."""
    mat = bpy.data.materials.get("Logo_Chrome")
    if mat is None:
        return
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_inputs(bsdf, Base_Color=(0.85, 0.85, 0.86, 1), Metallic=1.0)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 8.0
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = 0.06
    ramp.inputs["To Max"].default_value = 0.22
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], bsdf.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.05
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


# --------------------------------------------------------------------------- volumetric clouds
def mat_cloud_volume(name, edge_axes, edge_weight, noise_scale, threshold, density,
                     flow, morph, seed, softness=0.05):
    """Dense, constantly moving cloud/smoke inside the object's box.

    density = smoothstep(noise4D(pos + flow*t, W=morph*t) - edge * edge_weight)
    edge_axes picks which generated-coordinate axes fade the cloud towards the box
    faces: "XY" for pillars, "Y" for the back wall, "Z+" (top fade) for the floor.
    """
    mat, nt = ensure_material(name)
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial")
    vol = N.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.78, 0.78, 0.80, 1)
    vol.inputs["Anisotropy"].default_value = 0.35
    L.new(vol.outputs["Volume"], out.inputs["Volume"])

    tc = N.new("ShaderNodeTexCoord")
    mapping = N.new("ShaderNodeMapping")
    L.new(tc.outputs["Object"], mapping.inputs["Vector"])
    noise = N.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "4D"
    noise.inputs["Scale"].default_value = noise_scale
    noise.inputs["Detail"].default_value = 7.0
    noise.inputs["Roughness"].default_value = 0.58
    noise.inputs["Distortion"].default_value = 0.25
    L.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    # flow + morph over the whole shot (linear keys)
    mapping.inputs["Location"].default_value = (seed * 1.7, seed * 0.9, 0.0)
    noise.inputs["W"].default_value = seed
    mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
    noise.inputs["W"].keyframe_insert("default_value", frame=1)
    secs = (FRAME_END - 1) / FPS
    mapping.inputs["Location"].default_value = (seed * 1.7 + flow[0] * secs, seed * 0.9 + flow[1] * secs,
                                                flow[2] * secs)
    noise.inputs["W"].default_value = seed + morph * secs
    mapping.inputs["Location"].keyframe_insert("default_value", frame=FRAME_END)
    noise.inputs["W"].keyframe_insert("default_value", frame=FRAME_END)

    # edge falloff from generated coordinates
    sep = N.new("ShaderNodeSeparateXYZ")
    if edge_axes == "Z+":
        L.new(tc.outputs["Generated"], sep.inputs[0])
        edge_out = sep.outputs["Z"]
    else:
        centred = N.new("ShaderNodeVectorMath")
        centred.operation = "SUBTRACT"
        centred.inputs[1].default_value = (0.5, 0.5, 0.5)
        L.new(tc.outputs["Generated"], centred.inputs[0])
        absn = N.new("ShaderNodeVectorMath")
        absn.operation = "ABSOLUTE"
        L.new(centred.outputs["Vector"], absn.inputs[0])
        dbl = N.new("ShaderNodeVectorMath")
        dbl.operation = "SCALE"
        dbl.inputs["Scale"].default_value = 2.0
        L.new(absn.outputs["Vector"], dbl.inputs[0])
        L.new(dbl.outputs["Vector"], sep.inputs[0])
        if edge_axes == "XY":
            mx = N.new("ShaderNodeMath")
            mx.operation = "MAXIMUM"
            L.new(sep.outputs["X"], mx.inputs[0])
            L.new(sep.outputs["Y"], mx.inputs[1])
            edge_out = mx.outputs[0]
        else:
            edge_out = sep.outputs[edge_axes]
    # edge^2 keeps the core solid and only erodes near the faces
    sq = N.new("ShaderNodeMath")
    sq.operation = "POWER"
    sq.inputs[1].default_value = 2.0
    L.new(edge_out, sq.inputs[0])
    w = N.new("ShaderNodeMath")
    w.operation = "MULTIPLY"
    w.inputs[1].default_value = edge_weight
    L.new(sq.outputs[0], w.inputs[0])
    field = N.new("ShaderNodeMath")
    field.operation = "SUBTRACT"
    L.new(noise.outputs["Fac"], field.inputs[0])
    L.new(w.outputs[0], field.inputs[1])

    step = N.new("ShaderNodeMapRange")
    step.interpolation_type = "SMOOTHSTEP"
    step.inputs["From Min"].default_value = threshold - softness
    step.inputs["From Max"].default_value = threshold + softness
    L.new(field.outputs[0], step.inputs["Value"])
    dens = N.new("ShaderNodeMath")
    dens.operation = "MULTIPLY"
    dens.inputs[1].default_value = density
    L.new(step.outputs["Result"], dens.inputs[0])
    L.new(dens.outputs[0], vol.inputs["Density"])
    return mat


def cloud_box(coll, name, size, loc, mat):
    ob = link(bpy.data.objects.new(name, box_mesh(name, *size)), coll)
    ob.data.materials.append(mat)
    ob.location = loc
    ob.visible_shadow = True
    return ob


# --------------------------------------------------------------------------- build
def build():
    scene = bpy.context.scene
    coll = get_collection()

    m_wire, m_tube = mat_wire(), mat_tube()
    # gates/pillars: billowing sideways + upward; wall: slow drift; floor: rolling smoke
    m_gate = mat_cloud_volume("SEAGMA_CloudGate", "XY", 0.5, 0.30, 0.40, 45.0,
                              flow=(0.10, 0.0, 0.18), morph=0.10, seed=3)
    m_pillar = mat_cloud_volume("SEAGMA_CloudPillar", "XY", 0.5, 0.30, 0.40, 45.0,
                                flow=(-0.08, 0.0, 0.15), morph=0.10, seed=7)
    m_wall = mat_cloud_volume("SEAGMA_CloudWall", "Y", 0.8, 0.18, 0.44, 35.0,
                              flow=(0.06, 0.0, -0.10), morph=0.08, seed=11)
    m_floor = mat_cloud_volume("SEAGMA_CloudFloor", "Z+", 0.9, 0.28, 0.30, 14.0,
                               flow=(0.25, -0.05, 0.0), morph=0.12, seed=17, softness=0.08)
    upgrade_logo_chrome()

    # Logo stays where it is (centre ~x-0.26, y-1, z0.21, 10.6 m wide). Make it static.
    for name in (LOGO_EMPTY, LOGO_NAME):
        ob = bpy.data.objects.get(name)
        if ob and ob.animation_data:
            ob.animation_data_clear()
    if LOGO_EMPTY in bpy.data.objects:
        bpy.data.objects[LOGO_EMPTY].rotation_euler = (0, 0, 0)

    FLOOR_Z = -4.0

    # Cloud gates (front pillars that slide open)
    gate_w, gate_d, gate_h = 7.6, 3.0, 18.0
    gate_z = FLOOR_Z + gate_h / 2
    for side, sign in (("L", -1), ("R", 1)):
        ob = cloud_box(coll, f"Gate_{side}", (gate_w, gate_d, gate_h), (0, -4.5, gate_z), m_gate)
        closed_x = sign * (gate_w / 2 - 0.8)      # volumes overlap a bit -> soft seam
        open_x = sign * (6.0 + gate_w / 2)
        ob.location.x = closed_x
        ob.keyframe_insert("location", index=0, frame=1)
        ob.keyframe_insert("location", index=0, frame=F_GATE_OPEN_START)
        ob.location.x = open_x
        ob.keyframe_insert("location", index=0, frame=F_GATE_OPEN_END)

    # Fixed side pillars further out (seen in the wide shot)
    for i, (x, y) in enumerate([(-15.0, -2.0), (15.0, -2.0), (-12.0, 3.5), (12.0, 3.5)]):
        cloud_box(coll, f"Pillar_{i}", (4.5, 3.0, gate_h), (x, y, gate_z), m_pillar)

    # Back wall of cloud and rolling smoke floor
    cloud_box(coll, "BackWall", (46.0, 4.0, 22.0), (0, 8.5, FLOOR_Z + 11.0), m_wall)
    cloud_box(coll, "CloudFloor", (46.0, 26.0, 3.2), (0, 0.5, FLOOR_Z + 0.6), m_floor)

    # Thin wires hanging behind the logo
    wire_me = cylinder_mesh("Wire", 0.008, 22.0, 6)
    for i in range(9):
        ob = link(bpy.data.objects.new(f"Wire_{i:02d}", wire_me), coll)
        ob.location = (rng.uniform(-9, 9), rng.uniform(1.0, 6.5), FLOOR_Z + 11.0)
    wire_me.materials.append(m_wire)

    # Light tubes (strobing)
    tube_me = cylinder_mesh("LightTube", 0.05, 14.0, 12)
    tube_me.materials.append(m_tube)
    tubes = []
    xs = [-6.3, -5.0, -3.6, -2.4, -1.1, 0.2, 1.4, 2.7, 3.9, 5.2, 6.4]
    for i, x in enumerate(xs):
        ob = link(bpy.data.objects.new(f"LightTube_{i:02d}", tube_me), coll)
        ob.location = (x + rng.uniform(-0.25, 0.25), rng.choice([1.2, 2.6, 4.2, 5.8]),
                       FLOOR_Z + 7.5 + rng.uniform(-1.0, 1.5))
        ob["glow"] = 0.0
        tubes.append(ob)
    animate_strobes(tubes)

    # Lights
    key = link(bpy.data.objects.new("Key_Top", bpy.data.lights.new("Key_Top", "AREA")), coll)
    key.data.shape = "RECTANGLE"
    key.data.size, key.data.size_y = 18.0, 6.0
    key.data.color = (0.95, 0.97, 1.0)
    key.location = (0, -3.0, 17.0)
    key.rotation_euler = (math.radians(-12), 0, 0)

    fill = link(bpy.data.objects.new("Fill_Front", bpy.data.lights.new("Fill_Front", "AREA")), coll)
    fill.data.size = 20.0
    fill.location = (0, -24.0, 12.0)
    fill.rotation_euler = (math.radians(65), 0, 0)
    fill.visible_glossy = False

    rim = link(bpy.data.objects.new("Wall_Top", bpy.data.lights.new("Wall_Top", "AREA")), coll)
    rim.data.shape = "RECTANGLE"
    rim.data.size, rim.data.size_y = 30.0, 3.0
    rim.location = (0, 5.0, 15.0)
    rim.rotation_euler = (math.radians(-20), 0, 0)

    # Big soft card only the chrome sees (no diffuse / volume contribution)
    refl = link(bpy.data.objects.new("Logo_Reflect", bpy.data.lights.new("Logo_Reflect", "AREA")), coll)
    refl.data.shape = "RECTANGLE"
    refl.data.size, refl.data.size_y = 26.0, 9.0
    refl.location = (0, -24.0, 7.0)
    refl.rotation_euler = (math.radians(75), 0, 0)
    refl.visible_diffuse = False
    refl.visible_volume_scatter = False
    refl.visible_transmission = False

    # fade-in: lights ramp up from black
    for ob, energy in ((key, 7000.0), (fill, 2500.0), (rim, 3000.0), (refl, 6000.0)):
        ob.data.energy = 0.0
        ob.data.keyframe_insert("energy", frame=1)
        ob.data.energy = energy
        ob.data.keyframe_insert("energy", frame=F_FADE_END)

    # Camera
    cam_data = bpy.data.cameras.new("SEAGMA_Cam")
    cam_data.lens = 35
    cam_data.sensor_width = 36
    cam_data.clip_end = 300
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = 8.0
    cam = link(bpy.data.objects.new("SEAGMA_Cam", cam_data), coll)
    scene.camera = cam
    animate_camera(cam)

    # World: very dark grey so the chrome reflects something but the frame stays moody
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.003, 0.003, 0.0035, 1)
        bg.inputs["Strength"].default_value = 1.0

    setup_render(scene)


def tube_glow_curve():
    """Per-frame tube brightness 0..1, measured from the reference video (150 BPM, beat 0.4 s).
    All tubes move together:
      13.0-26.7 s  dim glow + soft pulse once per bar (1.6 s)
      26.7-33.7 s  sharp flash every beat
      33.7-37.0 s  every half beat
      37.0-40.8 s  triplets (build-up)
      40.8-44.5 s  break (off)
      44.5 s-      flash every beat
    """
    beat, bar = 0.4, 1.6
    vals = []
    for f in range(1, FRAME_END + 1):
        t = (f - 1) / FPS
        if t < 13.0:
            v = 0.0
        elif t < 26.7:
            since = (t - 26.7) % bar                     # bars locked to the 26.7 s drop
            pulse = math.exp(-since / 0.35) if since > 0.06 else since / 0.06
            fade = min(1.0, (t - 13.0) / 1.5)
            v = fade * (0.3 + 0.7 * pulse)
        elif t < 33.7:
            v = 1.0 if ((t - 26.7) % beat) < 2.0 / FPS else 0.0
        elif t < 37.0:
            v = 1.0 if ((t - 33.7) % (beat / 2)) < 1.5 / FPS else 0.0
        elif t < 40.8:
            v = 1.0 if ((f - int(37.0 * FPS)) % 3) == 0 else 0.0
        elif t < 44.5:
            v = 0.0
        else:
            v = 1.0 if ((t - 44.5) % beat) < 2.0 / FPS else 0.0
        vals.append(round(v, 3))
    return vals


def animate_strobes(tubes):
    curve = tube_glow_curve()
    prev = None
    for f, v in enumerate(curve, start=1):
        if v == prev:
            continue
        for ob in tubes:
            ob["glow"] = v * 25.0
            ob.keyframe_insert('["glow"]', frame=f)
        prev = v
    for ob in tubes:
        ob["glow"] = 0.0
        set_interpolation(ob, "CONSTANT")


def iter_fcurves(id_data):
    ad = id_data.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    if hasattr(act, "layers") and act.layers:
        out = []
        for layer in act.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    out.extend(cb.fcurves)
        return out
    return list(act.fcurves)


def set_interpolation(id_data, interp, easing=None):
    for fc in iter_fcurves(id_data):
        for k in fc.keyframe_points:
            k.interpolation = interp
            if easing:
                k.easing = easing


def animate_camera(cam):
    keys = [
        # frame, location, rotation (deg), focus distance
        (1,               (-2.6, -7.3, 4.2), (86, 0, -4), 1.6),
        (F_FADE_END,      (-2.0, -7.6, 3.6), (87, 0, -2), 1.9),
        (F_PULL_END,      (0.0, -14.0, 1.6), (89, 0, 0), 8.5),
        (F_GATE_OPEN_END, (0.0, -20.0, 0.9), (90, 0, 0), 19.0),
        (F_HOLD + 200,    (0.5, -20.8, 0.8), (90, 0, 0.8), 19.8),
        (FRAME_END,       (-0.3, -21.4, 0.9), (90.5, 0, -0.6), 20.4),
    ]
    for f, loc, rot, focus in keys:
        cam.location = loc
        cam.rotation_euler = tuple(math.radians(r) for r in rot)
        cam.data.dof.focus_distance = focus
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        cam.data.keyframe_insert("dof.focus_distance", frame=f)
    set_interpolation(cam, "BEZIER")
    set_interpolation(cam.data, "BEZIER")


def setup_render(scene):
    scene.frame_start = 1
    scene.frame_end = FRAME_END
    scene.frame_current = F_HOLD + 100
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 128
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
    scene.cycles.volume_bounces = 2
    for attr, val in (("volume_step_rate", 1.0), ("volume_preview_step_rate", 2.0), ("volume_max_steps", 256)):
        if hasattr(scene.cycles, attr):
            setattr(scene.cycles, attr, val)
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.5
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    try:
        if hasattr(scene.render.image_settings, "media_type"):
            scene.render.image_settings.media_type = "VIDEO"
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "HIGH"
    except (TypeError, AttributeError):
        scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = "//render/seagma_logo_"


if __name__ == "__main__":
    build()
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--save" in argv:
        bpy.ops.wm.save_mainfile()
        print("SEAGMA: saved", bpy.data.filepath)
    print("SEAGMA: build done")
