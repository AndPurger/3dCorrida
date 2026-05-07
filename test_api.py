import requests, json, time

servers = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter", 
    "https://z.overpass-api.de/api/interpreter",
]

# Use a small query to test
query = '[out:json][timeout:10];(way["highway"](-23.56,-46.66,-23.54,-46.62););out body;>;out skel qt;'

for s in servers:
    print(f"Testing {s.split('/')[2]}...", end=" ", flush=True)
    t = time.time()
    try:
        r = requests.post(s, data={"data": query}, timeout=15)
        elapsed = time.time() - t
        print(f"HTTP {r.status_code} in {elapsed:.1f}s", end="")
        if r.status_code == 200:
            data = r.json()
            print(f" — {len(data.get('elements', []))} elements")
        else:
            print()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}")
