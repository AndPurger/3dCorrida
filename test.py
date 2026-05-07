import os
import sys

from core.gpx_parser import GPXParser
from core.map_generator import MapGenerator
from core.mesh_builder import MeshBuilder
import osmnx as ox

gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Test Track</name>
    <trkseg>
      <trkpt lat="-23.55052" lon="-46.633309"><ele>760.0</ele></trkpt>
      <trkpt lat="-23.55152" lon="-46.634309"><ele>762.0</ele></trkpt>
      <trkpt lat="-23.55252" lon="-46.635309"><ele>758.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""

print("Testing GPX Parser...")
parser = GPXParser(gpx_content)
bbox = parser.get_bounding_box(margin=0.002)
gpx_gdf = parser.get_geodataframe()

print("Testing OSMNX fetching (streets)...")
map_gen = MapGenerator(bbox)
streets_gdf = map_gen.get_projected_streets()

print("Testing MeshBuilder...")
builder = MeshBuilder()
gpx_gdf_proj = ox.project_gdf(gpx_gdf, to_crs=streets_gdf.crs)

builder.create_base_plate(gpx_gdf_proj, thickness=4.0)

streets_poly = streets_gdf.copy()
streets_poly['geometry'] = streets_poly.geometry.buffer(2.0)
builder.add_gdf(streets_poly, base_height=0, extrude_height=2.0)

gpx_poly = gpx_gdf_proj.copy()
gpx_poly['geometry'] = gpx_poly.geometry.buffer(8.0)
builder.add_gdf(gpx_poly, base_height=0, extrude_height=10.0)

mesh = builder.get_combined_mesh()
mesh.export("test_out.stl")
print("Exported test_out.stl successfully!")
