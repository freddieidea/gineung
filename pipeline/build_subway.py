# 대구 도시철도역 → data/processed/subway_stations.csv (전국도시철도역사정보표준데이터 2021-06-30)
# 좌표 점검: 역 이름의 출구 버스정류장('OO역(3번출구)')이 있으면 그 가운데와 비교해 500m 넘게 어긋난 좌표는 출구 정류장 가운데로 고침
#  (실제로 신천역에는 서울 잠실새내역 좌표, 1호선 명덕역에는 약 800m 떨어진 좌표가 들어 있었음)
# 3호선 역 이름의 띄어쓰기('명 덕')를 없애 환승역(반월당·명덕·청라언덕)을 하나로 묶음
import json, re, pandas as pd, numpy as np
d=json.load(open("data/raw/public/도시철도역사_전국.json",encoding="utf-8")); m=dict(zip(d["cols_en"],d["cols_kr"]))
R=pd.DataFrame([{m.get(k,k):v for k,v in r.items()} for r in d["rows"]])
R=R[R["노선명"].fillna("").str.startswith("대구 도시철도")].copy()
R["역"]=R["역사명"].str.replace(" ",""); R["노선"]=R["노선명"].str.replace("대구 도시철도 ","")
R["경도"]=pd.to_numeric(R["역경도"]); R["위도"]=pd.to_numeric(R["역위도"])
B=pd.read_csv("data/processed/bus_stops.csv",dtype={"정류소ID":str}); B["n"]=B["정류소"].str.replace(" ","")
k=np.cos(np.radians(35.87))*111320; R["좌표근거"]=""
for i,r in R.iterrows():
    b=B[B["n"].str.match(rf"^{re.escape(r['역'])}역\(\d+번출구\)$")]
    if len(b)==0: R.at[i,"좌표근거"]="자료 좌표 (출구 정류장이 없어 점검 못 함)"; continue
    cx,cy=b["경도"].median(),b["위도"].median(); dist=float(np.hypot((r["경도"]-cx)*k,(r["위도"]-cy)*110540))
    if dist>500:  # 큰 역은 출구끼리 300m 넘게 떨어지기도 하므로 500m 기준
        R.at[i,"경도"],R.at[i,"위도"]=cx,cy; R.at[i,"좌표근거"]=f"자료 좌표가 {int(dist)}m 어긋나 출구 정류장 {len(b)}곳 가운데로 고침"
        print("좌표 고침:",r["역"],r["노선"],int(dist),"m")
    else: R.at[i,"좌표근거"]=f"자료 좌표 (출구 정류장과 {int(dist)}m)"
assert R["경도"].between(128.3,129.0).all() and R["위도"].between(35.55,36.35).all()
S=R.groupby("역").agg(노선=("노선",lambda x:", ".join(sorted(set(x)))),경도=("경도","mean"),위도=("위도","mean"),
    주소=("역사도로명주소","first"),자료기준일=("데이터기준일자","max"),좌표근거=("좌표근거",lambda x:" / ".join(x))).reset_index()
tr=S[S["노선"].str.contains(",")]
for _,r in tr.iterrows():  # 환승역은 노선별 좌표가 300m 안이어야 함
    g=R[R["역"]==r["역"]]; sp=float(np.hypot((g["경도"].max()-g["경도"].min())*k,(g["위도"].max()-g["위도"].min())*110540))
    assert sp<300,(r["역"],sp)
# 표준데이터(2021)에 빠진 역 보충 (10/15): 1호선 서부정류장역, 2024년 12월 개통한 1호선 연장 구간(대구한의대병원·부호·하양). 좌표는 브이월드 장소 검색의 '지하철역·철도역' 시설
ADD=[("서부정류장","1호선","대구광역시 달서구 송현동 1044-4",128.55715,35.83749,"브이월드 장소 검색 '서부정류장역'(지하철역)"),
     ("대구한의대병원","1호선","대구광역시 동구 사복동 581",128.75144,35.87188,"브이월드 장소 검색 '대구한의대병원역'(지하철역)"),
     ("부호","1호선","경상북도 경산시 하양읍 부호리 194-11",128.80187,35.89986,"브이월드 장소 검색 '부호(경일대.호산대)역'(지하철역)"),
     ("하양","1호선","경상북도 경산시 하양읍 하양역길 1",128.81827,35.90984,"브이월드 장소 검색 '하양역'(철도역, 1호선 연장 구간 종점)")]
for st,ln,ad,x,y,src in ADD:
    if (S["역"]==st).any(): continue
    S=pd.concat([S,pd.DataFrame([{"역":st,"노선":ln,"경도":x,"위도":y,"주소":ad,"자료기준일":"2026-10-15","좌표근거":src}])],ignore_index=True)
S.to_csv("data/processed/subway_stations.csv",index=False,encoding="utf-8")
print("노선별 역",R["노선"].value_counts().to_dict(),"역",len(S),"환승역",list(tr["역"]))
print("점검 못 한 역",int(R["좌표근거"].str.contains("점검 못").sum()),"/",len(R))
