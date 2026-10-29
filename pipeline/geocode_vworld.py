# 공공시설 중 '좌표 필요'인 곳의 좌표를 브이월드(국토교통부 공간정보 오픈플랫폼)로 찾는다 → data/work/vworld_geocode.csv
# - 주소가 있으면 주소 검색(도로명 → 안 되면 지번). 찾은 주소의 구·군이 자료의 구·군과 다르면 버림
# - 주소가 없으면(공공체육시설) 장소 이름 검색. 이름이 띄어쓰기·괄호 빼고 똑같은 곳만 받고, 같은 이름이 300m 넘게 떨어진 여러 곳이면 '여러 곳'으로 버림
# 받은 응답은 data/work/vworld_cache.json에 모아 두어 다시 묻지 않음. 키는 settings/vworld_key.txt (화면에 출력하지 않음)
import json, os, re, time, urllib.request, urllib.parse, pandas as pd, numpy as np
_ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K=open(os.path.join(_ROOT,"settings","vworld_key.txt")).read().strip()
CP=os.path.join(_ROOT,"data","work","vworld_cache.json"); C=json.load(open(CP,encoding="utf-8")) if os.path.exists(CP) else {}
def call(kind,p):
    ck=kind+"|"+json.dumps(p,ensure_ascii=False,sort_keys=True)
    if ck in C: return C[ck]
    url={"addr":"https://api.vworld.kr/req/address","search":"https://api.vworld.kr/req/search"}[kind]
    q=dict(p,key=K,format="json",crs="epsg:4326",version="2.0")
    r=urllib.request.Request(url+"?"+urllib.parse.urlencode(q),headers={"User-Agent":"Mozilla/5.0","Referer":"http://localhost"})
    for t in range(3):
        try: j=json.loads(urllib.request.urlopen(r,timeout=30).read().decode()); break
        except Exception as e: j={"error":str(e)[:200]}; time.sleep(2)
    C[ck]=j.get("response",j); time.sleep(0.05)
    if len(C)%25==0: json.dump(C,open(CP,"w",encoding="utf-8"),ensure_ascii=False)  # 중간 저장
    return C[ck]
GU=["중구","동구","서구","남구","북구","수성구","달서구","달성군","군위군"]
def clean_addr(a):
    a=str(a).replace("경상북도 군위군","대구광역시 군위군")   # 군위군은 2023-07-01 대구광역시로 편입
    a=re.sub(r"(화원|논공|다사|유가|옥포|현풍)면",r"\1읍",a)   # 달성군에서 읍으로 바뀐 면 (예: 현풍면 → 현풍읍, 옥포면 → 옥포읍)
    a=re.sub(r"[가-힣0-9]+동\[([가-힣0-9]+)\]",r"\1",a)          # 행정동[법정동] → 법정동 (예: 신암4동[신암동] → 신암동)
    a=re.sub(r"(\d+)번지\s*(\d+)호",r"\1-\2",a); a=re.sub(r"(\d+)번지",r"\1",a)   # 249번지 12호 → 249-12
    a=re.sub(r"(?<=\s)[가-힣0-9]+(?:동|가)\s+(?=[가-힣0-9]+(?:로|길)\s?\d)","",a)   # 도로명 앞에 붙은 동 이름 (예: 수성동3가 들안로64길 61)
    a=re.sub(r"(로)\s+(\d+길)",r"\1\2",a)                         # 학산로 42길 → 학산로42길
    a=re.sub(r"\(.*?\)","",a).split(",")[0].strip()
    a=re.sub(r"\s+(\d+층|지하\d*층?|\d+호).*$","",a)
    a=re.sub(r"\s+"," ",a)
    m=re.match(r"^(.*?(?:로|길)\s?\d+(?:-\d+)?)(?=\s|$)",a) or re.match(r"^(.*?(?:동|리|가)\s(?:산\s?)?\d+(?:-\d+)?)(?=\s|$)",a)
    if m: a=m.group(1)  # 번지 뒤의 건물·층·호 정보는 뺌
    return a.replace("대구시 ","대구광역시 ")
def anorm(s):
    # 주소 비교용: 괄호·띄어쓰기를 빼고, 시도·구군·읍면 앞부분을 떼어 낸 '도로명+번호' 또는 '동리+(산)번지'
    s=re.sub(r"\(.*?\)","",str(s)).replace(" ","").replace("·",".").replace("번길","길")
    s=re.sub(r"^(대구광역시|대구시|대구|경상북도|경북)","",s)
    s=re.sub(r"^(중구|동구|서구|남구|북구|수성구|달서구|달성군|군위군|칠곡군)","",s)
    s=re.sub(r"^[가-힣]+?(읍|면)(?=[가-힣\d.]*(로|길|동|리|가)산?\d)","",s)
    return s
