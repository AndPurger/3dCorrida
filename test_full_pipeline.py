"""Full pipeline test: GPX -> OSM -> Mesh (without Streamlit)"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Monkey-patch streamlit for non-interactive use
import types
class FakeSt:
    def _p(self, *a):
        try: print(*a)
        except: print(str(a).encode('ascii','replace').decode())
    def write(self, *a, **kw): self._p(*a)
    def info(self, *a, **kw): self._p("[INFO]", *a)
    def success(self, *a, **kw): self._p("[OK]", *a)
    def warning(self, *a, **kw): self._p("[WARN]", *a)
    def error(self, *a, **kw): self._p("[ERR]", *a)
    def spinner(self, *a, **kw):
        class CM:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return CM()
    def progress(self, *a, **kw):
        class P:
            def progress(self, *a, **kw): pass
            def empty(self): pass
        return P()
    def subheader(self, *a, **kw): print("---", *a)

import core.map_generator as mg
import core.terrain_generator as tg
mg.st = FakeSt()
tg.st = FakeSt()

from core.gpx_parser import GPXParser
from core.map_generator import MapGenerator
from core.mesh_builder import MeshBuilder
from core.terrain_generator import fetch_elevation_grid, create_terrain_mesh, TerrainInterpolator

# Load GPX
gpx_path = os.path.join(os.path.dirname(__file__), "GPX Sample file", "run.gpx")
with open(gpx_path, 'r', encoding='utf-8') as f:
    content = f.read()

parser = GPXParser(content)
points = parser.get_points()
lats = [p[0] for p in points]
lons = [p[1] for p in points]
border_pct = 15
margin_deg = max(max(lats)-min(lats), max(lons)-min(lons)) * (border_pct/100.0)
bbox = parser.get_bounding_box(margin=margin_deg)
print(f"GPX: {len(points)} points")
print(f"BBox: {bbox}")

gpx_gdf = parser.get_geodataframe()
gpx_gdf_2d = parser.get_geodataframe_2d()
local_crs = gpx_gdf_2d.estimate_utm_crs()
gpx_gdf_proj = gpx_gdf.to_crs(local_crs)
print(f"CRS: {local_crs}")

# OSM download
print("\n=== OSM DOWNLOAD ===")
map_gen = MapGenerator(bbox)
streets_gdf = map_gen.get_streets()
has_streets = not getattr(streets_gdf, 'empty', True)
print(f"Streets: {len(streets_gdf) if has_streets else 0}")

buildings_gdf = map_gen.get_buildings()
has_buildings = not getattr(buildings_gdf, 'empty', True)
print(f"Buildings: {len(buildings_gdf) if has_buildings else 0}")

if has_streets:
    streets_gdf = streets_gdf.to_crs(local_crs)
if has_buildings:
    buildings_gdf = buildings_gdf.to_crs(local_crs)

# Transform to mm
bounds = gpx_gdf_proj.total_bounds
cx = (bounds[0] + bounds[2]) / 2.0
cy = (bounds[1] + bounds[3]) / 2.0
dx = bounds[2] - bounds[0]
dy = bounds[3] - bounds[1]

max_print_size = 180
margin_pct_dec = border_pct / 100.0
max_extent_meters = max(dx, dy)
if max_extent_meters == 0: max_extent_meters = 1.0
total_max_extent = max_extent_meters * (1.0 + 2 * margin_pct_dec)
xy_scale = max_print_size / total_max_extent

import shapely.affinity
from shapely.geometry import box as shapely_box

clip_poly = shapely_box(bounds[0] - dx*margin_pct_dec, bounds[1] - dy*margin_pct_dec,
                        bounds[2] + dx*margin_pct_dec, bounds[3] + dy*margin_pct_dec)

if has_streets: streets_gdf = streets_gdf.clip(clip_poly)
if has_buildings: buildings_gdf = buildings_gdf.clip(clip_poly)

def transform_gdf_to_mm(gdf):
    if getattr(gdf, 'empty', True): return gdf
    gdf['geometry'] = gdf.geometry.apply(lambda geom: shapely.affinity.scale(
        shapely.affinity.translate(geom, xoff=-cx, yoff=-cy),
        xfact=xy_scale, yfact=xy_scale, zfact=xy_scale, origin=(0, 0, 0)
    ))
    return gdf

gpx_gdf_proj = transform_gdf_to_mm(gpx_gdf_proj)
if has_streets: streets_gdf = transform_gdf_to_mm(streets_gdf)
if has_buildings: buildings_gdf = transform_gdf_to_mm(buildings_gdf)

# Terrain
print("\n=== TERRAIN ===")
elev_lats, elev_lons, elev_grid = fetch_elevation_grid(bbox, zoom=12, vertical_resolution=10)
terrain_mesh, xs_g, ys_g, zs_g = create_terrain_mesh(
    elev_lats, elev_lons, elev_grid, local_crs,
    cx=cx, cy=cy, xy_scale=xy_scale,
    terrain_exaggeration=1.5, base_thickness=2.0
)
terrain_interp = TerrainInterpolator(xs_g, ys_g, zs_g)
print(f"Terrain mesh: {len(terrain_mesh.vertices)} verts, {len(terrain_mesh.faces)} faces")

# Build mesh
print("\n=== MESH BUILD ===")
builder = MeshBuilder()
builder.set_terrain(terrain_interp)
builder.meshes.append(terrain_mesh)

if has_buildings:
    builder.add_gdf(buildings_gdf, base_height=0, extrude_height=2.0, color=[180,180,180,255])
    print(f"Added {len(buildings_gdf)} buildings")
else:
    print("NO BUILDINGS!")

if has_streets:
    streets_poly = streets_gdf.copy()
    streets_poly['geometry'] = streets_poly.geometry.buffer(0.8)
    builder.add_gdf(streets_poly, base_height=0, extrude_height=0.8, color=[140,140,140,255])
    print(f"Added {len(streets_gdf)} streets")
else:
    print("NO STREETS!")

gpx_poly = gpx_gdf_proj.copy()
gpx_poly['geometry'] = gpx_poly.geometry.buffer(3.0)
ref_line = gpx_gdf_proj.geometry.iloc[0]
builder.add_gdf(gpx_poly, base_height=0, extrude_height=4.0,
                color=[255,200,0,255], ref_linestring=ref_line, alt_exaggeration=2.0)
print("Added GPX route")

final_mesh = builder.get_combined_mesh()
if final_mesh:
    stats = MeshBuilder.get_mesh_stats(final_mesh)
    print(f"\nFinal mesh: {stats['vertices']} verts, {stats['faces']} faces")
    print(f"Dimensions: {stats['dimensions_mm']}")
    print(f"Watertight: {stats['watertight']}")
    
    out_path = os.path.join(os.path.dirname(__file__), "test_output.stl")
    final_mesh.export(out_path)
    print(f"\nExported to {out_path}")
    print(f"File size: {os.path.getsize(out_path)/1024/1024:.1f} MB")
else:
    print("FAILED - no mesh generated!")
