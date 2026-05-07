import streamlit as st
import io
import os
import plotly.graph_objects as go
import importlib
import numpy as np

# Force reload modules every run
import core.gpx_parser
import core.map_generator
import core.mesh_builder
import core.terrain_generator
importlib.reload(core.gpx_parser)
importlib.reload(core.map_generator)
importlib.reload(core.mesh_builder)
importlib.reload(core.terrain_generator)

from core.gpx_parser import GPXParser
from core.map_generator import MapGenerator
from core.mesh_builder import MeshBuilder
from core.terrain_generator import fetch_elevation_grid, create_terrain_mesh, TerrainInterpolator

ASSETS = os.path.join(os.path.dirname(__file__), "assets")

st.set_page_config(page_title="GPX to 3D Map (3DCorrida)", layout="wide")
st.title("🏃‍♂️ 3DCorrida - GPX to 3D Map Generator")

# ── Sidebar Controls ──────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Settings")

# --- Print Size ---
st.sidebar.subheader("🖨️ Dimensões de Impressão")
max_print_size = st.sidebar.slider(
    "Max Print Size (mm)", 50, 300, 180, 10,
    help="O tamanho físico (lado maior) do mapa na sua impressora (ex: 180 = 18cm). Todas as outras medidas em milímetros serão baseadas nessa escala."
)

# --- Route ---
st.sidebar.subheader("🟡 Rota de Corrida")
route_thickness = st.sidebar.slider(
    "Route Width (mm)", 0.5, 10.0, 3.0, 0.5,
    help="Espessura física do filete da rota no modelo impresso (em mm)."
)
with st.sidebar.expander("❓ What does this change?"):
    img_path = os.path.join(ASSETS, "help_route_thickness.png")
    if os.path.exists(img_path): st.image(img_path, use_container_width=True)

route_height = st.sidebar.slider(
    "Route Base Height (mm)", 1.0, 15.0, 4.0, 1.0,
    help="Altura física da rota acima da superfície da cidade."
)
with st.sidebar.expander("❓ What does this change?"):
    img_path = os.path.join(ASSETS, "help_route_height.png")
    if os.path.exists(img_path): st.image(img_path, use_container_width=True)

route_alt_exag = st.sidebar.slider(
    "Altimetry Exaggeration", 0.0, 10.0, 2.0, 0.1,
    help="Exagera as subidas/descidas da linha da rota do GPX."
)
with st.sidebar.expander("❓ What does this change?"):
    img_path = os.path.join(ASSETS, "help_altimetry.png")
    if os.path.exists(img_path): st.image(img_path, use_container_width=True)

# --- City Map ---
st.sidebar.subheader("🏙️ City Map")
streets_width = st.sidebar.slider(
    "Street Width (mm)", 0.5, 5.0, 0.8, 0.1,
    help="Espessura física das ruas no modelo impresso."
)
streets_height = st.sidebar.slider(
    "Street Height (mm)", 0.5, 5.0, 0.8, 0.1,
    help="Altura dos fios de plástico das ruas."
)
building_height = st.sidebar.slider(
    "Building Height (mm)", 0.5, 10.0, 2.0, 0.5,
    help="Altura das construções em milímetros de plástico."
)
fetch_buildings = st.sidebar.checkbox(
    "Include Buildings", value=True,
    help="Downloads and extrudes building footprints from OpenStreetMap."
)
with st.sidebar.expander("❓ What does Buildings change?"):
    img_path = os.path.join(ASSETS, "help_buildings.png")
    if os.path.exists(img_path):
        st.image(img_path, use_container_width=True)
    st.caption("Left = no buildings, Right = extruded building blocks")

# --- Terrain (Enhanced — inspired by maps3d.io) ---
st.sidebar.subheader("🏔️ Terrain")
enable_terrain = st.sidebar.checkbox(
    "Enable Terrain Relief", value=False,
    help="Downloads Mapzen elevation data from AWS terrain tiles and applies real topographic relief."
)

terrain_dataset = st.sidebar.selectbox(
    "Elevation Dataset",
    options=["mapzen", "geotiff"],
    index=0,
    help="mapzen = Terrarium PNG encoding (faster). geotiff = GeoTIFF raster (requires rasterio).",
    disabled=not enable_terrain
)

