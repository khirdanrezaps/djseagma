"""
render_smoke_plates.py - render the simulated smoke (scripts/bake_smoke_vdb.py --npy) with Cycles
into looping RGBA flipbook atlases for Unreal smoke cards.

Elements (sizes in metres, same as the Blender scene):
  gate   7.6 x 3 x 18   -> used for both cloud gates and the side pillars
  wall   26 x 4 x 14    -> background behind the logo
  floor  46 x 10 x 4    -> rolling smoke bank on the floor
For every frame the periodic simulation tile is repeated over the element box, eroded towards
the box faces (billowy edges), lit from the top-left like the reference and rendered with a
transparent background. Frames are packed into SourceAssets/SmokePlates/T_Smoke_<elem>.png plus
smoke_plates.json (grid layout) for import_and_animate.py.

Run with the bpy module or Blender:  python scripts/render_smoke_plates.py <smoke_frames.npy>
"""
import json
import math
import os
import shutil
import sys
import tempfile

import bpy
import numpy as np
from scipy.ndimage import gaussian_filter, zoom

try:
    import openvdb as vdb
except ImportError:
    import pyopenvdb as vdb
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "SourceAssets", "SmokePlates"))
FRAMES = int(os.environ.get("PLATE_FRAMES", 80))
SAMPLES = 16

ELEMENTS = {
    #        size m (x, depth, z)  tile m  erosion weights   thr   px width  cols
    "gate": ((7.6, 3.0, 18.0), 6.0, (0.75, 0.5, 0.04), 0.44, 384, 10),
    "wall": ((26.0, 4.0, 14.0), 8.0, (0.04, 0.45, 0.06), 0.34, 768, 8),
    "floor": ((46.0, 10.0, 4.0), 8.0, (0.02, 0.10, 0.85), 0.40, 1536, 4),
}


def smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


MOD_RNG = np.random.default_rng(99)


def element_grid(tile, size, tile_m, weights, thr, offset):
    n = tile.shape[0]
    vox = tile_m / n
    dims = [max(8, int(round(s / vox))) for s in size]
    idx = [((np.arange(d) + o) % n) for d, o in zip(dims, offset)]
    d = zoom(tile[np.ix_(*idx)], 2, order=1)          # upsample before thresholding: no voxel steps
    vox /= 2.0
    dims = list(d.shape)
    rel = [np.linspace(-1, 1, k) for k in dims]
    RX, RY, RZ = np.meshgrid(*rel, indexing="ij")
    if weights[2] > 0.5:                      # floor: dense at the bottom, billows on top
        e = weights[2] * np.clip((RZ + 1) / 2, 0, 1) ** 2 + weights[0] * RX ** 8 + weights[1] * RY ** 2
    else:
        e = weights[0] * RX ** 2 + weights[1] * RY ** 2 + weights[2] * RZ ** 8
    # static large-scale variation so repeated tiles don't read as a pattern
    mod = gaussian_filter(np.random.default_rng(int(sum(dims))).standard_normal(d.shape).astype(np.float32), sigma=[k / 6.0 for k in d.shape],
                          mode="wrap")
    mod = (mod - mod.mean()) / (mod.std() + 1e-6)
    dens = smoothstep(d - e + 0.12 * mod, thr - 0.09, thr + 0.09).astype(np.float32)
    return dens, vox, dims


