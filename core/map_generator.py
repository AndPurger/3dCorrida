import requests
import json
import os
import hashlib
import xml.etree.ElementTree as ET
import geopandas as gpd
from shapely.geometry import LineString, Polygon
import streamlit as st

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

OVERPASS_SERVERS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]

def _cache_key(bbox_str, query_type):
    """Generate a unique cache key from the bounding box and type (streets/buildings)."""
    val = f"{bbox_str}_{query_type}"
    return hashlib.md5(val.encode()).hexdigest()

def _load_from_cache(bbox_str, query_type):
    key = _cache_key(bbox_str, query_type)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            st.success(f"📦 {query_type.capitalize()} carregados do cache local!")
            return data
        except Exception:
            pass
    return None

def _save_to_cache(bbox_str, query_type, data):
    key = _cache_key(bbox_str, query_type)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception:
        pass


def _fetch_osm_xml(bbox_str, timeout=30):
    """
    Fetch direct raw OSM XML from the main api.openstreetmap.org.
    This is much faster and reliable for small bounding boxes (< 0.25 sq degrees).
    """
    # bbox_str here is south,west,north,east.
    # Main OSM API expects min_lon, min_lat, max_lon, max_lat -> west, south, east, north
    s, w, n, e = bbox_str.split(',')
    osm_bbox = f"{w},{s},{e},{n}"
    url = f"https://api.openstreetmap.org/api/0.6/map?bbox={osm_bbox}"
    
    st.info("🔄 Baixando dados direto da API Principal do OSM...")
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "3DCorrida/1.0"})
        if r.status_code == 200:
            st.success("✅ Download concluído!")
            return r.content
        elif r.status_code == 400:
            st.warning("⚠️ Área muito grande para API principal. Tentando Overpass...")
        else:
            st.warning(f"⚠️ Erro HTTP {r.status_code} na API Principal")
    except Exception as e:
        st.warning(f"❌ Erro na API Principal: {type(e).__name__}")
    
    return None

def _parse_osm_xml_to_dict(xml_data):
    """Parse OSM XML to a dictionary containing nodes and filtered ways."""
    try:
        root = ET.fromstring(xml_data)
    except Exception as e:
        print(f"XML parse error: {e}")
        return None

    nodes = {}
    ways = []
    
    for child in root:
        if child.tag == 'node':
            # Store lon, lat
            nodes[child.attrib['id']] = (float(child.attrib['lon']), float(child.attrib['lat']))
        elif child.tag == 'way':
            tags = {tag.attrib['k']: tag.attrib['v'] for tag in child.findall('tag')}
            nd_refs = [nd.attrib['ref'] for nd in child.findall('nd')]
            ways.append({
                'id': child.attrib['id'],
                'tags': tags,
                'nodes': nd_refs
            })
            
    return {"nodes": nodes, "ways": ways}

