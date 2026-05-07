"""
Terrain Generator — Mapzen/AWS Terrain Tiles Engine

Fetches high-resolution elevation data from AWS-hosted Mapzen terrain tiles
(GeoTIFF format) instead of slow point-by-point SRTM queries.

Inspired by maps3d.io's approach:
  - elevationDataset=mapzen
  - elevationZoom=10..14 (tile zoom level)
  - elevationExaggeration=0.5..5.0
  - elevationVerticalResolution=1..20 (grid step in meters)
"""

import numpy as np
import trimesh
import hashlib
import os
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

# ── Constants ──────────────────────────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "terrain")
os.makedirs(CACHE_DIR, exist_ok=True)

# AWS-hosted Mapzen terrain tiles (public, no auth required)
TILE_URL_GEOTIFF = "https://s3.amazonaws.com/elevation-tiles-prod/geotiff/{z}/{x}/{y}.tif"
TILE_URL_TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

# Maximum concurrent tile downloads
MAX_WORKERS = 8


# ── Tile Math (replaces mercantile for zero-dependency) ───────────────────────

def _lng_to_tile_x(lng, zoom):
    """Convert longitude to tile X coordinate."""
    return int((lng + 180.0) / 360.0 * (1 << zoom))


def _lat_to_tile_y(lat, zoom):
    """Convert latitude to tile Y coordinate."""
    lat_rad = math.radians(lat)
    n = 1 << zoom
    return int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)


def _tile_bounds(x, y, z):
    """Get the geographic bounds (west, south, east, north) of a tile."""
    n = 1 << z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    north_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    south_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))

    north = math.degrees(north_rad)
    south = math.degrees(south_rad)

    return west, south, east, north


def _get_tiles_for_bbox(bbox, zoom):
    """Get all tile (x, y, z) tuples that cover a bounding box."""
    min_x = _lng_to_tile_x(bbox['w'], zoom)
    max_x = _lng_to_tile_x(bbox['e'], zoom)
    min_y = _lat_to_tile_y(bbox['n'], zoom)  # Note: Y is inverted
    max_y = _lat_to_tile_y(bbox['s'], zoom)

    tiles = []
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            tiles.append((x, y, zoom))
    return tiles


# ── Tile Download & Decode ────────────────────────────────────────────────────

def _decode_terrarium_png(png_data):
    """
    Decode Mapzen Terrarium PNG to elevation values.
    Formula: elevation = (R * 256 + G + B / 256) - 32768
    """
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(png_data)).convert('RGB')
    data = np.array(img, dtype=np.float64)

    r = data[:, :, 0]
    g = data[:, :, 1]
    b = data[:, :, 2]

    elevation = (r * 256.0 + g + b / 256.0) - 32768.0
    return elevation


def _download_tile_terrarium(x, y, z):
    """Download a single Terrarium PNG tile and decode to elevation array."""
    import requests

    # Check cache first
    cache_key = f"terrarium_{z}_{x}_{y}"
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.npy")

    if os.path.exists(cache_path):
        return np.load(cache_path), (x, y, z)

    url = TILE_URL_TERRARIUM.format(z=z, x=x, y=y)
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "3DCorrida/2.0"})
        if resp.status_code == 200:
            elevation = _decode_terrarium_png(resp.content)
            np.save(cache_path, elevation)
            return elevation, (x, y, z)
        else:
            return None, (x, y, z)
    except Exception:
        return None, (x, y, z)


def _download_tile_geotiff(x, y, z):
    """Download a single GeoTIFF tile and extract elevation array."""
    import requests

    cache_key = f"geotiff_{z}_{x}_{y}"
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.npy")

    if os.path.exists(cache_path):
        return np.load(cache_path), (x, y, z)

    url = TILE_URL_GEOTIFF.format(z=z, x=x, y=y)
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "3DCorrida/2.0"})
        if resp.status_code == 200:
            try:
                import rasterio
                import io as _io
                with rasterio.open(_io.BytesIO(resp.content)) as src:
                    elevation = src.read(1).astype(np.float64)
            except ImportError:
                # Fallback to terrarium if rasterio not available
                return _download_tile_terrarium(x, y, z)

            np.save(cache_path, elevation)
            return elevation, (x, y, z)
        else:
            return None, (x, y, z)
    except Exception:
        return None, (x, y, z)