def setup_scene(name, size, px):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.render.resolution_x = px
    sc.render.resolution_y = int(round(px * size[2] / size[0]))
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.004, 0.004, 0.0045, 1)

    vol = bpy.data.volumes.new(name)
    ob = bpy.data.objects.new(name, vol)
    sc.collection.objects.link(ob)
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    at = nt.nodes.new("ShaderNodeAttribute")
    at.attribute_name = "density"
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 12.0
    nt.links.new(at.outputs["Fac"], mul.inputs[0])
    nt.links.new(mul.outputs[0], pv.inputs["Density"])
    pv.inputs["Color"].default_value = (0.85, 0.85, 0.87, 1)
    pv.inputs["Anisotropy"].default_value = 0.2
    nt.links.new(pv.outputs[0], out.inputs["Volume"])
    vol.materials.append(mat)

    # key from top-left-front (reference lighting), weak front fill
    key = bpy.data.objects.new("key", bpy.data.lights.new("key", "AREA"))
    sc.collection.objects.link(key)
    key.data.size = max(size) * 0.6
    key.data.energy = 2400.0 * max(size) ** 2 / 40.0
    key.location = (-size[0] * 0.6, -size[1] * 4 - 6, size[2] * 1.4)
    key.rotation_euler = (math.radians(50), math.radians(-25), 0)
    fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "AREA"))
    sc.collection.objects.link(fill)
    fill.data.size = max(size)
    fill.data.energy = 40.0 * max(size) ** 2 / 40.0
    fill.location = (0, -max(size) * 1.5, size[2] * 0.5)
    fill.rotation_euler = (math.radians(90), 0, 0)

    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = size[0]
    cam.location = (0, -50, 0)
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.clip_end = 200
    sc.camera = cam
    return sc, ob, vol


def render_element(name, cfg, frames_npy, tmp):
    size, tile_m, weights, thr, px, cols = cfg
    sc, ob, vol = setup_scene(name, size, px)
    nsim = frames_npy.shape[0]
    imgs = []
    off = {"gate": (0, 0, 0), "wall": (17, 9, 31), "floor": (41, 23, 5)}[name]
    for i in range(FRAMES):
        tile = frames_npy[int(round(i * nsim / FRAMES)) % nsim].astype(np.float32)
        dens, vox, dims = element_grid(tile, size, tile_m, weights, thr, off)
        g = vdb.FloatGrid()
        g.copyFromArray(dens)
        g.name = "density"
        g.transform = vdb.createLinearTransform(voxelSize=1.0)
        path = os.path.join(tmp, "%s_%04d.vdb" % (name, i))
        vdb.write(path, grids=[g])
        vol.filepath = path
        vol.is_sequence = False
        vol.grids.load()
        # voxel grid -> metres, centred on the origin
        ob.scale = (vox, vox, vox)
        ob.location = (-dims[0] * vox / 2, -dims[1] * vox / 2, -dims[2] * vox / 2)
        vol.update_tag()
        bpy.context.view_layer.update()
        sc.render.filepath = os.path.join(tmp, "%s_%04d.png" % (name, i))
        bpy.ops.render.render(write_still=True)
        imgs.append(Image.open(sc.render.filepath).convert("RGBA"))
        bpy.data.volumes[name].grids.unload()
        print("PLATE %s %d/%d" % (name, i + 1, FRAMES), flush=True)
    w, h = imgs[0].size
    rows = int(math.ceil(FRAMES / cols))
    atlas = Image.new("RGBA", (w * cols, h * rows), (0, 0, 0, 0))
    for i, im in enumerate(imgs):
        atlas.paste(im, ((i % cols) * w, (i // cols) * h))
    path = os.path.join(OUT, "T_Smoke_%s.png" % name.capitalize())
    atlas.save(path, optimize=True)
    return {"file": os.path.basename(path), "cols": cols, "rows": rows, "frames": FRAMES,
            "frame_px": [w, h], "size_m": list(size)}


def main():
    frames = np.load(sys.argv[1])
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else list(ELEMENTS)
    os.makedirs(OUT, exist_ok=True)
    meta_path = os.path.join(OUT, "smoke_plates.json")
    meta = json.load(open(meta_path)) if os.path.isfile(meta_path) else {}
    tmp = tempfile.mkdtemp(prefix="smoke_plates_")
    try:
        for name in only:
            meta[name] = render_element(name, ELEMENTS[name], frames, tmp)
            json.dump(meta, open(meta_path, "w"), indent=1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PLATES DONE", meta)


if __name__ == "__main__":
    main()
