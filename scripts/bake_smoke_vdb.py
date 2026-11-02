"""
bake_smoke_vdb.py - simulate dense, churning 3D smoke and export a seamless looping, tileable
OpenVDB sequence for Unreal Heterogeneous Volumes.

Look target (reference video): thick cumulus-like smoke that keeps rolling and billowing in
place with real 3D volume and deep self-shadowing - not a scrolling 2D texture.

Solver: incompressible smoke on a periodic N^3 grid (numpy + scipy)
  * semi-Lagrangian advection of velocity and density (trilinear, wrap-around)
  * pressure projection in Fourier space (exactly divergence free)
  * vorticity confinement for curly billows
  * density buoyancy + slowly evolving large-scale divergence-free forcing keeps it churning
  * gentle density sharpening keeps the cloud dense with crisp billow edges
Because the domain is periodic, every frame tiles seamlessly in all three axes; the tail of
the recording is cross-faded into its head so the sequence also loops in time.

Output: SourceAssets/VDB/Smoke/SeagmaSmoke_0000.vdb ...  (grid "density", half float)

Run with any Python that has numpy + scipy + the openvdb module (e.g. Blender's bundled one):
  python scripts/bake_smoke_vdb.py [--res 64] [--frames 192] [--blend 36]
"""
import argparse
import math
import os
import shutil
import sys
import time

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

try:
    import openvdb as vdb
except ImportError:
    try:
        import pyopenvdb as vdb
    except ImportError:
        vdb = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "SourceAssets", "VDB", "Smoke"))

ap = argparse.ArgumentParser()
ap.add_argument("--res", type=int, default=64)
ap.add_argument("--frames", type=int, default=192, help="frames in the final loop")
ap.add_argument("--blend", type=int, default=36, help="cross-fade frames that close the loop")
ap.add_argument("--warmup", type=int, default=80)
ap.add_argument("--seed", type=int, default=2026)
ap.add_argument("--out", default=OUT_DIR)
ap.add_argument("--npy", default="", help="also save the frames as one .npy (for previews)")
args = ap.parse_args()

N = args.res
rng = np.random.default_rng(args.seed)
k1 = np.fft.fftfreq(N) * N
KX, KY, KZ = np.meshgrid(k1, k1, k1, indexing="ij")
K2 = KX ** 2 + KY ** 2 + KZ ** 2
K2[0, 0, 0] = 1.0
KMAG = np.sqrt(K2)
GRID = np.stack(np.meshgrid(*[np.arange(N, dtype=np.float32)] * 3, indexing="ij"))


# ------------------------------------------------------------------ initial cloud density
def fbm(slope, kmin, kmax):
    white = rng.standard_normal((N, N, N))
    amp = np.where((KMAG >= kmin) & (KMAG <= kmax), KMAG ** -slope, 0.0)
    f = np.real(np.fft.ifftn(np.fft.fftn(white) * amp))
    f -= f.min()
    return f / f.max()


def puffs(cells=4):
    pts = (np.stack(np.meshgrid(*[np.arange(cells)] * 3, indexing="ij"), -1)
           + rng.random((cells, cells, cells, 3))).reshape(-1, 3) / cells
    rad = rng.uniform(0.6, 1.0, len(pts))
    g = (np.arange(N) + 0.5) / N
    X, Y, Z = np.meshgrid(g, g, g, indexing="ij")
    out = np.full((N, N, N), 10.0)
    for p, r in zip(pts, rad):
        d = np.sqrt(((X - p[0] + .5) % 1 - .5) ** 2 + ((Y - p[1] + .5) % 1 - .5) ** 2 +
                    ((Z - p[2] + .5) % 1 - .5) ** 2) / r
        np.minimum(out, d, out=out)
    return np.clip(1.0 - out * cells * 0.75, 0, 1)


def smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ solver pieces
def project(u):
    uh = [np.fft.fftn(c) for c in u]
    div = KX * uh[0] + KY * uh[1] + KZ * uh[2]
    for c, k in zip(uh, (KX, KY, KZ)):
        c -= k * div / K2
    return np.stack([np.real(np.fft.ifftn(c)) for c in uh]).astype(np.float32)


def advect(field, u, dt):
    coords = GRID - dt * u
    if field.ndim == 3:
        return map_coordinates(field, coords, order=1, mode="grid-wrap").astype(np.float32)
    return np.stack([map_coordinates(c, coords, order=1, mode="grid-wrap") for c in field]).astype(np.float32)


def grad(f, axis):
    return 0.5 * (np.roll(f, -1, axis) - np.roll(f, 1, axis))


def curl(u):
    return np.stack([grad(u[2], 1) - grad(u[1], 2),
                     grad(u[0], 2) - grad(u[2], 0),
                     grad(u[1], 0) - grad(u[0], 1)])


