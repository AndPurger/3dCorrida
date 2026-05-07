import requests
import time

url = "https://overpass-api.de/api/interpreter"
query = "[out:json][timeout:25];(way[\"highway\"](-23.552,-46.635,-23.550,-46.633););out body;>;out skel qt;"

start = time.time()
try:
    print("Testing requests...", flush=True)
    res = requests.post(url, data={'data': query}, timeout=10)
    print("Status:", res.status_code)
    print("Length:", len(res.text))
except Exception as e:
    print("Error:", e)
print("Time taken:", time.time() - start)