terrain_zoom = st.sidebar.slider(
    "Elevation Zoom Level", 10, 14, 12, 1,
    help="Tile zoom level. Higher = more detail but more tiles to download. "
         "maps3d.io uses 13 for high quality.",
    disabled=not enable_terrain
)

terrain_exag = st.sidebar.slider(
    "Elevation Exaggeration", 0.5, 5.0, 1.5, 0.1,
    help="Multiplies the terrain height to make hills more visible. maps3d.io default: 1.5",
    disabled=not enable_terrain
)

terrain_vert_res = st.sidebar.slider(
    "Vertical Resolution (m)", 1, 50, 10, 1,
    help="Grid spacing in meters. Lower = more detail (more vertices). maps3d.io default: 10m.",
    disabled=not enable_terrain
)

with st.sidebar.expander("❓ What does Terrain change?"):
    img_path = os.path.join(ASSETS, "help_terrain.png")
    if os.path.exists(img_path):
        st.image(img_path, use_container_width=True)
    st.caption("Left = flat city, Right = real topographic relief")

# --- Base ---
st.sidebar.subheader("📐 Base da Maquete")
base_thickness = st.sidebar.slider(
    "Base Plate Thickness (mm)", 1.0, 10.0, 2.0, 0.5,
    help="Espessura física da base sólida abaixo da cidade."
)

hollow_base = st.sidebar.checkbox(
    "Hollow Base (3D Print)", value=False,
    help="Creates a hollow interior following the terrain profile. Saves 40-60%% material.",
    disabled=not enable_terrain
)

wall_thickness = st.sidebar.slider(
    "Wall Thickness (mm)", 1.0, 5.0, 2.0, 0.5,
    help="Shell wall thickness for hollow mode.",
    disabled=not (enable_terrain and hollow_base)
)

border_pct = st.sidebar.slider(
    "Border around route (%)", 5, 40, 15, 1,
    help="How much extra map area to include around the route, as a percentage."
)

# --- Export Format ---
st.sidebar.subheader("📦 Export")
export_format = st.sidebar.selectbox(
    "Export Format",
    options=["STL", "OBJ", "3MF", "GLB", "PLY"],
    index=0,
    help="STL = universal. OBJ = with normals. 3MF = modern, color-aware. GLB = web/AR ready."
)

uploaded_file = st.sidebar.file_uploader("📂 Upload GPX File", type=['gpx'])