def _overpass_query_fallback(query_str, timeout=60):
    """Fallback to Overpass API if main OSM API fails or bbox is too large."""
    for server in OVERPASS_SERVERS:
        try:
            st.info(f"🔄 Tentando Overpass: {server.split('/')[2]}...")
            resp = requests.post(
                server,
                data={"data": query_str},
                timeout=timeout,
                headers={"User-Agent": "3DCorrida/1.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "elements" in data and len(data["elements"]) > 0:
                    st.success(f"✅ Download concluído via Overpass")
                    return data
            else:
                st.warning(f"⚠️ Overpass HTTP {resp.status_code}")
        except requests.exceptions.Timeout:
            st.warning(f"⏰ Timeout em {server.split('/')[2]}")
        except Exception as e:
            st.warning(f"❌ Erro Overpass: {type(e).__name__}")
    return None

def _osm_dict_to_gdf(osm_dict, geom_type="lines", target_tag="highway"):
    """Convert parsed OSM XML dictionary OR Overpass JSON elements to GeoDataFrame."""
    if not osm_dict:
        return gpd.GeoDataFrame()

    geometries = []
    
    # Handle both Custom XML parse format AND Overpass JSON format seamlessly
    if "ways" in osm_dict:
        # Came from XML
        nodes = osm_dict["nodes"]
        ways = osm_dict["ways"]
    elif "elements" in osm_dict:
        # Came from Overpass
        nodes = {str(el["id"]): (float(el["lon"]), float(el["lat"])) for el in osm_dict["elements"] if el["type"] == "node"}
        ways = [el for el in osm_dict["elements"] if el["type"] == "way"]
    else:
        return gpd.GeoDataFrame()

    for w in ways:
        # Check if it has desired tag
        tags = w.get("tags", {})
        if target_tag not in tags:
            continue
            
        coords = []
        for nid in w.get("nodes", []):
            nid_str = str(nid)
            if nid_str in nodes:
                coords.append(nodes[nid_str])
        
        if len(coords) < 2:
            continue

        if geom_type == "polygons":
            # Closed ways = buildings
            if coords[0] == coords[-1] and len(coords) >= 4:
                try:
                    poly = Polygon(coords)
                    if poly.is_valid and poly.area > 0:
                        geometries.append(poly)
                except:
                    pass
        else:
            # Open ways = streets
            try:
                line = LineString(coords)
                if line.is_valid and line.length > 0:
                    geometries.append(line)
            except:
                pass

    if not geometries:
        return gpd.GeoDataFrame()

    return gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")


class MapGenerator:
    def __init__(self, bbox):
        self.south = bbox['s']
        self.west = bbox['w']
        self.north = bbox['n']
        self.east = bbox['e']
        self.bbox_str = f"{self.south},{self.west},{self.north},{self.east}"
        self.osm_data = None # Will hold the shared OSM dict for both streets and buildings
        
    def _fetch_combined_osm_data(self):
        """Fetch XML once and use it for both streets and buildings to save network calls."""
        if self.osm_data is not None:
            return self.osm_data
            
        # Try finding the pre-parsed entire dict from cache
        cached = _load_from_cache(self.bbox_str, "combined_osm_data")
        if cached is not None:
            self.osm_data = cached
            return cached

        # 1. Try Main OSM XML API
        xml_data = _fetch_osm_xml(self.bbox_str)
        if xml_data:
            parsed = _parse_osm_xml_to_dict(xml_data)
            if parsed:
                self.osm_data = parsed
                _save_to_cache(self.bbox_str, "combined_osm_data", parsed)
                return parsed

        # 2. Try Overpass as fallback (querying both highway and building at once)
        fallback_query = f"""
        [out:json][timeout:60];
        (
          way["highway"]({self.bbox_str});
          way["building"]({self.bbox_str});
        );
        out body;
        >;
        out skel qt;
        """
        st.warning("⚠️ Tentando Overpass como fallback para ruas e prédios...")
        overpass_data = _overpass_query_fallback(fallback_query)
        if overpass_data:
            self.osm_data = overpass_data
            _save_to_cache(self.bbox_str, "combined_osm_data", overpass_data)
            return overpass_data
            
        return None

    def get_streets(self):
        st.write("**🛣️ Carregando mapas (Servidor Principal OSM)...**")
        data = self._fetch_combined_osm_data()
        gdf = _osm_dict_to_gdf(data, geom_type="lines", target_tag="highway")
        
        if gdf.empty:
            st.error("❌ Nenhuma rua encontrada")
        else:
            st.success(f"✅ {len(gdf)} ruas processadas")
        return gdf

    def get_buildings(self):
        data = self._fetch_combined_osm_data()
        gdf = _osm_dict_to_gdf(data, geom_type="polygons", target_tag="building")
        
        if gdf.empty:
            st.warning("⚠️ Nenhum prédio encontrado na área")
        else:
            st.success(f"✅ {len(gdf)} prédios processados")
        return gdf
