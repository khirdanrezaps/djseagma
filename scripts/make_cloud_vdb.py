"""
make_cloud_vdb.py - bake a tileable 3D "cumulus" noise volume to OpenVDB for Unreal.

Output: SourceAssets/VDB/T_SeagmaCloudNoise.vdb  (one float grid named "density", 0..1)

The volume is periodic on all three axes, so Unreal can sample it with frac(UVW) and
scroll it forever without seams. The cloud shape, erosion and motion are done in the
Unreal volume material (scripts/import_and_animate.py), same idea as the Blender
volumetric material (scripts/build_logo_anim.py).

Needs numpy + the openvdb Python module that ships inside Blender / the bpy wheel:
  blender -b --python-exit-code 1 -P scripts/make_cloud_vdb.py
or with the bpy wheel's interpreter, pointing PYTHONPATH at bpy's bundled site-packages.
"""
import os
import sys

import numpy as np

try:
    import openvdb as vdb
except ImportError:  # older Blender builds
    import pyopenvdb as vdb

RES = 128          # voxels per side (one tile)
SEED = 2026
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SourceAssets", "VDB",
                   "T_SeagmaCloudNoise.vdb")


def periodic_fbm(res, rng, slope=1.7, kmin=1.5, kmax=40.0):
    """Band-limited fractal noise; filtering white noise in Fourier space makes it periodic."""
    white = rng.standard_normal((res, res, res)).astype(np.float32)
    f = np.fft.fftfreq(res) * res
    kx, ky, kz = np.meshgrid(f, f, f, indexing="ij")
    k = np.sqrt(kx * kx + ky * ky + kz * kz)
    amp = np.where((k >= kmin) & (k <= kmax), 1.0 / np.maximum(k, 1e-6) ** slope, 0.0)
    field = np.real(np.fft.ifftn(np.fft.fftn(white) * amp)).astype(np.float32)
    field -= field.min()
    return field / field.max()


def periodic_worley_puffs(res, rng, cells=6):
    """1 - distance to nearest feature point (wrapping), gives round cumulus puffs."""
    pts = (np.stack(np.meshgrid(*[np.arange(cells)] * 3, indexing="ij"), -1)
           + rng.random((cells, cells, cells, 3))) / cells           # one point per cell, 0..1
    pts = pts.reshape(-1, 3)
    radius = rng.uniform(0.6, 1.0, len(pts)).astype(np.float32)      # varied puff sizes
    g = (np.arange(res, dtype=np.float32) + 0.5) / res
    out = np.full((res, res, res), 10.0, np.float32)
    X, Y, Z = np.meshgrid(g, g, g, indexing="ij")
    for p, r in zip(pts, radius):
        d = np.sqrt(((X - p[0] + 0.5) % 1.0 - 0.5) ** 2 +
                    ((Y - p[1] + 0.5) % 1.0 - 0.5) ** 2 +
                    ((Z - p[2] + 0.5) % 1.0 - 0.5) ** 2) / r
        np.minimum(out, d, out=out)
    out = 1.0 - out * cells * 0.75
    return np.clip(out, 0.0, 1.0)


def main():
    rng = np.random.default_rng(SEED)
    fbm = periodic_fbm(RES, rng)
    puffs = periodic_worley_puffs(RES, rng)
    detail = periodic_fbm(RES, rng, slope=1.2, kmin=8.0, kmax=60.0)
    dens = 0.45 * fbm + 0.40 * puffs + 0.15 * detail
    dens -= dens.min()
    dens = (dens / dens.max()).astype(np.float32)

    grid = vdb.FloatGrid()
    grid.copyFromArray(dens)
    grid.name = "density"
    grid.gridClass = vdb.GridClass.FOG_VOLUME
    grid.transform = vdb.createLinearTransform(voxelSize=1.0)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    vdb.write(os.path.abspath(OUT), grids=[grid])
    print("wrote %s  res=%d  active=%d  mean=%.3f" % (os.path.abspath(OUT), RES, grid.activeVoxelCount(),
                                                      float(dens.mean())))


if __name__ == "__main__":
    main()
    sys.exit(0)
