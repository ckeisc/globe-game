#!/usr/bin/env python3
"""Pack the bundled zoom-4 / zoom-5 tile sets into atlas images.

Why: the globe ships the complete zoom-5 tile sets for the two default
providers (Esri World Imagery + OpenStreetMap Standard, 1,024 tiles each)
plus zoom-4 tiles derived from them (256 each) — 2,560 individual files
under assets/tiles-z5/. That alone pushed the space past the 500-file
publish review limit. This script packs the same tiles into atlas
images under assets/tiles-packed/: 20 atlases per provider, 41 files
total including the manifest, with no change to which tiles are bundled.

Layout (the page's loader in index.html uses the exact same arithmetic —
change one, change both):
  · One atlas is a 2048x2048 JPEG holding an 8x8 grid of 256px tiles
    (64 tiles per atlas).
  · Every tile has a global slot number within its provider:
        zoom 4:  slot = y*16 + x            (slots 0..255)
        zoom 5:  slot = 256 + y*32 + x      (slots 256..1279)
  · atlas index = slot // 64, cell = slot % 64,
    cell column = cell % 8, cell row = cell // 8.
  · Atlas files are named <provider>-<atlas index>.jpg
    (esri-0.jpg .. esri-19.jpg, osm-0.jpg .. osm-19.jpg).
  · The page crops each tile's 256x256 cell out of the atlas on demand,
    so rendering is identical to loading the tile file directly.

Re-running: needs the source tiles in assets/tiles-z5/{esri,osm}/{4,5}/
named <x>_<y>.jpg (esri) / <x>_<y>.png (osm). The sets must be complete
(all 1,280 tiles per provider) — the script refuses to pack a partial
set, so a bundled tile can never silently go missing. After a successful
pack the assets/tiles-z5/ tree can be deleted; it is not referenced by
the page any more. (The zoom-4 tiles were originally derived from the
zoom-5 sets: each z4 tile is its four z5 children composited 2x2 and
downscaled to 256px.)

Usage:  python3 assets/pack-tiles.py
Requires: Pillow  (pip install pillow)
"""

import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install pillow")

# The script ships inside assets/ (the only folder besides index.html
# that the published artifact serves), so the artifact root is its
# parent directory; running a copy from the artifact root also works.
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent if _HERE.name == "assets" else _HERE
SRC = ROOT / "assets" / "tiles-z5"
DST = ROOT / "assets" / "tiles-packed"

TILE = 256          # tile edge, px
GRID = 8            # tiles per atlas edge
PER_ATLAS = GRID * GRID
ZOOMS = (4, 5)
PROVIDERS = {"esri": "jpg", "osm": "png"}


def slot(z, x, y):
    """Global slot of tile z/x/y within its provider (see header)."""
    n = 2 ** z
    idx = y * n + x
    return idx if z == 4 else 256 + idx


def main():
    if not SRC.is_dir():
        sys.exit(f"source tiles not found: {SRC} — nothing to pack "
                 f"(if {DST} already exists, the bundle is already packed)")

    # ---- verify completeness before touching anything ----------------
    tiles = {}  # (provider, z, x, y) -> Path
    missing = []
    for prov, ext in PROVIDERS.items():
        for z in ZOOMS:
            n = 2 ** z
            for y in range(n):
                for x in range(n):
                    p = SRC / prov / str(z) / f"{x}_{y}.{ext}"
                    if p.is_file():
                        tiles[(prov, z, x, y)] = p
                    else:
                        missing.append(str(p))
    if missing:
        sys.exit(f"refusing to pack an incomplete tile set "
                 f"({len(missing)} missing, first: {missing[0]})")
    total_tiles = len(tiles)
    src_files = sum(1 for _ in SRC.rglob("*") if _.is_file())
    src_bytes = sum(p.stat().st_size for p in tiles.values())

    # ---- pack ---------------------------------------------------------
    DST.mkdir(parents=True, exist_ok=True)
    manifest_providers = {}
    out_bytes = 0
    for prov in PROVIDERS:
        n_atlas = (256 + 1024 + PER_ATLAS - 1) // PER_ATLAS  # 1280 tiles -> 20
        atlases = [Image.new("RGB", (GRID * TILE, GRID * TILE))
                   for _ in range(n_atlas)]
        for (pv, z, x, y), path in tiles.items():
            if pv != prov:
                continue
            s = slot(z, x, y)
            ai, cell = divmod(s, PER_ATLAS)
            col, row = cell % GRID, cell // GRID
            with Image.open(path) as im:
                if im.size != (TILE, TILE):
                    sys.exit(f"unexpected tile size {im.size}: {path}")
                atlases[ai].paste(im.convert("RGB"), (col * TILE, row * TILE))
        names = []
        for ai, atlas in enumerate(atlases):
            name = f"{prov}-{ai}.jpg"
            out = DST / name
            # Satellite photos are chroma-tolerant (4:2:0); the OSM map
            # tiles carry thin coloured lines and small text, so they
            # get 4:4:4 (subsampling=0) to stay crisp.
            if prov == "osm":
                atlas.save(out, "JPEG", quality=92, subsampling=0)
            else:
                atlas.save(out, "JPEG", quality=92)
            names.append(name)
            out_bytes += out.stat().st_size
        manifest_providers[prov] = {"atlases": names, "tiles": 1280}

    manifest = {
        "format": "globe-game tile atlases v1",
        "tileSize": TILE,
        "grid": GRID,
        "zooms": list(ZOOMS),
        "slotRule": "zoom 4: slot = y*16 + x; zoom 5: slot = 256 + y*32 + x; "
                    "atlas = slot // 64; cell = slot % 64; "
                    "col = cell % 8; row = cell // 8",
        "providers": manifest_providers,
    }
    (DST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    out_files = sum(1 for _ in DST.iterdir() if _.is_file())
    print(f"packed {total_tiles} tiles "
          f"({src_files} files, {src_bytes / 1e6:.1f} MB) -> "
          f"{out_files} files, {out_bytes / 1e6:.1f} MB in {DST}")
    print("the assets/tiles-z5/ source tree can now be deleted — "
          "the page loads only assets/tiles-packed/")


if __name__ == "__main__":
    main()
