import sys, os, json, hashlib, requests, time
sys.path.insert(0, r'd:\.dev\3dCorrida')
from core.gpx_parser import GPXParser

CACHE = r'd:\.dev\3dCorrida\.cache'
os.makedirs(CACHE, exist_ok=True)
SERVERS = ['https://lz4.overpass-api.de/api/interpreter', 'https://overpass-api.de/api/interpreter']

files = [
    r'd:\.dev\3dCorrida\GPX Sample file\run.gpx',
    r'd:\.dev\3dCorrida\GPX Sample file\run (1).gpx',
    r'd:\.dev\3dCorrida\GPX Sample file\Prova_Ilumina_Parana_.gpx',
]

for fp in files:
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            content = f.read()
        parser = GPXParser(content)
        pts = parser.get_points()
        if len(pts) == 0:
            print(f'SKIP {os.path.basename(fp)}: no points')
            continue
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        margin = max(max(lats)-min(lats), max(lons)-min(lons)) * 0.15
        bbox = parser.get_bounding_box(margin=margin)
        bbox_str = f"{bbox['s']},{bbox['w']},{bbox['n']},{bbox['e']}"
        print(f'File: {os.path.basename(fp)} | pts={len(pts)} | bbox={bbox_str}')

        for label, tag in [('streets','highway'), ('buildings','building')]:
            q = f"""
        [out:json][timeout:60];
        (
          way["{tag}"]({bbox_str});
        );
        out body;
        >;
        out skel qt;
        """
            key = hashlib.md5(q.encode()).hexdigest()
            path = os.path.join(CACHE, f'{key}.json')
            if os.path.exists(path):
                print(f'  {label}: already cached')
                continue
            for srv in SERVERS:
                print(f'  {label}: trying {srv.split("/")[2]}...', end=' ', flush=True)
                try:
                    r = requests.post(srv, data={'data':q}, timeout=60, headers={'User-Agent':'3DCorrida/1.0'})
                    if r.status_code == 200:
                        data = r.json()
                        n = len(data.get('elements',[]))
                        if n > 0:
                            with open(path,'w') as ff:
                                json.dump(data, ff)
                            print(f'OK {n} elements cached')
                            break
                        else:
                            print('empty response')
                    else:
                        print(f'HTTP {r.status_code}')
                except Exception as e:
                    print(type(e).__name__)
            time.sleep(1)
    except Exception as e:
        print(f'ERROR {os.path.basename(fp)}: {e}')

print('DONE')
