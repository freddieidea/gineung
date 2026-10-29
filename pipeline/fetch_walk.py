# 구·군 걷는 길 지도 받기 (OpenStreetMap, Overpass). 사용: python fetch_walk.py 남구 https://overpass-api.de/api  → data/raw/walk_남구.graphml
# 구·군 경계(행정동 경계를 합친 것)에서 약 500m 넓혀 받음(경계 근처 시설로 가는 길 포함)
import sys,json,osmnx as ox
from shapely.geometry import shape
from shapely.ops import unary_union
gu,url=sys.argv[1],sys.argv[2]
G=json.load(open("data/raw/boundary/daegu_hjd_20260701.geojson",encoding="utf-8"))["features"]
poly=unary_union([shape(f["geometry"]) for f in G if f["properties"]["sggnm"]==gu]).buffer(0.005)
ox.settings.overpass_url=url; ox.settings.requests_timeout=160; ox.settings.use_cache=True; ox.settings.cache_folder="/tmp/oxcache"
g=ox.graph_from_polygon(poly,network_type="walk",simplify=True,retain_all=True)  # retain_all: 떨어져 있는 지역(달성군 다사·하빈 등)도 버리지 않음
ox.save_graphml(g,f"data/raw/walk_{gu}.graphml"); print(gu,len(g.nodes),len(g.edges))
