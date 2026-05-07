import requests
import time

endpoints = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

query = "[out:json][timeout:5];(way[\"highway\"](-23.552,-46.635,-23.550,-46.633););out body;>;out skel qt;"

for e in endpoints:
    print("Testing:", e)
    try:
        res = requests.post(e, data={'data': query}, timeout=5)
        print("Status:", res.status_code)
        if res.status_code == 200:
            print("SUCCESS! Use this endpoint.")
            break
    except Exception as err:
        print("Error:", err)
