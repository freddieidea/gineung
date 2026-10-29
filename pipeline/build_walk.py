# 대구 걷는 길 지도 하나로 합치기 + 시설을 길 위의 가장 가까운 지점에 붙이기
#  → data/processed/walk_daegu.npz (길 그물), data/processed/facility_walk.csv (시설마다 붙은 길·위치·길까지 거리)
# - 구·군 지도 9개(OpenStreetMap, fetch_walk.py)를 합침. 같은 교차점은 OSM 번호가 같아 구·군 경계에서 자연스럽게 이어짐
# - 시설은 교차점이 아니라 '길 위의 가장 가까운 지점'에 붙임 (길을 10m 간격 점으로 나눠 가장 가까운 점을 찾음)
# - 노드 200개 이상으로 이어진 '큰 길망'에만 붙임. 떨어진 작은 길 조각에 붙으면 길이 끊겨 계산이 틀어지기 때문
# 시설만 다시 붙이기: python pipeline/build_walk.py --facilities  (길 그물은 그대로 두고 facility_walk.csv만 새로 만듦. 시설표가 바뀌었을 때)
import sys
import numpy as np, pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
GU=["중구","동구","서구","남구","북구","수성구","달서구","달성군","군위군"]
KX=np.cos(np.radians(35.87))*111320; KY=110540; STEP=10.0
ONLY_FAC="--facilities" in sys.argv
if ONLY_FAC:
    Z=np.load("data/processed/walk_daegu.npz"); sx,sy,se,st=Z["sx"],Z["sy"],Z["se"],Z["st"]
else:
  import osmnx as ox, networkx as nx
  G=nx.MultiDiGraph()
  for g in GU: G=nx.compose(G, ox.load_graphml(f"data/raw/walk_{g}.graphml"))
  osm=np.array(list(G.nodes)); idx={n:i for i,n in enumerate(osm)}
  X=np.array([G.nodes[n]["x"] for n in osm]); Y=np.array([G.nodes[n]["y"] for n in osm])
  best={}
  for u,v,d in G.edges(data=True):
      a,b=idx[u],idx[v]
      if a==b: continue
      k=(min(a,b),max(a,b)); L=float(d.get("length",0)) or float(np.hypot((X[a]-X[b])*KX,(Y[a]-Y[b])*KY))
      if k not in best or L<best[k][0]:
          geom=d.get("geometry"); pts=list(geom.coords) if geom is not None else [(X[a],Y[a]),(X[b],Y[b])]
          if np.hypot(pts[0][0]-X[a],pts[0][1]-Y[a])>np.hypot(pts[-1][0]-X[a],pts[-1][1]-Y[a]): pts=pts[::-1]  # a에서 시작하게
          best[k]=(L,pts)
  keys=list(best); eu=np.array([k[0] for k in keys]); ev=np.array([k[1] for k in keys]); el=np.array([best[k][0] for k in keys])
  n=len(osm); M=coo_matrix((np.r_[el,el],(np.r_[eu,ev],np.r_[ev,eu])),shape=(n,n)).tocsr()
  nc,comp=connected_components(M,directed=False); big=np.bincount(comp)[comp]>=200
  # 길을 10m 간격 점으로 나눔 (점마다 어느 길의 몇 % 지점인지)
  sx=[];sy=[];se=[];st=[]
  for e,k in enumerate(keys):
      if not big[eu[e]]: continue
      pts=np.array(best[k][1]); seg=np.hypot(np.diff(pts[:,0])*KX,np.diff(pts[:,1])*KY); cum=np.r_[0,np.cumsum(seg)]; tot=cum[-1]
      m=max(2,int(tot//STEP)+2); ds=np.linspace(0,tot,m)
      px=np.interp(ds,cum,pts[:,0]); py=np.interp(ds,cum,pts[:,1])
      sx.append(px); sy.append(py); se.append(np.full(m,e,np.int32)); st.append((ds/tot if tot>0 else np.zeros(m)).astype(np.float32))
  sx=np.concatenate(sx); sy=np.concatenate(sy); se=np.concatenate(se); st=np.concatenate(st)
  np.savez_compressed("data/processed/walk_daegu.npz",osm=osm,x=X,y=Y,eu=eu,ev=ev,el=el,comp=comp.astype(np.int32),big=big,sx=sx,sy=sy,se=se,st=st)
  print("교차점",n,"길",len(el),"이어진 덩어리",nc,f"큰 길망 {big.mean()*100:.1f}%","길 위 점",len(sx))
F=pd.read_csv("data/processed/facilities.csv",dtype=str,usecols=["fid","구군","경도","위도"])
F["x"]=pd.to_numeric(F["경도"],errors="coerce"); F["y"]=pd.to_numeric(F["위도"],errors="coerce"); F=F[F["x"].notna()]
T=cKDTree(np.c_[sx*KX,sy*KY]); d,j=T.query(np.c_[F["x"].values*KX,F["y"].values*KY])
pd.DataFrame({"fid":F["fid"].values,"edge":se[j],"t":np.round(st[j],4),"snap_m":np.round(d,1)}).to_csv("data/processed/facility_walk.csv",index=False,encoding="utf-8")
F["far"]=d>150
print("시설",len(F),"길까지 거리 중앙값",round(float(np.median(d)),1),"m, 150m 넘는 곳",int(F["far"].sum()))
print(F.groupby("구군")["far"].mean().mul(100).round(1).to_string())
