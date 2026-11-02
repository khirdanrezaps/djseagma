"""
import_and_animate.py - Unreal Engine 5.8 editor script for DJ Seagma Anim.

Rebuilds the Blender logo animation (DJ Seagma 2026.blend / scripts/build_logo_anim.py)
inside Unreal:
  1. imports SourceAssets/SM_SeagmaLogo.fbx into /Game/Seagma/Meshes
  2. creates materials (chrome logo, moving-cloud gates, emissive light tubes, wires)
  3. creates level /Game/Seagma/Maps/LV_SeagmaLogo and spawns the set
     (cloud gates, side pillars, back wall, floor, light tubes, wires, lights, fog, cine camera)
  4. creates Level Sequence /Game/Seagma/Cinematics/LS_SeagmaLogo through
     LevelSequenceEditorSubsystem and keys it with the exact timing exported from Blender
     (SourceAssets/seagma_anim_data.json):
        0-4 s   fade in on a close-up of the cloud gate
        4-17 s  camera pulls back, light tubes flicker through the seam
        17-28 s gates slide open, logo revealed
        28-45 s wide hold, tubes strobe on the beat (128 BPM)

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

PROJECT_DIR = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
SRC_DIR = os.path.join(PROJECT_DIR, "SourceAssets")
LOGO_FBX = os.path.join(SRC_DIR, "SM_SeagmaLogo.fbx")
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


def make_tube():
    m = new_material("M_Seagma_LightTube")
    mel.connect_material_property(color(m, (0.02, 0.02, 0.02), -400, -200), "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(color(m, (40.0, 38.8, 37.2), -400, 0), "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return finish(m)


def make_wire():
    m = new_material("M_Seagma_Wire")
    mel.connect_material_property(color(m, (0.35, 0.35, 0.35), -400, -200), "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(const(m, 1.0, -400, 0), "", unreal.MaterialProperty.MP_METALLIC)
    mel.connect_material_property(const(m, 0.4, -400, 100), "", unreal.MaterialProperty.MP_ROUGHNESS)
    return finish(m)


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

    for name, g in data["gates"].items():
        k0 = g["x_keys"][0]["x_cm"]
        s = g["size_cm"]
        actors[name] = spawn_mesh(cube, mats.get("cloud"), (k0, g["y_cm"], g["z_cm"]),
                                  (s[0] / 100, s[1] / 100, s[2] / 100), name)

    for i, p in enumerate(data["pillars"]):
        s = p["size_cm"]
        spawn_mesh(cube, mats.get("cloud"), p["location"], (s[0] / 100, s[1] / 100, s[2] / 100), "Pillar_%d" % i)
    for key in ("BackWall", "CloudFloor"):
        s = data[key]["size_cm"]
        spawn_mesh(cube, mats.get("cloud"), data[key]["location"], (s[0] / 100, s[1] / 100, s[2] / 100), key)

    actors["tubes"] = []
    for t in data["light_tubes"]:
        a = spawn_mesh(cyl, mats.get("tube"), t["location"], (0.1, 0.1, t["length_cm"] / 100), t["name"])
        a.static_mesh_component.set_cast_shadow(False)
        actors["tubes"].append((a, t))
    for i, w in enumerate(data["wires"]):
        spawn_mesh(cyl, mats.get("wire"), w["location"], (0.016, 0.016, w["length_cm"] / 100), "Wire_%02d" % i)

    stage("lights", build_lights)
    stage("smoke fog", build_fog)

    # Cine camera - lens/filmback matching Blender (35 mm on a 36 mm sensor, f/8)
    cam_data = data["camera"]
    k0 = cam_data["keys"][0]
    cam = spawn(unreal.CineCameraActor, k0["location"], (k0["roll"], k0["pitch"], k0["yaw"]), "SEAGMA_Cam")
    actors["camera"] = cam
    stage("camera lens settings", setup_lens, cam, cam_data, k0)
    return actors


def build_lights():
    # Lights (same layout idea as the Blender scene: soft top key, front fill, skylight)
    key = spawn(unreal.RectLight, (0, 300, 1700), (0, -78, 90), "Key_Top")
    kc = key.get_component_by_class(unreal.RectLightComponent)
    kc.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
    kc.set_intensity(60000.0)
    kc.set_editor_property("source_width", 1800.0)
    kc.set_editor_property("source_height", 600.0)
    kc.set_editor_property("attenuation_radius", 6000.0)

    fill = spawn(unreal.RectLight, (0, 2400, 1200), (0, -25, -90), "Fill_Front")
    fc = fill.get_component_by_class(unreal.RectLightComponent)
    fc.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
    fc.set_intensity(15000.0)
    fc.set_editor_property("source_width", 2000.0)
    fc.set_editor_property("source_height", 2000.0)
    fc.set_editor_property("attenuation_radius", 8000.0)

    sky = spawn(unreal.SkyLight, (0, 0, 2000), label="SkyLight")
    sc = sky.get_component_by_class(unreal.SkyLightComponent)
    sc.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_CAPTURED_SCENE)
    sc.set_editor_property("real_time_capture", True)
    sc.set_intensity(0.15)



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


def build_fog():
    fog = spawn(unreal.ExponentialHeightFog, (0, 0, -400), label="SmokeFog")
    fogc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    set_first(fogc, ["fog_density"], 0.03)
    set_first(fogc, ["fog_height_falloff"], 0.6)
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
    if tubes:
        stage("sequence: light tube strobes", key_tubes, tubes, bind([a for a, _ in tubes]), end)
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
        for k in g["x_keys"]:
            key_transform(ch, k["frame"], (k["x_cm"], g["y_cm"], g["z_cm"]), (0, 0, 0),
                          (scale.x, scale.y, scale.z))


def key_tubes(tubes, tube_b, end):
    for b, (a, t) in zip(tube_b, tubes):
        vtrack = b.add_track(unreal.MovieSceneVisibilityTrack)
        vtrack.set_property_name_and_path("bHidden", "bHidden")
        vsec = vtrack.add_section()
        vsec.set_range(0, end)
        vch = vsec.get_channels_by_type(unreal.MovieSceneScriptingBoolChannel)[0]
        vch.add_key(F(1), True, 0.0, unreal.MovieSceneTimeUnit.DISPLAY_RATE)       # hidden = off
        for frame, glow in t["glow_keys"]:
            if frame <= 1:
                continue
            vch.add_key(F(frame), not (glow > 0.0), 0.0, unreal.MovieSceneTimeUnit.DISPLAY_RATE)


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
    for key, fn in (("chrome", make_chrome), ("cloud", make_cloud), ("tube", make_tube), ("wire", make_wire)):
        m = stage("material " + key, fn)
        if m is not None:
            mats[key] = m
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
        task.enter_progress_frame(1, "Animating Level Sequence")
        if seq is not None:
            stage("animate sequence", animate_sequence, seq, data, actors)
        task.enter_progress_frame(1, "Saving")
        stage("save level", level_sub.save_current_level)
    report()


main()
