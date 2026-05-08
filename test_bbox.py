import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from core.gpx_parser import GPXParser

gpx_dir = os.path.join(os.path.dirname(__file__), "GPX Sample file")

for name in os.listdir(gpx_dir):
    if not name.endswith('.gpx'):
        continue
    try:
        path = os.path.join(gpx_dir, name)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        p = GPXParser(content)
        pts = p.get_points()
        bbox = p.get_bounding_box(margin=0.005)
        lat_r = bbox['n'] - bbox['s']
        lon_r = bbox['e'] - bbox['w']
        area = lat_r * lon_r
        print(f"{name}: {len(pts)} pts, bbox area={area:.4f} sq deg")
        print(f"  S={bbox['s']:.5f} N={bbox['n']:.5f} W={bbox['w']:.5f} E={bbox['e']:.5f}")
        print(f"  lat_range={lat_r:.4f} lon_range={lon_r:.4f}")
        if area > 0.25:
            print("  >> WARNING: TOO LARGE for OSM main API (max 0.25 sq deg)!")
        print()
    except Exception as e:
        print(f"{name}: ERROR {e}")
