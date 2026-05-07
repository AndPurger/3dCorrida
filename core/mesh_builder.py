"""
Mesh Builder — Enhanced 3D mesh construction and multi-format export.

Supports extrusion of GeoDataFrame geometries, terrain-aware placement,
GPX altimetry, and export to STL, OBJ, 3MF, and glTF/GLB formats.
"""

import trimesh
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
import geopandas as gpd
from scipy.spatial import cKDTree


class MeshBuilder:
    def __init__(self):
        self.meshes = []
        self.terrain_interpolator = None

    def set_terrain(self, terrain_interpolator):
        """Set a terrain interpolator for ground-level offsets."""
        self.terrain_interpolator = terrain_interpolator

    def apply_altimetry(self, mesh, linestring, alt_exaggeration=1.0):
        """Apply GPX altitude variation to the top face of a route mesh."""
        if not linestring.has_z or alt_exaggeration == 0:
            return mesh

        coords = np.array(linestring.coords)
        xy = coords[:, :2]
        z = coords[:, 2] * alt_exaggeration

        min_z = np.min(z)
        z = z - min_z

        tree = cKDTree(xy)
        vertices = np.copy(mesh.vertices)

        z_max = np.max(vertices[:, 2])
        is_top = np.isclose(vertices[:, 2], z_max)
        if not np.any(is_top):
            return mesh

        dist, idx = tree.query(vertices[is_top, :2])
        local_z = z[idx]

        vertices[is_top, 2] = vertices[is_top, 2] + local_z
        mesh.vertices = vertices
        mesh.faces = mesh.faces
        return mesh

    def add_gdf(self, gdf, base_height=0.0, extrude_height=1.0,
                color=None, ref_linestring=None, alt_exaggeration=1.0):
        """Extrude GeoDataFrame geometries into 3D meshes."""
        if color is None:
            color = [150, 150, 150, 255]
        if getattr(gdf, 'empty', True):
            return

        for geom in gdf.geometry:
            if geom.is_empty:
                continue

            # Handle both Polygon and MultiPolygon
            if isinstance(geom, (Polygon, MultiPolygon)):
                polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms)
            else:
                # For any other geometry type, try to get polygons
                try:
                    polys = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
                except Exception:
                    continue

            for poly in polys:
                try:
                    mesh = trimesh.creation.extrude_polygon(poly, height=extrude_height)
                    mesh.apply_translation([0, 0, base_height])

                    # Apply GPX altimetry
                    if ref_linestring is not None:
                        mesh = self.apply_altimetry(mesh, ref_linestring, alt_exaggeration)

                    # Apply terrain: uniform Z offset at polygon centroid
                    # (NOT per-vertex, which distorts small geometries)
                    if self.terrain_interpolator is not None:
                        cx, cy = poly.centroid.x, poly.centroid.y
                        ground_z = self.terrain_interpolator.get_height(cx, cy)
                        mesh.apply_translation([0, 0, float(ground_z[0])])

                    if hasattr(mesh.visual, 'vertex_colors'):
                        mesh.visual.vertex_colors = color
                    self.meshes.append(mesh)
                except Exception as e:
                    print(f"Error extruding polygon: {e}")

    def create_base_plate(self, gdf_proj, thickness=2.0, margin_pct=0.15,
                          color=None):
        """Create a base plate extended by margin_pct around the GDF bounds."""
        if color is None:
            color = [200, 200, 200, 255]
        if getattr(gdf_proj, 'empty', True):
            return

        bounds = gdf_proj.total_bounds  # [minx, miny, maxx, maxy]
        dx = bounds[2] - bounds[0]
        dy = bounds[3] - bounds[1]
        margin_x = dx * margin_pct
        margin_y = dy * margin_pct

        poly = Polygon([
            (bounds[0] - margin_x, bounds[1] - margin_y),
            (bounds[2] + margin_x, bounds[1] - margin_y),
            (bounds[2] + margin_x, bounds[3] + margin_y),
            (bounds[0] - margin_x, bounds[3] + margin_y),
        ])

        try:
            mesh = trimesh.creation.extrude_polygon(poly, height=thickness)
            mesh.apply_translation([0, 0, -thickness])
            if hasattr(mesh.visual, 'vertex_colors'):
                mesh.visual.vertex_colors = color
            self.meshes.append(mesh)
        except Exception as e:
            print(f"Error creating base plate: {e}")

        return bounds, margin_x, margin_y

    def get_combined_mesh(self):
        """Combine all meshes into a single mesh."""
        if not self.meshes:
            return None
        return trimesh.util.concatenate(self.meshes)

    # ── Multi-Format Export ────────────────────────────────────────────────

    @staticmethod
    def export_mesh(mesh, file_format='stl'):
        """
        Export mesh to bytes in the specified format.

        Parameters
        ----------
        mesh : trimesh.Trimesh
            The mesh to export
        file_format : str
            One of: 'stl', 'obj', '3mf', 'glb', 'gltf', 'ply'

        Returns
        -------
        bytes
            The exported mesh data
        str
            The MIME type for download
        str
            The file extension
        """
        import io

        buffer = io.BytesIO()

        format_map = {
            'stl': ('model/stl', '.stl', 'stl'),
            'obj': ('model/obj', '.obj', 'obj'),
            '3mf': ('application/vnd.ms-package.3dmanufacturing-3dmodel+xml', '.3mf', '3mf'),
            'glb': ('model/gltf-binary', '.glb', 'glb'),
            'gltf': ('model/gltf+json', '.gltf', 'gltf'),
            'ply': ('application/x-ply', '.ply', 'ply'),
        }

        fmt = file_format.lower()
        if fmt not in format_map:
            fmt = 'stl'

        mime_type, extension, trimesh_fmt = format_map[fmt]

        try:
            mesh.export(buffer, file_type=trimesh_fmt)
            buffer.seek(0)
            return buffer.read(), mime_type, extension
        except Exception as e:
            # Fallback to STL if format fails
            print(f"Export to {fmt} failed ({e}), falling back to STL")
            buffer = io.BytesIO()
            mesh.export(buffer, file_type='stl')
            buffer.seek(0)
            return buffer.read(), 'model/stl', '.stl'

    @staticmethod
    def get_mesh_stats(mesh):
        """Get human-readable mesh statistics."""
        if mesh is None:
            return {}

        stats = {
            'vertices': len(mesh.vertices),
            'faces': len(mesh.faces),
            'watertight': mesh.is_watertight,
            'volume_mm3': mesh.volume if mesh.is_watertight else None,
        }

        # Bounding box dimensions
        bounds = mesh.bounds
        dims = bounds[1] - bounds[0]
        stats['dimensions_mm'] = {
            'x': round(dims[0], 1),
            'y': round(dims[1], 1),
            'z': round(dims[2], 1),
        }

        # Estimated print size
        stats['max_dimension_mm'] = round(max(dims), 1)

        return stats

    def export_stl(self, mesh, filepath):
        """Legacy: Export to STL file."""
        if mesh is not None:
            mesh.export(filepath)
