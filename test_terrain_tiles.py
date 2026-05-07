"""Quick test: Verify Mapzen terrain tile download for the maps3d.io sample area."""
import sys
sys.path.insert(0, '.')

from core.terrain_generator import (
    _get_tiles_for_bbox, _download_tile_terrarium, _tile_bounds
)
import numpy as np

# Sample bbox from maps3d.io URL:
# ne: lat=41.99245, lng=-8.05319
# sw: lat=41.72539, lng=-8.40445
bbox = {
    'n': 41.99245,
    's': 41.72539,
    'e': -8.05319,
    'w': -8.40445,
}

print(f"Bounding box: {bbox}")
print()

# Test tile calculation at various zoom levels
for zoom in [10, 11, 12, 13, 14]:
    tiles = _get_tiles_for_bbox(bbox, zoom)
    print(f"Zoom {zoom}: {len(tiles)} tiles needed -> {[f'({x},{y})' for x,y,z in tiles[:4]]}{'...' if len(tiles) > 4 else ''}")

print()

# Download one tile at zoom 12 to test
tiles_z12 = _get_tiles_for_bbox(bbox, 12)
tx, ty, tz = tiles_z12[0]
print(f"Downloading test tile ({tx}, {ty}, {tz})...")

elev, _ = _download_tile_terrarium(tx, ty, tz)
if elev is not None:
    print(f"  [OK] Shape: {elev.shape}")
    print(f"  [OK] Elevation range: {elev.min():.1f}m -- {elev.max():.1f}m")
    print(f"  [OK] Mean: {elev.mean():.1f}m")
    
    # Get bounds of this tile
    w, s, e, n = _tile_bounds(tx, ty, tz)
    print(f"  Tile bounds: S={s:.4f} N={n:.4f} W={w:.4f} E={e:.4f}")
else:
    print("  [FAIL] Download failed")

print()
print("Test complete!")
