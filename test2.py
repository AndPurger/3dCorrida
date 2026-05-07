import osmnx as ox

ox.settings.overpass_endpoint = "https://overpass.kumi.systems/api"
print("Endpoint:", ox.settings.overpass_endpoint)

bbox_tuple = (-46.635309, -23.55252, -46.633309, -23.55052)
tags = {'highway': True}
try:
    print("Fetching from bbox:", bbox_tuple)
    features = ox.features_from_bbox(bbox=bbox_tuple, tags=tags)
    print("Features count:", len(features))
    lines = features[features.geometry.type.isin(['LineString', 'MultiLineString'])]
    print("Lines count:", len(lines))
except Exception as e:
    print("Exception", e)
