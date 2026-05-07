import requests
import xml.etree.ElementTree as ET
import time

def fetch_osm_direct(bbox):
    # bbox: dict with 'w', 's', 'e', 'n' (min_lon, min_lat, max_lon, max_lat)
    url = f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox['w']},{bbox['s']},{bbox['e']},{bbox['n']}"
    print(f"Fetching from {url}")
    t0 = time.time()
    r = requests.get(url, headers={'User-Agent': '3DCorridaApp/1.0'})
    print(f"Time: {time.time() - t0:.2f}s, Status: {r.status_code}")
    
    if r.status_code == 200:
        xml_data = r.content
        print(f"Size: {len(xml_data)} bytes")
        
        # Parse XML
        root = ET.fromstring(xml_data)
        nodes = {}
        ways = []
        for child in root:
            if child.tag == 'node':
                nodes[child.attrib['id']] = (float(child.attrib['lon']), float(child.attrib['lat']))
            elif child.tag == 'way':
                tags = {tag.attrib['k']: tag.attrib['v'] for tag in child.findall('tag')}
                nd_refs = [nd.attrib['ref'] for nd in child.findall('nd')]
                ways.append({'id': child.attrib['id'], 'tags': tags, 'nodes': nd_refs})
                
        print(f"Parsed {len(nodes)} nodes, {len(ways)} ways")
        
        # Filter highways and buildings
        hw_count = sum(1 for w in ways if 'highway' in w['tags'])
        bldg_count = sum(1 for w in ways if 'building' in w['tags'])
        print(f"Highways: {hw_count}, Buildings: {bldg_count}")

bbox = {'w': -46.635, 's': -23.552, 'e': -46.633, 'n': -23.550}
fetch_osm_direct(bbox)