def by_addr(a,gu):
    a=clean_addr(a); bad="주소로 못 찾음"
    for typ in ("road","parcel"):
        r=call("addr",{"service":"address","request":"getcoord","address":a,"type":typ,"refine":"true","simple":"false"})
        if r.get("status")!="OK": continue
        if anorm(a)!=anorm(r["refined"]["text"]): bad="비슷한 다른 주소로 바뀌어 버림"; continue  # 예: 신암남로 7 → 신암남로11길 7, 28-5 → 산 28-5 (지번으로 한 번 더 찾아 봄)
        st=r["refined"]["structure"]; g=st.get("level2","")
        if gu and g and not g.endswith(gu) and gu not in g: return None,f"주소 검색 결과 구·군이 다름({g})"
        p=r["result"]["point"]; return (float(p["x"]),float(p["y"]),r["refined"]["text"]),f"브이월드 주소 좌표({ '도로명' if typ=='road' else '지번'})"
    return None,bad
norm=lambda s: re.sub(r"[\s()·\-]|제(?=\d)","",str(s))
def by_name(name,gu):
    r=call("search",{"service":"search","request":"search","query":name,"type":"place","size":"30","page":"1","bbox":"128.3,35.55,129.0,36.35"})
    items=(r.get("result") or {}).get("items",[]) if r.get("status")=="OK" else []
    hit=[x for x in items if norm(x["title"])==norm(name)]
    if gu: hit=[x for x in hit if gu in (x["address"].get("road") or "")+(x["address"].get("parcel") or "")]
    if not hit: return None,"이름이 똑같은 장소 없음"
    xs=np.array([[float(x["point"]["x"]),float(x["point"]["y"])] for x in hit])
    k=np.cos(np.radians(35.87))*111320
    spread=max(np.hypot((xs[:,0]-xs[:,0].min())*k,(xs[:,1]-xs[:,1].min())*110540).max(),np.hypot((xs[:,0].max()-xs[:,0])*k,(xs[:,1].max()-xs[:,1])*110540).max())
    if spread>300: return None,f"같은 이름 장소가 여러 곳({len(hit)}곳, {int(spread)}m)"
    a=hit[0]["address"].get("road") or hit[0]["address"].get("parcel")
    return (float(np.median(xs[:,0])),float(np.median(xs[:,1])),a),f"브이월드 장소 이름 검색({len(hit)}건 일치)"
def save_cache(): json.dump(C,open(CP,"w",encoding="utf-8"),ensure_ascii=False)
if __name__=="__main__":   # 함수만 불러 쓸 때(시설 변화 관리)는 아래를 돌리지 않음
    P=pd.read_csv("data/processed/public_facilities.csv",dtype=str)
    todo=P[(P["좌표근거"]=="좌표 필요")|P["좌표근거"].fillna("").str.startswith("브이월드")]  # 다시 돌려도 같은 결과(응답은 저장해 둔 것을 씀)
    out=[]
    for _,r in todo.iterrows():
        gu=r["구군"] if isinstance(r["구군"],str) else ""
        own=isinstance(r["주소"],str) and r["주소"].strip() and not str(r.get("주소근거","") or "").startswith("브이월드")  # 이름 검색으로 얻은 주소는 원자료 주소가 아님
        if own: res,why=by_addr(r["주소"],gu)
        else: res,why=by_name(r["상호"],gu)
        out.append({"fid":r["fid"],"업종코드":r["업종코드"],"상호":r["상호"],"경도":res[0] if res else None,"위도":res[1] if res else None,"찾은주소":res[2] if res else "","근거":why})
    json.dump(C,open(CP,"w",encoding="utf-8"),ensure_ascii=False)
    O=pd.DataFrame(out); O.to_csv("data/work/vworld_geocode.csv",index=False,encoding="utf-8")
    print("찾음",int(O["경도"].notna().sum()),"/",len(O)); print(O.groupby(["업종코드"])["경도"].apply(lambda x:f"{x.notna().sum()}/{len(x)}").to_string())
    print(O[O["경도"].isna()]["근거"].str.replace(r"\(.*","",regex=True).value_counts().to_string())