# ── Main Elevation Fetch ──────────────────────────────────────────────────────

def fetch_elevation_grid(bbox, zoom=13, dataset="mapzen", vertical_resolution=10):
    """
    Fetch elevation data for a bounding box using Mapzen/AWS terrain tiles.

    Parameters
    ----------
    bbox : dict
        Bounding box with keys 'n', 's', 'e', 'w'
    zoom : int
        Tile zoom level (10-14). Higher = more detail but more tiles.
        maps3d.io default: 13
    dataset : str
        "mapzen" (default) — uses Terrarium PNG encoding
        "geotiff" — uses GeoTIFF format (requires rasterio)
    vertical_resolution : float
        Target grid spacing in approximate meters. Lower = more vertices.

    Returns
    -------
    lats, lons, grid : arrays
        Regularly-spaced latitude, longitude, and elevation grid
    """
    tiles = _get_tiles_for_bbox(bbox, zoom)
    n_tiles = len(tiles)

    st.info(f"🗺️ Downloading {n_tiles} terrain tile(s) at zoom {zoom}...")

    # Choose download function based on dataset
    download_fn = _download_tile_geotiff if dataset == "geotiff" else _download_tile_terrarium

    # Download tiles in parallel
    tile_data = {}
    progress = st.progress(0, text="Downloading terrain tiles...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_fn, x, y, z): (x, y, z)
                   for x, y, z in tiles}

        completed = 0
        for future in as_completed(futures):
            elevation, (tx, ty, tz) = future.result()
            if elevation is not None:
                tile_data[(tx, ty)] = elevation
            completed += 1
            progress.progress(completed / n_tiles,
                              text=f"Downloading terrain tiles... {completed}/{n_tiles}")

    progress.empty()

    if not tile_data:
        st.error("❌ No elevation tiles could be downloaded. Using flat terrain.")
        resolution = 50
        lats = np.linspace(bbox['s'], bbox['n'], resolution)
        lons = np.linspace(bbox['w'], bbox['e'], resolution)
        return lats, lons, np.zeros((resolution, resolution))

    # ── Assemble tile mosaic ──────────────────────────────────────────────
    # Find the tile grid extent
    all_tx = sorted(set(k[0] for k in tile_data))
    all_ty = sorted(set(k[1] for k in tile_data))

    # Each tile is 256x256 pixels (standard slippy map tile size)
    tile_size = list(tile_data.values())[0].shape[0]  # Usually 256 or 512

    # Build the full mosaic
    mosaic_h = len(all_ty) * tile_size
    mosaic_w = len(all_tx) * tile_size
    mosaic = np.zeros((mosaic_h, mosaic_w), dtype=np.float64)

    for (tx, ty), elev in tile_data.items():
        col_idx = all_tx.index(tx)
        row_idx = all_ty.index(ty)

        r0 = row_idx * tile_size
        c0 = col_idx * tile_size

        # Handle tiles that might be different sizes
        h, w = elev.shape
        mosaic[r0:r0 + h, c0:c0 + w] = elev

    # ── Compute geographic extent of the mosaic ──────────────────────────
    mosaic_west, mosaic_south, _, _ = _tile_bounds(all_tx[0], all_ty[-1], zoom)
    _, _, mosaic_east, mosaic_north = _tile_bounds(all_tx[-1], all_ty[0], zoom)

    # ── Create regular lat/lon grid and sample from mosaic ───────────────
    # Calculate output resolution based on vertical_resolution parameter
    lat_range = bbox['n'] - bbox['s']
    lon_range = bbox['e'] - bbox['w']

    # Approximate meters per degree at this latitude
    mid_lat = (bbox['n'] + bbox['s']) / 2.0
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(mid_lat))

    extent_lat_m = lat_range * meters_per_deg_lat
    extent_lon_m = lon_range * meters_per_deg_lon

    # Grid resolution from vertical_resolution (meters between grid points)
    res_lat = max(10, int(extent_lat_m / vertical_resolution))
    res_lon = max(10, int(extent_lon_m / vertical_resolution))

    # Cap at reasonable limits
    res_lat = min(res_lat, 500)
    res_lon = min(res_lon, 500)

    lats = np.linspace(bbox['s'], bbox['n'], res_lat)
    lons = np.linspace(bbox['w'], bbox['e'], res_lon)

    # Sample elevations from the mosaic using bilinear interpolation
    from scipy.interpolate import RegularGridInterpolator

    mosaic_lats = np.linspace(mosaic_north, mosaic_south, mosaic_h)  # N to S (image order)
    mosaic_lons = np.linspace(mosaic_west, mosaic_east, mosaic_w)

    # RegularGridInterpolator requires monotonically increasing axes
    # mosaic_lats is N→S (decreasing), flip it
    mosaic_lats_asc = mosaic_lats[::-1]
    mosaic_flipped = mosaic[::-1, :]  # Flip rows to match ascending lat

    interpolator = RegularGridInterpolator(
        (mosaic_lats_asc, mosaic_lons), mosaic_flipped,
        method='linear', bounds_error=False, fill_value=0.0
    )

    # Create query grid
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    query_points = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])

    grid = interpolator(query_points).reshape(res_lat, res_lon)

    st.success(
        f"✅ Terrain: {res_lat}×{res_lon} grid from {n_tiles} tiles "
        f"(zoom {zoom}, ~{vertical_resolution}m resolution)"
    )

    return lats, lons, grid


