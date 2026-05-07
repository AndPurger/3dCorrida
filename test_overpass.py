import requests
query = '[out:json][timeout:10];(way["highway"](-23.552,-46.635,-23.550,-46.633););out body;>;out skel qt;'
r = requests.post('https://overpass-api.de/api/interpreter', data={'data': query}, timeout=15)
print('Status:', r.status_code, 'Elements:', len(r.json().get('elements',[])))
