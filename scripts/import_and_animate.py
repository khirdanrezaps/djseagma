"""
import_and_animate.py - Unreal Engine 5.8 editor script for DJ Seagma Anim.

Rebuilds the Blender logo animation (DJ Seagma 2026.blend / scripts/build_logo_anim.py)
inside Unreal:
  1. imports SourceAssets/SM_SeagmaLogo.fbx into /Game/Seagma/Meshes
  2. creates materials (chrome logo, smoke flipbook cards rendered from the smoke sim, light tubes, wires)
  3. creates level /Game/Seagma/Maps/LV_SeagmaLogo and spawns the set
     (cloud gates, side pillars, back wall, floor, light tubes, wires, lights, fog, cine camera)
  4. creates Level Sequence /Game/Seagma/Cinematics/LS_SeagmaLogo through
     LevelSequenceEditorSubsystem and keys it with the exact timing exported from Blender
     (SourceAssets/seagma_anim_data.json):
        0-4 s   fade in on a close-up of the cloud gate
        4-17 s  camera pulls back, light tubes flicker through the seam
        17-28 s gates slide open, logo revealed
        28-45 s wide hold, tubes strobe with the pattern measured from the reference (150 BPM)

Run inside the Unreal Editor (Tools > Execute Python Script..., or Output Log in "Cmd" mode:
    py "<project>/scripts/import_and_animate.py"
Safe to re-run: it deletes the actors it spawned before (tag "SeagmaAnim") and rebuilds
the sequence.
"""
import json
import os
import traceback

import unreal

# --------------------------------------------------------------------------- config
ROOT = "/Game/Seagma"
MESH_DIR = ROOT + "/Meshes"
MAT_DIR = ROOT + "/Materials"
MAP_PATH = ROOT + "/Maps/LV_SeagmaLogo"
SEQ_DIR = ROOT + "/Cinematics"
SEQ_NAME = "LS_SeagmaLogo"
TAG = "SeagmaAnim"

# If the imported logo faces the wrong way or reads mirrored, adjust this (degrees, Z axis).
LOGO_YAW_FIX = 0.0

# ---- look tuning (change these, then re-run the script) ----
EXPOSURE_BIAS = 0.0         # +1 = twice as bright, -1 = half
KEY_LUMENS = 900.0          # soft top light on the clouds
FILL_LUMENS = 120.0         # front fill (keeps the cloud faces readable)
TUBE_EMISSIVE = 4.0         # brightness of a lit tube (bloom does the rest)
TUBE_LIGHT_LUMENS = 60.0    # light each lit tube throws into the fog
TUBE_FOG_SCATTER = 6.0      # how much the tube lights glow inside the volumetric fog
SATURATION = 0.12           # reference is almost black & white
CLOUD_DENSITY = 0.35        # extinction per cm inside the cloud
LOGO_REFLECT_LUMENS = 4000.0  # what the chrome logo reflects (specular-only card behind camera)

PROJECT_DIR = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
SRC_DIR = os.path.join(PROJECT_DIR, "SourceAssets")
LOGO_FBX = os.path.join(SRC_DIR, "SM_SeagmaLogo.fbx")
PLATES_DIR = os.path.join(SRC_DIR, "SmokePlates")      # Cycles-rendered smoke flipbooks (render_smoke_plates.py)
PLATES_JSON = os.path.join(PLATES_DIR, "smoke_plates.json")
CARD_FBX = os.path.join(SRC_DIR, "SM_SmokeCard.fbx")
SMOKE_DIR = ROOT + "/Smoke"
SMOKE_SPEED = 0.35          # flipbook frames per sequence frame (lower = slower churn)
SMOKE_BRIGHTNESS = 1.0      # smoke card brightness
SMOKE_STROBE_GLOW = 0.6     # how much the smoke lights up when the tubes flash

DATA_JSON = os.path.join(SRC_DIR, "seagma_anim_data.json")

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
level_sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
seq_sub = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)


def log(msg):
    unreal.log("[SeagmaAnim] " + msg)


RESULTS = []   # (stage, ok, error) - shown in a popup at the end


def stage(name, fn, *args):
    """Run one step; an error is logged and reported but never stops the next steps."""
    try:
        out = fn(*args)
        RESULTS.append((name, True, ""))
        log("OK   " + name)
        return out
    except Exception as exc:
        RESULTS.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
        unreal.log_error("[SeagmaAnim] FAILED %s\n%s" % (name, traceback.format_exc()))
        return None


# --------------------------------------------------------------------------- import
def import_logo():
    task = unreal.AssetImportTask()
    task.filename = LOGO_FBX
    task.destination_path = MESH_DIR
    task.destination_name = "SM_SeagmaLogo"
    task.automated = True
    task.replace_existing = True
    task.save = True
    asset_tools.import_asset_tasks([task])
    path = MESH_DIR + "/SM_SeagmaLogo"
    mesh = eal.load_asset(path)
    if not isinstance(mesh, unreal.StaticMesh):
        # some importers return the mesh under a different name - take the first static mesh
        for p in task.imported_object_paths or []:
            obj = eal.load_asset(p)
            if isinstance(obj, unreal.StaticMesh):
                mesh = obj
                break
    if not isinstance(mesh, unreal.StaticMesh):
        raise RuntimeError("Logo import failed: " + LOGO_FBX)
    log("imported " + mesh.get_path_name())
    return mesh