# ── Legacy fallback (kept for compatibility) ──────────────────────────────────

def fetch_elevation_grid_srtm(bbox, resolution=50):
    """
    Legacy: Fetch elevation data using srtm.py (point-by-point).
    Kept as fallback if AWS tiles are unavailable.
    """
    lats = np.linspace(bbox['s'], bbox['n'], resolution)
    lons = np.linspace(bbox['w'], bbox['e'], resolution)

    try:
        import srtm
        elevation_data = srtm.get_data()

        grid = np.zeros((resolution, resolution))
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                ele = elevation_data.get_elevation(lat, lon)
                grid[i, j] = ele if ele is not None else 0

        st.success(f"✅ SRTM fallback: {resolution}×{resolution} grid")
        return lats, lons, grid

    except Exception as e:
        st.error(f"❌ SRTM fallback also failed: {e}")
        return lats, lons, np.zeros((resolution, resolution))


# ── Terrain Mesh Creation ─────────────────────────────────────────────────────

def create_terrain_mesh(lats, lons, grid, local_crs, cx=0.0, cy=0.0,
                        xy_scale=1.0, terrain_exaggeration=1.0,
                        base_thickness=3.0, hollow=False, wall_thickness=2.0):
    """
    Create a SOLID terrain block: terrain surface on top, flat bottom.
    This replaces both the base plate and terrain surface.

    Parameters
    ----------
    hollow : bool
        If True, create a hollow shell (saves material for 3D printing).
    wall_thickness : float
        Wall thickness in mm for hollow mode.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    res_lat = len(lats)
    res_lon = len(lons)

    # Create meshgrid in lat/lon
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    flat_lons = lon_grid.flatten()
    flat_lats = lat_grid.flatten()
    flat_elevs = grid.flatten()

    # Project to local CRS
    points_gdf = gpd.GeoDataFrame(
        geometry=[Point(lon, lat) for lon, lat in zip(flat_lons, flat_lats)],
        crs="EPSG:4326"
    )
    points_proj = points_gdf.to_crs(local_crs)

    # Apply physical translation and scaling
    xs = np.array([(p.x - cx) * xy_scale for p in points_proj.geometry])
    ys = np.array([(p.y - cy) * xy_scale for p in points_proj.geometry])

    # Apply terrain exaggeration and scale Z to physical mm
    min_elev = np.min(flat_elevs)
    zs_top = (flat_elevs - min_elev) * xy_scale * terrain_exaggeration

    # Bottom Z
    z_bottom = -base_thickness

    n = len(xs)

    # ── Build solid block vertices ──
    top_verts = np.column_stack([xs, ys, zs_top])
    bot_verts = np.column_stack([xs, ys, np.full(n, z_bottom)])
    vertices = np.vstack([top_verts, bot_verts])

    faces = []

    # ── Top surface faces (normal up) ──
    for i in range(res_lat - 1):
        for j in range(res_lon - 1):
            idx = i * res_lon + j
            faces.append([idx, idx + res_lon, idx + 1])
            faces.append([idx + 1, idx + res_lon, idx + res_lon + 1])

    # ── Bottom surface faces (normal down, reversed winding) ──
    for i in range(res_lat - 1):
        for j in range(res_lon - 1):
            idx = n + i * res_lon + j
            faces.append([idx, idx + 1, idx + res_lon])
            faces.append([idx + 1, idx + res_lon + 1, idx + res_lon])

    # ── Side walls ──
    # South edge (i=0)
    for j in range(res_lon - 1):
        t0, t1 = j, j + 1
        b0, b1 = n + j, n + j + 1
        faces.append([t0, b0, t1])
        faces.append([t1, b0, b1])
    # North edge (i=res_lat-1)
    for j in range(res_lon - 1):
        row = res_lat - 1
        t0, t1 = row * res_lon + j, row * res_lon + j + 1
        b0, b1 = n + row * res_lon + j, n + row * res_lon + j + 1
        faces.append([t0, t1, b0])
        faces.append([t1, b1, b0])
    # West edge (j=0)
    for i in range(res_lat - 1):
        t0, t1 = i * res_lon, (i + 1) * res_lon
        b0, b1 = n + i * res_lon, n + (i + 1) * res_lon
        faces.append([t0, t1, b0])
        faces.append([t1, b1, b0])
    # East edge (j=res_lon-1)
    for i in range(res_lat - 1):
        col = res_lon - 1
        t0, t1 = i * res_lon + col, (i + 1) * res_lon + col
        b0, b1 = n + i * res_lon + col, n + (i + 1) * res_lon + col
        faces.append([t0, b0, t1])
        faces.append([t1, b0, b1])

    faces = np.array(faces)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

    # ── Hollow mode (for 3D printing) ──
    if hollow and wall_thickness > 0:
        mesh = _make_hollow(mesh, zs_top, xs, ys, n,
                            res_lat, res_lon, z_bottom, wall_thickness)

    xs_grid = xs.reshape(res_lat, res_lon)
    ys_grid = ys.reshape(res_lat, res_lon)
    zs_grid = zs_top.reshape(res_lat, res_lon)

    return mesh, xs_grid, ys_grid, zs_grid


def _make_hollow(mesh, zs_top, xs, ys, n, res_lat, res_lon,
                 z_bottom, wall_thickness):
    """
    Create a hollow version of the terrain mesh by offsetting the bottom
    surface upward to follow the terrain profile with a constant wall thickness.
    This saves 40-60% material on 3D prints.
    """
    # Create inner bottom surface that follows terrain - wall_thickness
    inner_z = zs_top - wall_thickness
    # Ensure inner surface doesn't go below the original bottom
    inner_z = np.maximum(inner_z, z_bottom + 0.5)

    # Rebuild bottom vertices with the offset surface
    vertices = mesh.vertices.copy()
    # Update bottom verts (indices n..2n-1)
    vertices[n:, 2] = inner_z

    mesh.vertices = vertices
    return mesh


# ── Terrain Interpolator ──────────────────────────────────────────────────────

class TerrainInterpolator:
    """Interpolates ground height at any XY point based on the terrain grid."""

    def __init__(self, xs_grid, ys_grid, zs_grid):
        from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

        points = np.column_stack([xs_grid.flatten(), ys_grid.flatten()])
        values = zs_grid.flatten()

        # Linear interpolation for interior points
        self._linear = LinearNDInterpolator(points, values)
        # Nearest-neighbor fallback for points outside the convex hull (edges)
        self._nearest = NearestNDInterpolator(points, values)

    def get_height(self, x, y):
        """Get interpolated ground height at (x, y) coordinates."""
        xy = np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])
        z = self._linear(xy)
        # Fill NaN (outside convex hull) with nearest neighbor
        mask = np.isnan(z)
        if np.any(mask):
            z[mask] = self._nearest(xy[mask])
        return z.ravel()