def vorticity_confinement(u, eps):
    w = curl(u)
    mag = np.sqrt((w ** 2).sum(0)) + 1e-6
    n = np.stack([grad(mag, a) for a in range(3)])
    n /= np.sqrt((n ** 2).sum(0)) + 1e-6
    f = np.stack([n[1] * w[2] - n[2] * w[1], n[2] * w[0] - n[0] * w[2], n[0] * w[1] - n[1] * w[0]])
    return eps * f


class Forcing:
    """Large-scale divergence-free velocity forcing whose modes slowly rotate in phase."""

    def __init__(self, kmin=1.0, kmax=3.2, modes_amp=1.0):
        shell = (KMAG >= kmin) & (KMAG <= kmax)
        self.base = [np.where(shell, rng.standard_normal((N, N, N)) + 1j * rng.standard_normal((N, N, N)), 0)
                     for _ in range(3)]
        # remove the compressive part
        div = KX * self.base[0] + KY * self.base[1] + KZ * self.base[2]
        for c, k in zip(self.base, (KX, KY, KZ)):
            c -= k * div / K2
        self.omega = np.where(shell, rng.uniform(0.02, 0.06, (N, N, N)), 0)
        self.amp = modes_amp

    def __call__(self, t):
        ph = np.exp(1j * self.omega * t)
        f = np.stack([np.real(np.fft.ifftn(c * ph)) for c in self.base])
        return (self.amp * f / (np.abs(f).max() + 1e-6)).astype(np.float32)


FORCE, BUOY, VORT, DAMP, CONTRAST, DETAIL = 0.022, 0.012, 0.035, 0.97, 1.03, 0.5


def run():
    d = (0.4 * fbm(1.7, 1.5, N / 3) + 0.4 * puffs(cells=5) + 0.2 * fbm(1.2, 6, N / 2)).astype(np.float32)
    d = smoothstep(d, 0.35, 0.75).astype(np.float32)
    target_mean = float(d.mean())
    u = np.zeros((3, N, N, N), np.float32)
    force = Forcing()
    dt = 1.0
    total = args.warmup + args.frames + args.blend
    rec = []
    t0 = time.time()
    for step in range(total):
        u += FORCE * force(step)                                   # slow large-scale churn
        u[2] += BUOY * (d - d.mean())                              # light buoyancy -> rolling up
        u += vorticity_confinement(u, VORT)                        # curl at the billow scale
        u *= DAMP
        u = project(advect(u, u, dt))
        d = advect(d, u, dt)
        # keep soft round billows: tiny blur against grid noise, mild contrast against blur
        d = gaussian_filter(d, 0.35, mode="wrap")
        d = np.clip(0.5 + (d - 0.5) * CONTRAST, 0, 1)
        d += (target_mean - d.mean())
        d = np.clip(d, 0, 1).astype(np.float32)
        if step >= args.warmup:
            rec.append(d.copy())
        if step % 20 == 0:
            vmax = float(np.sqrt((u ** 2).sum(0)).max())
            print("step %d/%d  |u|max=%.2f  mean=%.3f  %.1fs" % (step, total, vmax, d.mean(), time.time() - t0),
                  flush=True)
    # close the loop in time
    F, B = args.frames, args.blend
    # cumulus "cauliflower" detail: two small-scale puff fields cross-faded with a period of F
    # frames (loops with the sequence) and warped by the sim, so billow surfaces stay lumpy
    det = [0.8 * puffs(cells=max(8, N // 6)) + 0.2 * fbm(1.4, N / 10, N / 3) for _ in range(2)]
    out = []
    for i in range(F):
        a = rec[i]
        if i < B:
            w = 0.5 - 0.5 * math.cos(math.pi * (i + 0.5) / B)
            a = rec[i + F] * (1 - w) + rec[i] * w
        ph = math.pi * i / F
        dt_ = det[0] * math.cos(ph) ** 2 + det[1] * math.sin(ph) ** 2
        a = np.clip(a + DETAIL * (dt_ - 0.5) * smoothstep(a, 0.15, 0.5), 0, 1)
        out.append(a.astype(np.float32))
    return out


def write(frames):
    if vdb is None:
        raise SystemExit("openvdb module not found - run with Blender's Python")
    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out)
    total = 0
    for i, a in enumerate(frames):
        a = np.where(a < 0.02, 0.0, a).astype(np.float32)
        g = vdb.FloatGrid()
        g.copyFromArray(a)
        g.name = "density"
        g.gridClass = vdb.GridClass.FOG_VOLUME
        g.transform = vdb.createLinearTransform(voxelSize=1.0)
        g.saveFloatAsHalf = True
        g.prune(0.0)
        p = os.path.join(args.out, "SeagmaSmoke_%04d.vdb" % i)
        vdb.write(p, grids=[g])
        total += os.path.getsize(p)
    print("wrote %d frames (%d^3) to %s  total %.1f MB" % (len(frames), N, args.out, total / 1e6))


if __name__ == "__main__":
    frames = run()
    if args.npy:
        np.save(args.npy, np.stack(frames).astype(np.float16))
    write(frames)
    sys.exit(0)