# --------------------------------------------------------------------------- materials
def new_material(name):
    """Create the material, or empty an existing one (it may already be used by a mesh)."""
    path = MAT_DIR + "/" + name
    if eal.does_asset_exist(path):
        mat = eal.load_asset(path)
        mel.delete_all_material_expressions(mat)
        return mat
    return asset_tools.create_asset(name, MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())


def expr(mat, cls, x, y, **props):
    e = mel.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def const(mat, value, x, y):
    return expr(mat, unreal.MaterialExpressionConstant, x, y, r=value)


def color(mat, rgb, x, y):
    return expr(mat, unreal.MaterialExpressionConstant3Vector, x, y,
                constant=unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))


def finish(mat):
    mel.layout_material_expressions(mat)
    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)
    return mat


def make_chrome():
    m = new_material("M_Seagma_Chrome")
    mel.connect_material_property(color(m, (0.85, 0.85, 0.86), -400, -200), "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(const(m, 1.0, -400, 0), "", unreal.MaterialProperty.MP_METALLIC)
    mel.connect_material_property(const(m, 0.14, -400, 100), "", unreal.MaterialProperty.MP_ROUGHNESS)
    return finish(m)


def make_cloud():
    """Grey cloud surface whose light/dark pattern keeps rolling upward (World Position + Time noise)."""
    m = new_material("M_Seagma_Cloud")
    try:
        wp = expr(m, unreal.MaterialExpressionWorldPosition, -1200, 0)
        scale = expr(m, unreal.MaterialExpressionMultiply, -1000, 0)
        mel.connect_material_expressions(wp, "", scale, "A")
        mel.connect_material_expressions(const(m, 0.004, -1200, 150), "", scale, "B")
        t = expr(m, unreal.MaterialExpressionTime, -1200, 300)
        flow = expr(m, unreal.MaterialExpressionMultiply, -1000, 300)
        mel.connect_material_expressions(t, "", flow, "A")
        mel.connect_material_expressions(color(m, (0.04, 0.0, 0.07), -1200, 400), "", flow, "B")
        pos = expr(m, unreal.MaterialExpressionAdd, -800, 100)
        mel.connect_material_expressions(scale, "", pos, "A")
        mel.connect_material_expressions(flow, "", pos, "B")
        noise = expr(m, unreal.MaterialExpressionNoise, -600, 100, levels=6, output_min=0.0, output_max=1.0)
        mel.connect_material_expressions(pos, "", noise, "Position")
        lerp = expr(m, unreal.MaterialExpressionLinearInterpolate, -300, 0)
        mel.connect_material_expressions(color(m, (0.08, 0.08, 0.085), -600, -200), "", lerp, "A")
        mel.connect_material_expressions(color(m, (0.62, 0.62, 0.64), -600, -100), "", lerp, "B")
        mel.connect_material_expressions(noise, "", lerp, "Alpha")
        mel.connect_material_property(lerp, "", unreal.MaterialProperty.MP_BASE_COLOR)
    except Exception as exc:  # fall back to a flat grey if a node API changed
        unreal.log_warning("[SeagmaAnim] cloud noise graph failed (%s), using flat grey" % exc)
        mel.connect_material_property(color(m, (0.45, 0.45, 0.47), -400, 0), "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(const(m, 0.9, -400, 300), "", unreal.MaterialProperty.MP_ROUGHNESS)
    return finish(m)


MPC_NAME = "MPC_SeagmaTubes"


def make_mpc():
    """Material Parameter Collection with one scalar, TubeGlow (0..1), keyed by the sequence."""
    path = MAT_DIR + "/" + MPC_NAME
    mpc = eal.load_asset(path) if eal.does_asset_exist(path) else asset_tools.create_asset(
        MPC_NAME, MAT_DIR, unreal.MaterialParameterCollection, unreal.MaterialParameterCollectionFactoryNew())
    params = []
    for n in ("TubeGlow", "SmokeFrame"):
        p = unreal.CollectionScalarParameter()
        p.set_editor_property("parameter_name", n)
        p.set_editor_property("default_value", 0.0)
        params.append(p)
    mpc.set_editor_property("scalar_parameters", params)
    eal.save_loaded_asset(mpc)
    return mpc


def make_tube(mpc=None):
    m = new_material("M_Seagma_LightTube")
    mel.connect_material_property(color(m, (0.02, 0.02, 0.02), -400, -200), "", unreal.MaterialProperty.MP_BASE_COLOR)
    emis = color(m, (TUBE_EMISSIVE, TUBE_EMISSIVE * 0.97, TUBE_EMISSIVE * 0.93), -700, 0)
    if mpc is not None:
        cp = expr(m, unreal.MaterialExpressionCollectionParameter, -700, 150, collection=mpc,
                  parameter_name="TubeGlow")
        emis = node2(m, unreal.MaterialExpressionMultiply, emis, cp, -400, 50)
    mel.connect_material_property(emis, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return finish(m)


def make_wire():
    m = new_material("M_Seagma_Wire")
    mel.connect_material_property(color(m, (0.35, 0.35, 0.35), -400, -200), "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(const(m, 1.0, -400, 0), "", unreal.MaterialProperty.MP_METALLIC)
    mel.connect_material_property(const(m, 0.4, -400, 100), "", unreal.MaterialProperty.MP_ROUGHNESS)
    return finish(m)


def make_ground():
    m = new_material("M_Seagma_Ground")
    mel.connect_material_property(color(m, (0.015, 0.015, 0.016), -400, -200), "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(const(m, 0.85, -400, 0), "", unreal.MaterialProperty.MP_ROUGHNESS)
    return finish(m)


# --------------------------------------------------------------------------- smoke cards (flipbooks)
def p_scalar(m, name, value, x, y):
    return expr(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=name, default_value=value)


def node2(m, cls, a, b, x, y, ia="A", ib="B"):
    n = expr(m, cls, x, y)
    mel.connect_material_expressions(a, "", n, ia)
    mel.connect_material_expressions(b, "", n, ib)
    return n


def import_texture(png, name):
    task = unreal.AssetImportTask()
    task.filename = png
    task.destination_path = SMOKE_DIR
    task.destination_name = name
    task.automated = True
    task.replace_existing = True
    task.save = True
    asset_tools.import_asset_tasks([task])
    tex = eal.load_asset(SMOKE_DIR + "/" + name)
    if tex is None:
        raise RuntimeError("texture import failed: " + png)
    set_first(tex, ["never_stream"], True)                 # full res in Movie Render Queue
    set_first(tex, ["lod_group"], unreal.TextureGroup.TEXTUREGROUP_CINEMATIC)
    set_first(tex, ["mip_gen_settings"], unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    eal.save_loaded_asset(tex)
    return tex


def import_card_mesh():
    task = unreal.AssetImportTask()
    task.filename = CARD_FBX
    task.destination_path = MESH_DIR
    task.destination_name = "SM_SmokeCard"
    task.automated = True
    task.replace_existing = True
    task.save = True
    asset_tools.import_asset_tasks([task])
    mesh = eal.load_asset(MESH_DIR + "/SM_SmokeCard")
    if mesh is None:
        raise RuntimeError("card import failed")
    return mesh


def make_smoke_material(name, tex, info, mpc):
    """Unlit translucent flipbook: frame = (SmokeFrame * Speed + Offset) mod Frames, blended with the next
    frame for smooth motion; the smoke brightens with the tube strobe (MPC TubeGlow)."""
    m = new_material(name)
    set_first(m, ["blend_mode"], unreal.BlendMode.BLEND_TRANSLUCENT)
    set_first(m, ["shading_model"], unreal.MaterialShadingModel.MSM_UNLIT)
    set_first(m, ["two_sided"], True)
    cols, rows, frames = float(info["cols"]), float(info["rows"]), float(info["frames"])

    t = expr(m, unreal.MaterialExpressionCollectionParameter, -2600, 0, collection=mpc, parameter_name="SmokeFrame")
    tf = node2(m, unreal.MaterialExpressionMultiply, t, p_scalar(m, "Speed", 1.0, -2600, 120), -2400, 40)
    tf = node2(m, unreal.MaterialExpressionAdd, tf, p_scalar(m, "Offset", 0.0, -2600, 220), -2250, 80)
    fl = expr(m, unreal.MaterialExpressionFloor, -2100, 0)
    mel.connect_material_expressions(tf, "", fl, "")
    blend = node2(m, unreal.MaterialExpressionSubtract, tf, fl, -2000, 200)        # frac -> blend weight
    uv = expr(m, unreal.MaterialExpressionTextureCoordinate, -2100, 400)

    def sample(frame_node, y):
        k = node2(m, unreal.MaterialExpressionFmod, frame_node, const(m, frames, -1900, y + 60), -1750, y)
        col = node2(m, unreal.MaterialExpressionFmod, k, const(m, cols, -1600, y + 60), -1450, y)
        row = expr(m, unreal.MaterialExpressionFloor, -1300, y + 100)
        mel.connect_material_expressions(node2(m, unreal.MaterialExpressionDivide, k, const(m, cols, -1600, y + 160),
                                               -1450, y + 100), "", row, "")
        cell = node2(m, unreal.MaterialExpressionAppendVector, col, row, -1150, y)
        auv = node2(m, unreal.MaterialExpressionAdd, uv, cell, -1000, y)
        auv = node2(m, unreal.MaterialExpressionDivide, auv,
                    expr(m, unreal.MaterialExpressionConstant2Vector, -1150, y + 120, r=cols, g=rows), -850, y)
        ts = expr(m, unreal.MaterialExpressionTextureSample, -650, y, texture=tex)
        set_first(ts, ["sampler_type"], unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        mel.connect_material_expressions(auv, "", ts, "UVs")
        return ts

    s0 = sample(fl, -200)
    nxt = node2(m, unreal.MaterialExpressionAdd, fl, const(m, 1.0, -1900, 500), -1800, 450)
    s1 = sample(nxt, 450)
    rgb = expr(m, unreal.MaterialExpressionLinearInterpolate, -350, -100)
    mel.connect_material_expressions(s0, "RGB", rgb, "A")
    mel.connect_material_expressions(s1, "RGB", rgb, "B")
    mel.connect_material_expressions(blend, "", rgb, "Alpha")
    alpha = expr(m, unreal.MaterialExpressionLinearInterpolate, -350, 150)
    mel.connect_material_expressions(s0, "A", alpha, "A")
    mel.connect_material_expressions(s1, "A", alpha, "B")
    mel.connect_material_expressions(blend, "", alpha, "Alpha")

    bright = node2(m, unreal.MaterialExpressionMultiply, rgb, p_scalar(m, "Brightness", SMOKE_BRIGHTNESS, -350, 0),
                   -150, -100)
    glow = expr(m, unreal.MaterialExpressionCollectionParameter, -500, 300, collection=mpc, parameter_name="TubeGlow")
    glow = node2(m, unreal.MaterialExpressionMultiply, glow, p_scalar(m, "StrobeGlow", SMOKE_STROBE_GLOW, -500, 400),
                 -300, 330)
    glow = node2(m, unreal.MaterialExpressionMultiply, glow, alpha, -150, 300)
    emis = node2(m, unreal.MaterialExpressionAdd, bright, glow, 0, 0)
    op = node2(m, unreal.MaterialExpressionMultiply, alpha, p_scalar(m, "Opacity", 1.0, -150, 450), 0, 300)
    mel.connect_material_property(emis, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    return finish(m)


def smoke_instance(parent, name, offset, speed=1.0, brightness=None):
    path = MAT_DIR + "/" + name
    mi = eal.load_asset(path) if eal.does_asset_exist(path) else asset_tools.create_asset(
        name, MAT_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    mel.set_material_instance_scalar_parameter_value(mi, "Offset", float(offset))
    mel.set_material_instance_scalar_parameter_value(mi, "Speed", float(speed))
    if brightness is not None:
        mel.set_material_instance_scalar_parameter_value(mi, "Brightness", float(brightness))
    mel.update_material_instance(mi)
    eal.save_loaded_asset(mi)
    return mi


def make_smoke(mpc):
    """Import the three flipbook atlases + card mesh, build one material per atlas."""
    meta = json.load(open(PLATES_JSON))
    out = {"card": import_card_mesh(), "meta": meta}
    for key in ("gate", "wall", "floor"):
        info = meta[key]
        tex = import_texture(os.path.join(PLATES_DIR, info["file"]), "T_Smoke_" + key.capitalize())
        out[key] = make_smoke_material("M_Smoke_" + key.capitalize(), tex, info, mpc)
    return out


# --------------------------------------------------------------------------- level + actors
def open_or_create_level():
    if eal.does_asset_exist(MAP_PATH):
        level_sub.load_level(MAP_PATH)
    else:
        level_sub.new_level(MAP_PATH)
    for a in actor_sub.get_all_level_actors():
        if a.actor_has_tag(TAG):
            actor_sub.destroy_actor(a)


def V(xyz):
    return unreal.Vector(float(xyz[0]), float(xyz[1]), float(xyz[2]))


def spawn(cls, loc, rot=(0, 0, 0), label=None):
    a = actor_sub.spawn_actor_from_class(cls, V(loc), unreal.Rotator(roll=rot[0], pitch=rot[1], yaw=rot[2]))
    a.tags = [TAG]
    if label:
        a.set_actor_label(label)
    return a


def spawn_mesh(mesh, mat, loc, scale, label, rot=(0, 0, 0)):
    a = spawn(unreal.StaticMeshActor, loc, rot, label)
    comp = a.static_mesh_component
    comp.set_mobility(unreal.ComponentMobility.MOVABLE)
    comp.set_static_mesh(mesh)
    if mat:
        comp.set_material(0, mat)
    a.set_actor_scale3d(V(scale))
    return a


def build_set(data, logo_mesh, mats):
    cube = eal.load_asset("/Engine/BasicShapes/Cube")          # 100 cm cube, pivot at centre
    cyl = eal.load_asset("/Engine/BasicShapes/Cylinder")       # 100 cm tall, 100 cm wide
    actors = {}

    if logo_mesh is not None:
        actors["logo"] = spawn_mesh(logo_mesh, mats.get("chrome"), data["logo"]["location"], (1, 1, 1),
                                    "SeagmaLogo", (0, 0, LOGO_YAW_FIX))

    smoke = mats.get("smoke")

    def card(label, loc, w_cm, h_cm, mat_key, offset, parent=None, speed=1.0, brightness=None):
        if smoke is None:
            return None
        mi = smoke_instance(smoke[mat_key], "MI_Smoke_" + label, offset, speed, brightness)
        a = spawn_mesh(smoke["card"], mi, loc, (w_cm / 100.0, 1.0, h_cm / 100.0), label)
        a.static_mesh_component.set_cast_shadow(False)
        if parent is not None:
            a.attach_to_actor(parent, "", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                              unreal.AttachmentRule.KEEP_WORLD, False)
        return a

    nf = smoke["meta"]["gate"]["frames"] if smoke else 80
    for i, (name, g) in enumerate(data["gates"].items()):
        w, d, h = g["size_cm"]
        x0 = g["x_keys"][0]["x_cm"]
        # the gate actor is the back smoke layer; a front layer rides along (parallax, depth)
        back = card(name, (x0, g["y_cm"] - d * 0.25, g["z_cm"]), w, h, "gate", i * 31 % nf)
        actors[name] = back
        card(name + "_Front", (x0, g["y_cm"] + d * 0.5, g["z_cm"]), w * 1.04, h, "gate", (i * 31 + 47) % nf, back,
             1.15, 1.1)
    for i, pl in enumerate(data["pillars"]):
        w, d, h = pl["size_cm"]
        x, y, z = pl["location"]
        card("Pillar_%d" % i, (x, y + d * 0.5, z), w * 1.3, h, "gate", (i * 19 + 11) % nf, None, 0.9, 0.85)
    bw = data["BackWall"]
    card("BackWall", (bw["location"][0], bw["location"][1], 300.0), 2600.0, 1400.0, "wall", 0, None, 0.8, 0.8)
    card("BackWall_Near", (0.0, bw["location"][1] + 250.0, 250.0), 2700.0, 1450.0, "wall", 37, None, 0.9, 0.65)
    fl = data["CloudFloor"]
    floor_z = fl["location"][2] - fl["size_cm"][2] / 2.0
    card("CloudFloor", (0.0, 250.0, floor_z + 200.0), 4600.0, 400.0, "floor", 0, None, 1.0, 1.1)
    card("CloudFloor_Back", (0.0, -350.0, floor_z + 230.0), 4600.0, 460.0, "floor", 29, None, 0.85, 0.9)

    # dark ground under the smoke
    ground_z = fl["location"][2] - fl["size_cm"][2] / 2.0
    spawn_mesh(cube, mats.get("ground"), (0, 0, ground_z - 50), (80, 60, 1), "Ground")

    actors["tubes"] = []
    for t in data["light_tubes"]:
        a = spawn_mesh(cyl, mats.get("tube"), t["location"], (0.1, 0.1, t["length_cm"] / 100), t["name"])
        a.static_mesh_component.set_cast_shadow(False)
        light = stage("tube light " + t["name"], tube_light, t)
        actors["tubes"].append((a, t))
        if light is not None:
            actors.setdefault("tube_lights", []).append((light, t))
    for i, w in enumerate(data["wires"]):
        spawn_mesh(cyl, mats.get("wire"), w["location"], (0.016, 0.016, w["length_cm"] / 100), "Wire_%02d" % i)

    stage("lights", build_lights)
    stage("smoke fog", build_fog)
    stage("post process (exposure, b&w grade, bloom)", build_post_process)

    # Cine camera - lens/filmback matching Blender (35 mm on a 36 mm sensor, f/8)
    cam_data = data["camera"]
    k0 = cam_data["keys"][0]
    cam = spawn(unreal.CineCameraActor, k0["location"], (k0["roll"], k0["pitch"], k0["yaw"]), "SEAGMA_Cam")
    actors["camera"] = cam
    stage("camera lens settings", setup_lens, cam, cam_data, k0)
    return actors


def tube_light(t):
    """Long thin rect light inside each tube: lights the clouds and glows in the volumetric fog."""
    a = spawn(unreal.RectLight, t["location"], (0, 0, -90), t["name"] + "_Light")
    c = a.get_component_by_class(unreal.RectLightComponent)
    set_first(c, ["intensity_units"], unreal.LightUnits.LUMENS)
    c.set_intensity(TUBE_LIGHT_LUMENS)
    set_first(c, ["source_width"], 10.0)
    set_first(c, ["source_height"], float(t["length_cm"]))
    set_first(c, ["attenuation_radius"], 1800.0)
    set_first(c, ["volumetric_scattering_intensity"], TUBE_FOG_SCATTER)
    set_first(c, ["cast_shadows"], False)
    set_first(c, ["light_color"], unreal.Color(255, 248, 238, 255))
    c.set_intensity(0.0)                       # the sequence keys the intensity with the strobe
    return a


def build_lights():
    # Lights (same layout idea as the Blender scene: soft top key, front fill, skylight)
    key = spawn(unreal.RectLight, (0, 300, 1700), (0, -78, 90), "Key_Top")
    kc = key.get_component_by_class(unreal.RectLightComponent)
    kc.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
    kc.set_intensity(KEY_LUMENS)
    set_first(kc, ["volumetric_scattering_intensity"], 1.0)
    kc.set_editor_property("source_width", 1800.0)
    kc.set_editor_property("source_height", 600.0)
    kc.set_editor_property("attenuation_radius", 6000.0)

    # big soft card behind the camera that only the chrome sees (specular only)
    refl = spawn(unreal.RectLight, (0, 2700, 650), (0, -8, -90), "Logo_Reflect")
    rc = refl.get_component_by_class(unreal.RectLightComponent)
    set_first(rc, ["intensity_units"], unreal.LightUnits.LUMENS)
    rc.set_intensity(LOGO_REFLECT_LUMENS)
    set_first(rc, ["source_width"], 2600.0)
    set_first(rc, ["source_height"], 900.0)
    set_first(rc, ["attenuation_radius"], 6000.0)
    set_first(rc, ["diffuse_scale"], 0.0)
    set_first(rc, ["volumetric_scattering_intensity"], 0.0)
    set_first(rc, ["cast_shadows"], False)

    fill = spawn(unreal.RectLight, (0, 2400, 1200), (0, -25, -90), "Fill_Front")
    fc = fill.get_component_by_class(unreal.RectLightComponent)
    fc.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
    fc.set_intensity(FILL_LUMENS)
    set_first(fc, ["volumetric_scattering_intensity"], 0.3)
    fc.set_editor_property("source_width", 2000.0)
    fc.set_editor_property("source_height", 2000.0)
    fc.set_editor_property("attenuation_radius", 8000.0)




def set_first(obj, names, value):
    """Set the first property name that exists (names differ between engine versions)."""
    for n in names:
        try:
            obj.set_editor_property(n, value)
            return n
        except Exception:
            continue
    unreal.log_warning("[SeagmaAnim] none of %s found on %s" % (names, obj.get_class().get_name()))
    return None


def build_post_process():
    ppv = spawn(unreal.PostProcessVolume, (0, 0, 0), label="SeagmaGrade")
    set_first(ppv, ["unbound", "b_unbound"], True)
    ps = ppv.get_editor_property("settings")

    def ov(name, value):
        try:
            ps.set_editor_property("override_" + name, True)
            ps.set_editor_property(name, value)
        except Exception as exc:
            unreal.log_warning("[SeagmaAnim] post process %s not set: %s" % (name, exc))

    ov("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
    ov("auto_exposure_apply_physical_camera_exposure", False)
    ov("auto_exposure_bias", EXPOSURE_BIAS)
    ov("color_saturation", unreal.Vector4(SATURATION, SATURATION, SATURATION, 1.0))
    ov("color_contrast", unreal.Vector4(1.25, 1.25, 1.25, 1.0))
    ov("bloom_intensity", 0.9)
    ov("bloom_threshold", 1.0)
    ov("vignette_intensity", 0.55)
    ov("film_grain_intensity", 0.12)
    ov("local_exposure_highlight_contrast_scale", 0.9)
    ppv.set_editor_property("settings", ps)


def build_fog():
    fog = spawn(unreal.ExponentialHeightFog, (0, 0, -400), label="SmokeFog")
    fogc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    set_first(fogc, ["fog_density"], 0.012)
    set_first(fogc, ["fog_height_falloff"], 0.35)
    set_first(fogc, ["fog_inscattering_luminance", "fog_inscattering_color"], unreal.LinearColor(0.004, 0.004, 0.0045, 1))
    set_first(fogc, ["volumetric_fog_scattering_distribution"], 0.6)
    set_first(fogc, ["volumetric_fog_albedo"], unreal.Color(200, 200, 205, 255))
    set_first(fogc, ["enable_volumetric_fog", "volumetric_fog", "b_enable_volumetric_fog"], True)
    set_first(fogc, ["volumetric_fog_extinction_scale"], 2.0)



def setup_lens(cam, cam_data, k0):
    cc = cam.get_cine_camera_component()
    fb = cc.filmback
    fb.sensor_width = cam_data["sensor_mm"]
    fb.sensor_height = cam_data["sensor_mm"] * 9.0 / 16.0
    cc.filmback = fb
    cc.current_focal_length = cam_data["lens_mm"]
    cc.current_aperture = cam_data["fstop"]
    fs = cc.focus_settings
    fs.focus_method = unreal.CameraFocusMethod.MANUAL
    fs.manual_focus_distance = k0["focus_cm"]
    cc.focus_settings = fs


# --------------------------------------------------------------------------- sequence helpers
def F(blender_frame):
    """Blender frames start at 1, Sequencer frames at 0."""
    return unreal.FrameNumber(int(round(blender_frame)) - 1)


def double_channels(section):
    for t in (getattr(unreal, "MovieSceneScriptingDoubleChannel", None),
              getattr(unreal, "MovieSceneScriptingFloatChannel", None)):
        if t is None:
            continue
        ch = section.get_channels_by_type(t)
        if ch:
            return ch
    return section.get_all_channels()


def add_key(channel, frame, value, interp=unreal.MovieSceneKeyInterpolation.AUTO):
    channel.add_key(F(frame), value, 0.0, unreal.MovieSceneTimeUnit.DISPLAY_RATE, interp)


def transform_section(binding, end_frame):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    section.set_range(0, end_frame)
    ch = double_channels(section)  # LocX LocY LocZ RotX(roll) RotY(pitch) RotZ(yaw) ScaleX ScaleY ScaleZ
    return ch


def key_transform(ch, frame, loc, rot, scale, interp=unreal.MovieSceneKeyInterpolation.AUTO):
    for i, v in enumerate(list(loc) + list(rot) + list(scale)):
        add_key(ch[i], frame, float(v), interp)


def get_binding_id(seq, binding):
    for fn in (lambda: seq.get_portable_binding_id(seq, binding),
               lambda: unreal.MovieSceneSequenceExtensions.get_portable_binding_id(seq, seq, binding),
               lambda: seq.get_binding_id(binding),
               lambda: binding.get_binding_id()):
        try:
            return fn()
        except Exception:
            continue
    raise RuntimeError("could not resolve camera binding id")


# --------------------------------------------------------------------------- sequence
def create_sequence(data):
    """Create + save the Level Sequence asset first, so it exists even if a later step fails."""
    path = SEQ_DIR + "/" + SEQ_NAME
    try:
        unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
    except Exception:
        pass
    if eal.does_asset_exist(path):
        eal.delete_asset(path)
    if not eal.does_directory_exist(SEQ_DIR):
        eal.make_directory(SEQ_DIR)
    seq = asset_tools.create_asset(SEQ_NAME, SEQ_DIR, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    if seq is None:
        raise RuntimeError("AssetTools.create_asset returned None for " + path)

    fps = int(data["fps"])
    end = int(data["frame_end"])                     # Blender 1..1080 -> Sequencer 0..1080 (end exclusive)
    seq.set_display_rate(unreal.FrameRate(fps, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(end)
    for fn, val in (("set_view_range_start", 0.0), ("set_view_range_end", end / float(fps)),
                    ("set_work_range_start", 0.0), ("set_work_range_end", end / float(fps))):
        try:
            getattr(seq, fn)(val)
        except Exception:
            pass
    eal.save_asset(path, only_if_is_dirty=False)
    log("sequence asset created: " + path)
    return seq


def bind(actors_list):
    """Bind actors through LevelSequenceEditorSubsystem; fall back to add_possessable per actor."""
    try:
        bindings = seq_sub.add_actors(actors_list)
        if bindings and len(bindings) == len(actors_list):
            return list(bindings)
        unreal.log_warning("[SeagmaAnim] add_actors returned %d bindings for %d actors, falling back"
                           % (len(bindings or []), len(actors_list)))
    except Exception as exc:
        unreal.log_warning("[SeagmaAnim] add_actors failed (%s), falling back" % exc)
    seq = unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence()
    return [seq.add_possessable(a) for a in actors_list]


def animate_sequence(seq, data, actors):
    fps = int(data["fps"])
    end = int(data["frame_end"])
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)

    cam = actors.get("camera")
    gate_actors = [actors[n] for n in data["gates"] if n in actors]
    tubes = actors.get("tubes", [])

    if cam is not None:
        cam_b = bind([cam])[0]
        stage("sequence: camera move", key_camera, data, cam_b, end)
        stage("sequence: focus distance", key_focus, seq, data, cam, cam_b, end)
        stage("sequence: camera cut", camera_cut, seq, cam_b, end)
    if gate_actors:
        stage("sequence: gates open", key_gates, data, gate_actors, bind(gate_actors), end)
    glow = data.get("tube_glow")
    if glow and actors.get("mpc") is not None:
        stage("sequence: tube strobe (MPC TubeGlow)", key_tube_mpc, seq, actors["mpc"], glow, end)
    tube_lights = actors.get("tube_lights", [])
    if glow and tube_lights:
        stage("sequence: tube light strobe (fog glow)", key_tube_lights, seq, tube_lights, glow, end)
    if actors.get("mpc") is not None:
        stage("sequence: smoke flipbook time (MPC SmokeFrame)", key_smoke_time, seq, actors["mpc"], end)
    stage("sequence: fade in", key_fade, seq, data, end)

    eal.save_loaded_asset(seq)
    try:
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    except Exception:
        pass


def key_camera(data, cam_b, end):
    ch = transform_section(cam_b, end)
    for k in data["camera"]["keys"]:
        key_transform(ch, k["frame"], k["location"], (k["roll"], k["pitch"], k["yaw"]), (1, 1, 1))


def key_focus(seq, data, cam, cam_b, end):
    comp_b = None
    for child in cam_b.get_child_possessables():
        if "Camera" in str(child.get_display_name()):
            comp_b = child
            break
    if comp_b is None:
        comp_b = seq.add_possessable(cam.get_cine_camera_component())
    ftrack = comp_b.add_track(unreal.MovieSceneFloatTrack)
    ftrack.set_property_name_and_path("ManualFocusDistance", "FocusSettings.ManualFocusDistance")
    fsec = ftrack.add_section()
    fsec.set_range(0, end)
    fch = double_channels(fsec)[0]
    for k in data["camera"]["keys"]:
        add_key(fch, k["frame"], float(k["focus_cm"]))


def camera_cut(seq, cam_b, end):
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack)
    cut_sec = cut.add_section()
    cut_sec.set_range(0, end)
    cut_sec.set_camera_binding_id(get_binding_id(seq, cam_b))


def key_gates(data, gate_actors, gate_b, end):
    gates = [(n, g) for n, g in data["gates"].items()]
    for (name, g), b, a in zip(gates, gate_b, gate_actors):
        ch = transform_section(b, end)
        scale = a.get_actor_scale3d()
        loc = a.get_actor_location()
        for k in g["x_keys"]:
            key_transform(ch, k["frame"], (k["x_cm"], loc.y, loc.z), (0, 0, 0),
                          (scale.x, scale.y, scale.z))


def changes(values):
    """(frame, value) where the curve changes; frames are Blender-style (1-based)."""
    out, prev = [], None
    for f, v in enumerate(values, start=1):
        if v != prev:
            out.append((f, v))
            prev = v
    return out


def key_tube_mpc(seq, mpc, glow, end):
    track = seq.add_track(unreal.MovieSceneMaterialParameterCollectionTrack)
    track.set_editor_property("mpc", mpc)
    sec = track.add_section()
    sec.set_range(0, end)
    for f, v in changes(glow):
        sec.add_scalar_parameter_key("TubeGlow", F(f), float(v))
    set_constant_interp(sec)


def component_binding(seq, actor_b, actor, comp):
    for child in actor_b.get_child_possessables():
        if comp.get_name() in str(child.get_display_name()) or comp.get_class().get_name() in str(child.get_name()):
            return child
    return seq.add_possessable(comp)


def key_tube_lights(seq, tube_lights, glow, end):
    keys = changes(glow)
    for b, (a, t) in zip(bind([a for a, _ in tube_lights]), tube_lights):
        comp = a.get_component_by_class(unreal.RectLightComponent)
        cb = component_binding(seq, b, a, comp)
        tr = cb.add_track(unreal.MovieSceneFloatTrack)
        tr.set_property_name_and_path("Intensity", "Intensity")
        sec = tr.add_section()
        sec.set_range(0, end)
        ch = double_channels(sec)[0]
        for f, v in keys:
            add_key(ch, f, float(v) * TUBE_LIGHT_LUMENS, unreal.MovieSceneKeyInterpolation.CONSTANT)


def key_smoke_time(seq, mpc, end):
    """SmokeFrame runs linearly 0 -> end * SMOKE_SPEED; each material wraps it with its own offset."""
    track = seq.add_track(unreal.MovieSceneMaterialParameterCollectionTrack)
    track.set_editor_property("mpc", mpc)
    sec = track.add_section()
    sec.set_range(0, end)
    sec.add_scalar_parameter_key("SmokeFrame", F(1), 0.0)
    sec.add_scalar_parameter_key("SmokeFrame", F(end + 1), float(end) * SMOKE_SPEED)
    try:
        for ch in sec.get_all_channels():
            for k in ch.get_keys():
                k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_LINEAR)
    except Exception:
        pass


def set_constant_interp(section):
    try:
        for ch in section.get_all_channels():
            for k in ch.get_keys():
                try:
                    k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_CONSTANT)
                except Exception:
                    pass
    except Exception:
        pass


def key_fade(seq, data, end):
    fade = seq.add_track(unreal.MovieSceneFadeTrack)
    fsec = fade.add_section()
    fsec.set_range(0, end)
    fch = double_channels(fsec)[0]
    add_key(fch, data["fade_in"]["from_frame"], 1.0)
    add_key(fch, data["fade_in"]["to_frame"], 0.0)


# --------------------------------------------------------------------------- main
def make_materials():
    mats = {}
    mpc = stage("material parameter collection (tube strobe)", make_mpc)
    if mpc is not None:
        mats["mpc"] = mpc
    for key, fn in (("chrome", make_chrome), ("cloud", make_cloud), ("tube", lambda: make_tube(mpc)),
                    ("wire", make_wire), ("ground", make_ground)):
        m = stage("material " + key, fn)
        if m is not None:
            mats[key] = m
    if mpc is not None:
        sm = stage("smoke flipbooks (textures + card + materials)", make_smoke, mpc)
        if sm is not None:
            mats["smoke"] = sm
    return mats


def assign_logo_material(logo_mesh, mats):
    logo_mesh.set_material(0, mats["chrome"])
    eal.save_loaded_asset(logo_mesh)


def report():
    lines = [("OK      " if ok else "GAGAL   ") + name + ("" if ok else "\n          " + err)
             for name, ok, err in RESULTS]
    failed = [r for r in RESULTS if not r[1]]
    summary = "\n".join(lines)
    log("summary:\n" + summary)
    head = ("Semua langkah berhasil.\n" if not failed else
            "%d langkah gagal - detail lengkap ada di Output Log (cari [SeagmaAnim]).\n" % len(failed))
    head += "Sequence: %s/%s\n\n" % (SEQ_DIR, SEQ_NAME)
    try:
        unreal.EditorDialog.show_message("DJ Seagma - import_and_animate", head + summary,
                                         unreal.AppMsgType.OK)
    except Exception:
        pass


def main():
    if not os.path.isfile(DATA_JSON) or not os.path.isfile(LOGO_FBX):
        unreal.EditorDialog.show_message(
            "DJ Seagma", "SourceAssets tidak ditemukan:\n%s\n%s\n\nPastikan sudah git pull dan "
            "folder SourceAssets ada di sebelah DJSeagma_Anim.uproject." % (LOGO_FBX, DATA_JSON),
            unreal.AppMsgType.OK)
        return
    with open(DATA_JSON, "r") as fh:
        data = json.load(fh)

    with unreal.ScopedSlowTask(6, "DJ Seagma: building logo animation") as task:
        task.make_dialog(True)
        task.enter_progress_frame(1, "Creating Level Sequence asset")
        seq = stage("create Level Sequence asset", create_sequence, data)
        task.enter_progress_frame(1, "Importing logo FBX")
        logo_mesh = stage("import logo FBX", import_logo)
        task.enter_progress_frame(1, "Creating materials")
        mats = make_materials()
        if logo_mesh is not None and "chrome" in mats:
            stage("assign chrome to logo", assign_logo_material, logo_mesh, mats)
        task.enter_progress_frame(1, "Building level")
        stage("open/create level " + MAP_PATH, open_or_create_level)
        actors = stage("spawn set actors", build_set, data, logo_mesh, mats) or {}
        actors["mpc"] = mats.get("mpc")
        task.enter_progress_frame(1, "Animating Level Sequence")
        if seq is not None:
            stage("animate sequence", animate_sequence, seq, data, actors)
        task.enter_progress_frame(1, "Saving")
        stage("save level", level_sub.save_current_level)
    report()


main()
