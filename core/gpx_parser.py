import gpxpy
import gpxpy.gpx
from shapely.geometry import LineString
import geopandas as gpd


class GPXParser:
    def __init__(self, gpx_file_content: str):
        self.gpx = gpxpy.parse(gpx_file_content)

    def get_points(self):
        points = []
        for track in self.gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    ele = point.elevation if point.elevation is not None else 0.0
                    points.append((point.latitude, point.longitude, ele))
        return points

    def get_linestring(self):
        points = self.get_points()
        # Shapely expects (lon, lat, elevation)
        return LineString([(lon, lat, ele) for lat, lon, ele in points])

    def get_linestring_2d(self):
        """2D linestring for CRS estimation (avoids NaN issues)."""
        points = self.get_points()
        return LineString([(lon, lat) for lat, lon, ele in points])

    def get_bounding_box(self, margin=0.005):
        bounds = self.get_linestring_2d().bounds
        return {
            'n': bounds[3] + margin,
            's': bounds[1] - margin,
            'e': bounds[2] + margin,
            'w': bounds[0] - margin,
        }

    def get_geodataframe(self):
        """Returns a GeoDataFrame with a 3D LineString."""
        line = self.get_linestring()
        gdf = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[line])
        return gdf

    def get_geodataframe_2d(self):
        """Returns a GeoDataFrame with a 2D LineString (for CRS estimation)."""
        line = self.get_linestring_2d()
        gdf = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[line])
        return gdf