# ── Processing ────────────────────────────────────────────────────────────────
if uploaded_file is not None:
    gpx_content = uploaded_file.getvalue().decode("utf-8")

    # ─ 1) Parse GPX ─
    with st.spinner("📍 Parsing GPX..."):
        parser = GPXParser(gpx_content)
        # Use border_pct to calculate margin in degrees (approximate)
        points = parser.get_points()
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        lat_range = max(lats) - min(lats)
        lon_range = max(lons) - min(lons)
        margin_deg = max(lat_range, lon_range) * (border_pct / 100.0)

        bbox = parser.get_bounding_box(margin=margin_deg)
        gpx_gdf = parser.get_geodataframe()       # 3D (with elevation)
        gpx_gdf_2d = parser.get_geodataframe_2d()  # 2D (for CRS estimation)
        local_crs = gpx_gdf_2d.estimate_utm_crs()
        gpx_gdf_proj = gpx_gdf.to_crs(local_crs)

    st.success(f"✅ GPX: {len(points)} pontos | CRS: {local_crs}")

    # ─ 2) Download OSM data ─
    st.subheader("🗺️ Downloading Map Data")
    map_gen = MapGenerator(bbox)

    streets_gdf = map_gen.get_streets()
    has_streets = not getattr(streets_gdf, 'empty', True)
    if has_streets:
        streets_gdf = streets_gdf.to_crs(local_crs)

    buildings_gdf = None
    has_buildings = False
    if fetch_buildings:
        buildings_gdf = map_gen.get_buildings()
        has_buildings = not getattr(buildings_gdf, 'empty', True)
        if has_buildings:
            buildings_gdf = buildings_gdf.to_crs(local_crs)

    # ─ 2.5) Transform Geometries to Physical Printer Space (mm) ─
    bounds = gpx_gdf_proj.total_bounds  # [minx, miny, maxx, maxy] in meters
    cx = (bounds[0] + bounds[2]) / 2.0
    cy = (bounds[1] + bounds[3]) / 2.0
    dx = bounds[2] - bounds[0]
    dy = bounds[3] - bounds[1]
    
    # Clip OSM features exactly to the map area (plus border) so long highways don't shoot out
    margin_pct_dec = border_pct / 100.0
    margin_x = dx * margin_pct_dec
    margin_y = dy * margin_pct_dec
    
    from shapely.geometry import box
    clip_poly = box(bounds[0] - margin_x, bounds[1] - margin_y, 
                    bounds[2] + margin_x, bounds[3] + margin_y)
                    
    if has_streets:
        streets_gdf = streets_gdf.clip(clip_poly)
    if has_buildings:
        buildings_gdf = buildings_gdf.clip(clip_poly)

    # Calculate scale so that the max bounding box size fits exactly max_print_size
    max_extent_meters = max(dx, dy)
    if max_extent_meters == 0: max_extent_meters = 1.0
    total_max_extent = max_extent_meters * (1.0 + 2 * margin_pct_dec)
    
    xy_scale = max_print_size / total_max_extent  # Factor to convert meters to scaled mm
    
    import shapely.affinity
    def transform_gdf_to_mm(gdf):
        if getattr(gdf, 'empty', True): return gdf
        # MUST supply zfact=xy_scale and origin=(0,0,0) so GPX elevations scale down to printer mm!
        gdf['geometry'] = gdf.geometry.apply(lambda geom: shapely.affinity.scale(
            shapely.affinity.translate(geom, xoff=-cx, yoff=-cy),
            xfact=xy_scale, yfact=xy_scale, zfact=xy_scale, origin=(0, 0, 0)
        ))
        return gdf

    gpx_gdf_proj = transform_gdf_to_mm(gpx_gdf_proj)
    if has_streets: streets_gdf = transform_gdf_to_mm(streets_gdf)
    if has_buildings: buildings_gdf = transform_gdf_to_mm(buildings_gdf)

    # ─ 3) Terrain elevation (optional — now with Mapzen tiles!) ─
    terrain_interp = None
    terrain_mesh = None
    if enable_terrain:
        st.subheader("🏔️ Downloading Mapzen Elevation Tiles...")
        with st.spinner("Fetching high-resolution terrain data from AWS..."):
            elev_lats, elev_lons, elev_grid = fetch_elevation_grid(
                bbox,
                zoom=terrain_zoom,
                dataset=terrain_dataset,
                vertical_resolution=terrain_vert_res
            )
            terrain_mesh, xs_g, ys_g, zs_g = create_terrain_mesh(
                elev_lats, elev_lons, elev_grid, local_crs,
                cx=cx, cy=cy, xy_scale=xy_scale,
                terrain_exaggeration=terrain_exag,
                base_thickness=base_thickness,
                hollow=hollow_base,
                wall_thickness=wall_thickness
            )
            terrain_interp = TerrainInterpolator(xs_g, ys_g, zs_g)

    # ─ 4) Build 3D Mesh ─
    st.subheader("🔧 Construindo Malha 3D")
    with st.spinner("Extrudando geometrias..."):
        builder = MeshBuilder()

        # Configura o interpolador de terreno para ajustar as geometrias
        if terrain_interp is not None:
            builder.set_terrain(terrain_interp)

        if terrain_mesh is not None:
            # O próprio bloco sólido SRTM serve como base
            builder.meshes.append(terrain_mesh)
            mode_label = "🏔️ Terreno oco" if hollow_base else "🏔️ Terreno sólido"
            st.write(f"{mode_label} gerado com sucesso")
        else:
            # Sem terreno: base plana
            builder.create_base_plate(gpx_gdf_proj, thickness=base_thickness,
                                      margin_pct=border_pct / 100.0)

        # Buildings (agora os prédios são geometrias "crisp" que seguem o relevo via centróide)
        if has_buildings:
            builder.add_gdf(buildings_gdf, base_height=0,
                            extrude_height=building_height,
                            color=[180, 180, 180, 255])
            st.write(f"🏢 {len(buildings_gdf)} prédios extrudados")

        # Streets
        if has_streets:
            streets_poly = streets_gdf.copy()
            streets_poly['geometry'] = streets_poly.geometry.buffer(streets_width)
            builder.add_gdf(streets_poly, base_height=0,
                            extrude_height=streets_height,
                            color=[140, 140, 140, 255])
            st.write(f"🛣️ {len(streets_gdf)} ruas extrudadas")

        # GPX Route
        gpx_poly = gpx_gdf_proj.copy()
        gpx_poly['geometry'] = gpx_poly.geometry.buffer(route_thickness)
        ref_line = gpx_gdf_proj.geometry.iloc[0]
        builder.add_gdf(gpx_poly, base_height=0, extrude_height=route_height,
                        color=[255, 200, 0, 255],
                        ref_linestring=ref_line, alt_exaggeration=route_alt_exag)
        st.write("🟡 Rota GPX destacada")

        final_mesh = builder.get_combined_mesh()

    # ─ 5) Display + Export ─
    if final_mesh:
        # Mesh statistics
        stats = MeshBuilder.get_mesh_stats(final_mesh)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Vértices", f"{stats['vertices']:,}")
        with col2:
            st.metric("Faces", f"{stats['faces']:,}")
        with col3:
            dims = stats.get('dimensions_mm', {})
            st.metric("Dimensões (mm)",
                       f"{dims.get('x', 0)} × {dims.get('y', 0)} × {dims.get('z', 0)}")

        if stats.get('watertight'):
            st.success("✅ Mesh é watertight (pronta para impressão 3D)")
        else:
            st.warning("⚠️ Mesh não é watertight (pode ter problemas no slicer)")

        # ── 3D Visualization ──
        vertices = final_mesh.vertices
        faces = final_mesh.faces

        # Color terrain by elevation for better visualization
        z_vals = vertices[:, 2]
        z_min, z_max = z_vals.min(), z_vals.max()
        z_range = z_max - z_min if z_max > z_min else 1.0

        # Elevation-based intensity (0-1)
        intensity = (z_vals - z_min) / z_range

        fig = go.Figure(data=[
            go.Mesh3d(
                x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
                i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
                intensity=intensity,
                colorscale=[
                    [0.0, 'rgb(40, 40, 50)'],       # Base dark
                    [0.15, 'rgb(60, 80, 60)'],       # Low terrain green
                    [0.3, 'rgb(80, 120, 70)'],       # Mid green
                    [0.5, 'rgb(160, 160, 100)'],     # Transition
                    [0.7, 'rgb(180, 140, 100)'],     # Brown
                    [0.85, 'rgb(200, 180, 160)'],    # Light rock
                    [1.0, 'rgb(240, 240, 240)'],     # Snow/peak
                ],
                showscale=True,
                colorbar=dict(
                    title="Elevation",
                    thickness=15,
                    len=0.5,
                ),
                opacity=1.0,
                flatshading=True,
                lighting=dict(
                    ambient=0.35,
                    diffuse=0.85,
                    roughness=0.4,
                    specular=0.25,
                    fresnel=0.15
                ),
                lightposition=dict(x=100, y=200, z=300),
            )
        ])

        fig.update_layout(
            scene=dict(
                aspectmode='data',
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                zaxis=dict(visible=False),
                bgcolor='rgb(20, 20, 30)',
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            height=650,
            paper_bgcolor='rgb(20, 20, 30)',
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── Export ──
        st.subheader("📦 Download")

        fmt = export_format.lower()
        mesh_data, mime_type, ext = MeshBuilder.export_mesh(final_mesh, fmt)

        filename = f"3d_corrida_map{ext}"
        file_size_mb = len(mesh_data) / (1024 * 1024)

        st.download_button(
            label=f"⬇️ Download {export_format} ({file_size_mb:.1f} MB)",
            data=mesh_data,
            file_name=filename,
            mime=mime_type,
        )

        # Quick links for other formats
        st.caption("Outros formatos disponíveis no seletor da sidebar.")

    else:
        st.error("❌ Falha ao gerar a mesh. Verifique seu arquivo GPX.")
