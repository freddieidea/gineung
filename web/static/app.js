// 기능상속 화면. 서버(web/server.py)의 /api 를 부름. 키는 화면에 없음
(() => {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const ymd = (d) => { const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(d || ""); return m ? `${+m[1]}년 ${+m[2]}월${m[3] ? ` ${+m[3]}일` : ""}` : ""; };
  const ym = (d) => { const m = /^(\d{4})-(\d{2})/.exec(d || ""); return m ? `${+m[1]}년 ${+m[2]}월` : ""; };
  const api = async (path, body) => {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    let d = {}; try { d = await r.json(); } catch (e) { d = { type: "error", text: "서버와 연결이 끊겼어요. 잠시 뒤 다시 해 주세요." }; }
    if (d.보기전용) toast(d.글);   // 심사용 보기 전용 접속: 실제 반영하는 버튼은 막고 알림만
    if (body) { try { gcTrack(path, body, d); } catch (e) {} }   // 화면에서 한 일 → 업무 보조 대화에 전달
    return d;
  };
  function toast(msg) {
    let t = document.getElementById("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); document.body.append(t); }
    t.textContent = msg; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 3200);
  }

  // ---------- 지도 ----------
  const map = L.map("map", { zoomControl: true }).setView([35.8714, 128.6014], 12);
  // 배경 지도 (10/21): 국토교통부 브이월드 (공공 서비스용, 서버가 대신 받아 넘김: /tiles). 받지 못하면 오픈스트리트맵으로 자동 전환. 색을 낮춰 표시가 잘 보이게 함(style.css)
  const vworld = L.tileLayer("/tiles/{z}/{x}/{y}.png", { minZoom: 6, maxZoom: 19, attribution: '&copy; 국토교통부 브이월드' }).addTo(map);
  let tileFails = 0;
  vworld.on("tileerror", () => {
    if (++tileFails !== 8) return;
    map.removeLayer(vworld);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> 기여자' }).addTo(map);
  });
  const closureLayer = L.layerGroup().addTo(map);
  const resultLayer = L.layerGroup().addTo(map);
  const focusLayer = L.layerGroup().addTo(map);   // 지자체 화면에서 고른 곳 표시
  const pinIndex = new Map();   // 문 닫은 곳 fid → 핀 (목록에서 누르면 그 핀을 엶)
  const icon = (cls, html = "", size = 18) => L.divIcon({ className: "", html: `<div class="pin ${cls}">${html}</div>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2], popupAnchor: [0, -size / 2] });
  // 문 닫은 곳: 빨간 핀 + 내린 셔터 그림 (한눈에 보이게, 헌준님 의견 10/15). 새로 연 가게: 초록 핀 + 가게 그림 + 빨간 점(예전 가게가 문 닫은 자리)
  const SHUTTER = '<g stroke="#fff" stroke-width="1.8" stroke-linecap="round" fill="none"><path d="M9.5 9.5h11v10h-11z"/><path d="M9.5 13h11M9.5 16.3h11"/></g>';
  const STORE = '<g stroke="#fff" stroke-width="1.8" stroke-linejoin="round" fill="none"><path d="M8.5 12.5l1.5-4h10l1.5 4z"/><path d="M10 12.5v7h10v-7"/><path d="M13.5 19.5v-3.5h3v3.5"/></g>';
  const pinSvg = (fill, glyph) => `<svg width="30" height="38" viewBox="0 0 30 38" aria-hidden="true"><path d="M15 36.5S27 24.2 27 15A12 12 0 0 0 3 15c0 9.2 12 21.5 12 21.5z" fill="${fill}" stroke="#fff" stroke-width="2"/>${glyph}</svg>`;
  const pinIcon = (kind, count = 0, cls = "") => {
    const svg = kind === "now" ? pinSvg("#0E7A5F", STORE) : pinSvg("#D93025", SHUTTER);
    const badge = kind === "now" ? '<span class="pin-dot"></span>' : (count > 1 ? `<span class="pin-count">${count}</span>` : "");
    return L.divIcon({ className: cls, html: `<div class="mpin mpin-${kind}">${svg}${badge}</div>`, iconSize: [30, 38], iconAnchor: [15, 37], popupAnchor: [0, -34], tooltipAnchor: [0, -30] });
  };

  // 이 곳이 하는(하던) 일 — 주민 화면과 지자체 화면이 같은 자료(/api/did, Engine.what_it_does)를 씀. 공공 목적이면 근거 법령까지
  function didBox(list, scale, title) {
    const box = el("div", "did");
    if (!list || !list.length) return null;
    if (title) box.append(el("div", "did-h", title));
    const chips = el("div", "did-chips");
    list.slice(0, 6).forEach((d) => { const c = el("span", "did-c" + (d.공공 ? " pub" : "")); if (d.공공) c.append(el("b", null, "공공")); c.append(document.createTextNode(d.이름)); c.title = (d.근거 || []).join(" / "); chips.append(c); });
    box.append(chips);
    const pub = list.filter((d) => d.공공);
    pub.slice(0, 2).forEach((d) => box.append(el("div", "did-law", `${d.이름}: ${d.공공.권리} · ${d.공공.법령}`)));
    const sc = typeof scale === "string" ? scale : (scale && scale.글);
    if (sc) box.append(el("div", "did-law", `규모: ${sc}`));
    return box;
  }
  async function fillDid(holder, fid, title) {
    const d = await api("/api/did?fid=" + encodeURIComponent(fid));
    const b = didBox(d.하던일, d.규모, title); if (b) holder.append(b);
  }

  // 한 자리에 핀 하나. 그 칸에 새 가게가 들어왔으면 핀은 새 가게(지금), 문 닫은 곳은 '예전 이 자리'
  // (10/29) 주민 화면에서는 자료 분류 이름을 사람들이 부르는 말로: '기타 한식 음식점' → '한식 음식점', '일식 회/초밥' → '일식 회·초밥'
  const kw = (u) => String(u || "").replace(/^기타\s*/, "").replace(/\//g, "·");
  function popupFor(pin) {
    const box = el("div");
    const recs = pin.기록;
    if (recs.length > 1) box.append(el("div", "pp-head", `이 건물 폐업 시설 ${recs.length}곳`));
    const list = recs.length > 1 ? [...recs].sort((a, b) => String(b.폐업일자 || "").localeCompare(String(a.폐업일자 || ""))) : recs;   // 최근에 닫은 곳부터
    list.forEach((r) => {
      if (r.지금 && recs.length === 1) {
        const now = el("div", "pp-sec");
        now.append(el("div", "pp-label", "현재 영업 시설"), el("div", "pp-name", r.지금.상호));
        const meta = [kw(r.지금.업종), r.지금.개업일 ? `${ym(r.지금.개업일)} 개업` : ""].filter(Boolean).join(" · ");
        if (meta) now.append(el("div", "pp-meta", meta));
        box.append(now);
      }
      const old = el("div", "pp-sec pp-old");
      if (recs.length === 1) old.append(el("div", "pp-label", r.지금 ? "이전 시설 (폐업)" : "폐업"));
      old.append(el("div", "pp-name", r.상호), el("div", "pp-meta", `${kw(r.업종)} · ${ymd(r.폐업일자)}`));
      if (recs.length === 1 && r.fid) { const h = el("div"); old.append(h); fillDid(h, r.fid, "주요 기능"); }
      if (recs.length > 1) { if (r.지금) old.append(el("div", "pp-meta", `현재 영업: ${r.지금.상호}`)); }
      const b = el("button", "pp-btn", "대체 시설 찾기");
      b.addEventListener("click", () => { map.closePopup(); setMode("resident"); startConv({ fid: r.fid }, r.상호); });
      old.append(b);
      box.append(old);
    });
    return box;
  }
  // 문 닫은 곳은 종류를 골라서 봄 (헌준님 의견 10/16: 한꺼번에 다 띄우면 지저분하고 눈에 잘 안 들어옴)
  // 한 건물에 여러 곳이면 고른 종류에 해당하는 곳만 핀·말풍선에 넣음
  let closurePins = [], closureKinds = [], kindSel = "전체";
  try { kindSel = localStorage.getItem("closureKind") || "전체"; } catch (e) {}
  const kindOk = (r) => kindSel === "전체" || r.분류 === kindSel;
  map.on("popupopen", () => document.getElementById("map").classList.add("pp-open"));   // 말풍선을 여는 동안 지도 설명(범례)이 말풍선을 가리지 않게
  map.on("popupclose", () => document.getElementById("map").classList.remove("pp-open"));
  const topPad = () => {   // 지도 위 종류 버튼 줄 아래로 말풍선이 오게 (버튼에 가려지지 않게)
    const kb = document.getElementById("kindbar"), mp = document.getElementById("map");
    if (!kb || !mp || kb.offsetParent === null) return 24;
    return Math.max(24, Math.round(kb.getBoundingClientRect().bottom - mp.getBoundingClientRect().top + 12));
  };
  // (10/29 헌준님) 한 건물 여러 폐업 말풍선이 너무 작게 열리던 것: 높이를 표시를 만들 때가 아니라 열 때 지도 크기로 다시 잼 (3곳 남짓 보이게)
  const multiH = () => { const h = document.getElementById("map").clientHeight || 600; return Math.max(240, Math.min(440, h - topPad() - 56)); };
  map.on("popupopen", (e) => { const pp = e.popup; if (!pp.options.className || !pp.options.className.includes("pp-multi")) return; const want = multiH(); if (pp.options.maxHeight !== want) { pp.options.maxHeight = want; pp.update(); } });
  function drawClosures() {
    closureLayer.clearLayers(); pinIndex.clear();
    if (kindSel === "안 보기") return;
    closurePins.forEach((p0) => {
      const recs = p0.기록.filter(kindOk);
      if (!recs.length) return;
      const p = { ...p0, 기록: recs };
      const single = recs.length === 1;
      const ic = single && recs[0].지금 ? pinIcon("now", 0, "cl") : pinIcon("closed", recs.length, "cl");
      // (10/29 헌준님: 동촌유원지처럼 한 건물에 여러 곳이면 말풍선이 화면보다 길어져 지도가 멀리 튐) 말풍선 높이를 화면 안으로 두고 안에서 위아래로 넘겨 봄
      const m = L.marker([p.위도, p.경도], { icon: ic, title: recs.map((r) => r.상호).join(", ") }).bindPopup(() => popupFor(p), { maxWidth: single ? 300 : 330, maxHeight: single ? undefined : multiH(), autoPanPadding: [24, 24], autoPanPaddingTopLeft: [24, topPad()], className: single ? "" : "pp-multi" });
      m.addTo(closureLayer);
      recs.forEach((r) => pinIndex.set(r.fid, m));
    });
  }
  function drawKindBar() {
    const bar = document.getElementById("kindbar"); bar.querySelectorAll("button").forEach((b) => b.remove());
    const count = {}; let all = 0;
    closurePins.forEach((p) => p.기록.forEach((r) => { count[r.분류] = (count[r.분류] || 0) + 1; all++; }));
    const opts = [["전체", all], ...closureKinds.filter((k) => count[k]).map((k) => [k, count[k]]), ["안 보기", null]];   // 문 닫은 곳이 없는 종류는 버튼을 만들지 않음
    if (!opts.some(([k]) => k === kindSel)) kindSel = "전체";
    opts.forEach(([k, n]) => {
      const b = el("button", "kb"); b.type = "button"; b.setAttribute("aria-pressed", String(k === kindSel));
      b.append(document.createTextNode(k)); if (n != null) b.append(el("span", "kb-n", String(n)));
      b.addEventListener("click", () => {
        kindSel = k; try { localStorage.setItem("closureKind", k); } catch (e) {}
        bar.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        drawClosures(); drawNearby(); if (govLoaded) drawGov();
      });
      bar.append(b);
    });
  }
  // 문 닫은 곳 핀 (10/23): 페이지를 열어 둔 채로 아침 점검이 지나도 새 폐업·기간이 끝난 곳이 반영되게, 화면으로 돌아올 때·20분마다 다시 받음
  //  바뀐 것이 없거나 주민이 핀 설명을 열어 보고 있으면 다시 그리지 않음 (보던 것이 갑자기 사라지지 않게)
  let closureSig = null, closureAt = 0;
  async function loadClosures(quiet) {
    if (quiet && Date.now() - closureAt < 5 * 60 * 1000) return;
    let d; try { d = await api("/api/closures"); } catch (e) { return; }
    if (!d || !Array.isArray(d.핀)) return;
    closureAt = Date.now();
    const sig = d.핀.flatMap((p) => p.기록.map((r) => r.fid + (r.지금 ? "+" : ""))).sort().join(",");
    if (quiet && (sig === closureSig || document.querySelector("#map .leaflet-popup"))) { if (sig !== closureSig) closureAt = 0; return; }
    closureSig = sig; closurePins = d.핀; closureKinds = d.분류 || closureKinds;
    drawKindBar(); drawClosures(); drawNearby();
  }
  loadClosures();
  setInterval(() => { if (!document.hidden) loadClosures(true); }, 20 * 60 * 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadClosures(true); });
  // 지도의 장소 표시 (복지·공공시설): 따로 켜고 끄지 않고 지도의 일부로 — 확대하면 그림과 이름이 함께 보임 (헌준님 10/16: 따로 빼니 분리된 느낌)
  const pubLayer = L.layerGroup().addTo(map); let pubSeq = 0;
  // 복지시설(보라)·공공시설(파랑)을 색으로 나누고, 시설마다 그림으로 (경로당 집, 복지관 하트, 급식소 그릇, 아동센터 아이, 행정복지센터 관공서, 도서관 책, 보건소 십자, 우체국 편지, 지구대 방패)
  const POI_SVG = {
    house: '<path d="M3 8.2L8 4l5 4.2V13H3z" fill="none" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/><path d="M6.6 13v-2.8h2.8V13" fill="none" stroke="#fff" stroke-width="1.6"/>',
    heart: '<path d="M8 13s-4.6-2.7-4.6-6A2.4 2.4 0 0 1 8 5.6 2.4 2.4 0 0 1 12.6 7c0 3.3-4.6 6-4.6 6z" fill="#fff"/>',
    bowl: '<path d="M2.8 8h10.4a5.2 5.2 0 0 1-10.4 0z" fill="#fff"/><path d="M6 3.2c-.6.8.6 1.4 0 2.4M9.6 3.2c-.6.8.6 1.4 0 2.4" stroke="#fff" stroke-width="1.2" fill="none" stroke-linecap="round"/>',
    child: '<circle cx="8" cy="4.6" r="1.9" fill="#fff"/><path d="M4.6 13c0-2.6 1.5-4.4 3.4-4.4s3.4 1.8 3.4 4.4z" fill="#fff"/>',
    family: '<circle cx="5.6" cy="5" r="1.6" fill="#fff"/><circle cx="10.6" cy="5.6" r="1.3" fill="#fff"/><path d="M2.8 13c0-2.4 1.2-4.2 2.8-4.2s2.8 1.8 2.8 4.2zM8.6 13c0-2 .9-3.4 2-3.4s2 1.4 2 3.4z" fill="#fff"/>',
    care: '<path d="M2.8 9.6l2.6-1.2 3.4 1 2.2-.6c.8-.2 1.4.8.7 1.3L8.4 12 3.6 11.6z" fill="#fff"/><path d="M9.6 6.8S7.6 5.6 7.6 4.4a1 1 0 0 1 2-.3 1 1 0 0 1 2 .3c0 1.2-2 2.4-2 2.4z" fill="#fff"/>',
    gov: '<path d="M2.6 6.2L8 3.4l5.4 2.8z" fill="#fff"/><path d="M4 7.2v4.4M6.6 7.2v4.4M9.4 7.2v4.4M12 7.2v4.4M2.8 12.6h10.4" stroke="#fff" stroke-width="1.4" stroke-linecap="round"/>',
    book: '<path d="M8 5c-1.4-1-3.2-1.2-5-.8v8c1.8-.4 3.6-.2 5 .8 1.4-1 3.2-1.2 5-.8v-8c-1.8-.4-3.6-.2-5 .8zm0 0v8" fill="none" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>',
    cross: '<path d="M6.4 3h3.2v3.4H13v3.2H9.6V13H6.4V9.6H3V6.4h3.4z" fill="#fff"/>',
    mail: '<rect x="2.6" y="4.4" width="10.8" height="7.6" rx="1.2" fill="none" stroke="#fff" stroke-width="1.5"/><path d="M3 5l5 3.8L13 5" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>',
    shield: '<path d="M8 2.8l4.6 1.6v3.4c0 2.8-2 4.6-4.6 5.4-2.6-.8-4.6-2.6-4.6-5.4V4.4z" fill="#fff"/>',
  };
  const pubIcon = (p) => L.divIcon({ className: "", iconSize: [0, 0], popupAnchor: [0, -14],
    html: `<div class="poi ${p.갈래 === "복지" ? "welfare" : "public"}${p.확인필요 ? " dim" : ""}"><span class="poi-i"><svg viewBox="0 0 16 16" aria-hidden="true">${POI_SVG[p.그림] || POI_SVG.gov}</svg></span><span class="poi-n">${p.상호.replace(/^대구광역시\s*/, "")}</span></div>` });
  function pubPopup(p) {
    const box = el("div");
    box.append(el("div", "pp-label", p.종류), el("div", "pp-name", p.상호), el("div", "pp-meta", p.주소));
    (p.안내 || []).forEach((x) => box.append(el("div", "pp-meta", x)));
    if (p.확인필요) box.append(el("div", "pp-meta", "이용 대상이 정해져 있을 수 있어요. 전화로 물어보세요."));
    if (p.전화) { const a = el("a", "pp-tel", "전화 " + p.전화.split(" (")[0]); a.href = "tel:" + p.전화.replace(/[^\d]/g, ""); box.append(a); }
    if (p.fid) {   // 주민 폐업 제보 → AI 교차검증 (분명하면 바로 반영, 공백이 생기는 공공 시설만 담당자 확인). 두 번 눌러야 접수
      const rp = el("button", "btn-text report", "폐업·이전 제보");
      rp.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (rp.dataset.step !== "ask") { rp.dataset.step = "ask"; rp.textContent = "한 번 더 누르면 제보가 접수돼요"; return; }
        rp.disabled = true; const x = await api("/api/report", { fid: p.fid, 내용: "지도 시설 정보에서 제보" });
        rp.replaceWith(el("div", "pp-meta", x.글 || "제보가 접수됐어요."));
      });
      box.append(rp);
    }
    return box;
  }
  async function loadPub() {
    const my = ++pubSeq;
    if (map.getZoom() < 15) { pubLayer.clearLayers(); return; }
    const b = map.getBounds();
    const d = await api(`/api/places?w=${b.getWest()}&s=${b.getSouth()}&e=${b.getEast()}&n=${b.getNorth()}`);
    if (my !== pubSeq) return;
    pubLayer.clearLayers();
    (d.시설 || []).forEach((p) => L.marker([p.위도, p.경도], { icon: pubIcon(p), title: p.상호 }).bindPopup(() => pubPopup(p), { maxWidth: 280 }).addTo(pubLayer));
  }
  map.on("moveend", loadPub); loadPub();
  // 지도 표시 설명: 아래 설명을 누르면 그 표시가 무엇인지, 시설 그림마다 어떤 곳인지 보여 줌 (헌준님 10/19)
  const LEGEND = {
    closed: { t: "폐업 시설", d: "최근 폐업한 생활 시설 · 누르면 주요 기능과 대체 시설 확인 · 지도 위 버튼으로 종류 선택" },
    now: { t: "신규 개업 (폐업 자리)", d: "폐업 시설 자리에 새로 개업한 시설 · 같은 기능이면 대체 시설로 안내" },
    welfare: { t: "복지시설", c: "welfare", items: [["house", "경로당"], ["heart", "노인·사회·장애인복지관"], ["bowl", "무료급식소"], ["child", "지역아동센터·다함께돌봄센터"], ["family", "가족센터"], ["care", "주야간보호·단기보호·정신건강복지센터"]] },
    public: { t: "공공시설", c: "public", items: [["gov", "행정복지센터"], ["book", "도서관·작은도서관"], ["cross", "보건소·건강생활지원센터"], ["mail", "우체국"], ["shield", "지구대·파출소"]] },
  };
  const lgPanel = $("#lg-panel");
  document.querySelectorAll(".lg-btn").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k, open = b.getAttribute("aria-expanded") === "true";
    document.querySelectorAll(".lg-btn").forEach((x) => x.setAttribute("aria-expanded", "false"));
    if (open) { lgPanel.hidden = true; return; }
    b.setAttribute("aria-expanded", "true"); lgPanel.innerHTML = "";
    const L0 = LEGEND[k]; const head = el("div", "lg-p-head"); head.append(el("b", null, L0.t));
    const x = el("button", "lg-p-x", "닫기"); x.type = "button"; x.addEventListener("click", () => { lgPanel.hidden = true; b.setAttribute("aria-expanded", "false"); }); head.append(x);
    lgPanel.append(head);
    if (L0.d) lgPanel.append(el("p", null, L0.d));
    if (L0.items) {
      const ul = el("ul", "lg-p-list");
      L0.items.forEach(([ic, name]) => { const li = el("li"); const i = el("span", `poi-i lg-p-i ${L0.c}`); i.innerHTML = `<svg viewBox="0 0 16 16" aria-hidden="true">${POI_SVG[ic]}</svg>`; li.append(i, el("span", null, name)); ul.append(li); });
      lgPanel.append(ul);
      lgPanel.append(el("p", "lg-p-note", map.getZoom() < 15 ? "지도를 더 확대하면 시설이 보여요." : "시설을 누르면 주소와 전화번호를 볼 수 있어요."));
    }
    lgPanel.hidden = false;
  }));
  // 내 위치로: 지도를 지금 계신 곳으로 옮김 (허용한 경우만)
  const LocateCtl = L.Control.extend({ options: { position: "topleft" }, onAdd() {
    const b = L.DomUtil.create("button", "locate-btn"); b.type = "button"; b.title = "내 위치로"; b.setAttribute("aria-label", "내 위치로");
    b.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="3.2" fill="currentColor"/><circle cx="10" cy="10" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 1.5v3M10 15.5v3M1.5 10h3M15.5 10h3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
    L.DomEvent.disableClickPropagation(b);
    b.addEventListener("click", () => {
      if (!navigator.geolocation) return;
      b.classList.add("busy");
      navigator.geolocation.getCurrentPosition((p) => { b.classList.remove("busy"); const ll = [p.coords.latitude, p.coords.longitude]; map.setView(ll, 16); L.circleMarker(ll, { radius: 7, color: "#fff", weight: 3, fillColor: "#2F6FDB", fillOpacity: 1 }).addTo(map); },
        () => { b.classList.remove("busy"); b.title = "위치를 알 수 없어요. 브라우저에서 위치 허용을 확인해 주세요."; }, { timeout: 8000, maximumAge: 60000 });
    });
    return b;
  } });
  new LocateCtl().addTo(map);
  const zoomClass = () => { const m = document.getElementById("map"); m.classList.toggle("z-far", map.getZoom() < 13); m.classList.toggle("z-poi", map.getZoom() >= 16); };   // 더 확대하면 장소 이름도   // 멀리서 볼 때는 핀을 조금 작게
  map.on("zoomend", zoomClass); zoomClass();

  // ---------- 화면 고르기 ----------
  const tabs = { resident: $("#tab-resident"), gaps: $("#tab-gaps"), gov: $("#tab-gov") };
  function setMode(m) {
    Object.entries(tabs).forEach(([k, b]) => b.setAttribute("aria-selected", String(k === m)));
    $("#resident").hidden = m !== "resident"; $("#gov").hidden = m !== "gov"; $("#gaps").hidden = m !== "gaps";
    // 화면마다 그 화면의 표시만 (섞이지 않게): 주민 = 문 닫은 곳 전체와 대화 결과 / 기능 공백 = 공백이 생긴 폐업 시설 / 지자체 = 에이전트가 보고한 곳
    const res = m === "resident", gov = m === "gov", gp = m === "gaps";
    [resultLayer, closureLayer, routeLayer].forEach((l) => (res ? l.addTo(map) : map.removeLayer(l)));   // 10/25: 주민 화면의 가는 길(점선·버스 선)이 다른 화면에 남던 것
    govLayers(gov);
    gp ? gapLayer.addTo(map) : map.removeLayer(gapLayer);
    focusLayer.clearLayers();
    $("#kindbar").hidden = !res; $(".legend-res").hidden = !res; $(".legend-gaps").hidden = !gp; $("#lg-panel").hidden = true;
    if (gov && !govLoaded) loadGov();
    if (gp) loadGaps();
    gcShow(gov);
  }
  tabs.resident.addEventListener("click", () => setMode("resident"));
  tabs.gaps.addEventListener("click", () => setMode("gaps"));
  tabs.gov.addEventListener("click", () => setMode("gov"));
  $("#gv-tab-report").addEventListener("click", () => setGovSub("report"));
  $("#gv-tab-pre").addEventListener("click", () => setGovSub("pre"));
  // 폐업 사전 검토: 영업 중인 시설을 찾아 '문을 닫는다면'을 계산·판단 (/api/gov/prereview, 결과는 저장하지 않음)
  $("#pre-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const qv = $("#pre-q").value.trim(), ul = $("#pre-list"), st = $("#pre-status");
    ul.innerHTML = ""; st.hidden = false;
    if (qv.replace(/\s/g, "").length < 2) { st.textContent = "시설 이름이나 업종을 두 글자 이상 입력해 주세요."; return; }
    st.textContent = "찾는 중입니다.";
    const d = await api("/api/gov/facility?q=" + encodeURIComponent(qv));
    if (preFail(d, st)) return;
    const list = d.목록;
    st.textContent = list.length ? "검토할 시설을 고르세요." : "영업 중인 시설 가운데 이름·업종이 맞는 곳이 없습니다.";
    list.forEach((r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button";
      const top = el("div", "gv-q-top"); top.append(el("b", null, r.상호), el("span", null, [r.업종, r.구군].filter(Boolean).join(" · ")));
      b.append(top, el("p", null, r.주소 || ""));
      b.addEventListener("click", () => runPre(r));
      li.append(b); ul.append(li);
    });
  });

  // ---------- 주민: 이름으로 찾기 ----------
  const q = $("#q"), sugg = $("#sugg"); let timer = 0, seq = 0;
  // 입력창: 글이 길어지면 옆으로 밀리지 않고 아래로 늘어남 (최대 5줄, 그 뒤는 창 안에서 넘김). Enter는 보내기, Shift+Enter는 줄 바꿈
  function grow(t) {
    t.style.height = "auto"; const max = parseFloat(getComputedStyle(t).lineHeight) * 5 + 4;
    t.style.height = Math.min(t.scrollHeight, max) + "px"; t.style.overflowY = t.scrollHeight > max ? "auto" : "hidden";
  }
  function typeBox(t, form) {
    t.addEventListener("input", () => grow(t));
    t.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); form.requestSubmit(); }
    });
  }
  typeBox(q, $("#ask"));
  q.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const my = ++seq, text = q.value.trim();
      if (text.length < 2) { sugg.hidden = true; return; }
      const d = await api("/api/search?q=" + encodeURIComponent(text));
      if (my !== seq) return;
      sugg.innerHTML = "";
      const rs = d.결과 || [];
      if (!rs.length) { sugg.hidden = true; return; }   // 이름이 없으면 목록 없이 그대로 보내면 에이전트가 알아들음
      rs.forEach((r) => {
        const li = el("li"), b = el("button");
        const nm = el("span", "nm", r.상호);
        if (r.닫음) nm.append(el("span", "tag-closed", r.폐업일자 ? `${ym(r.폐업일자)} 문 닫음` : "문 닫음"));
        b.append(nm, el("span", "meta", `${kw(r.업종)} · ${r.주소}`));
        if (r.새가게) b.append(el("span", "meta", `현재 영업: ${r.새가게}`));
        b.addEventListener("click", () => { sugg.hidden = true; startConv({ fid: r.fid }, r.상호); });
        li.append(b); sugg.append(li);
      });
      sugg.hidden = false;
    }, 220);
  });
  // 지금 위치 (허용하지 않거나 안 되면 null)
  const here = () => new Promise((ok) => {
    if (!navigator.geolocation) return ok(null);
    navigator.geolocation.getCurrentPosition((p) => ok({ 경도: p.coords.longitude, 위도: p.coords.latitude }), () => ok(null), { timeout: 5000, maximumAge: 60000 });
  });
  $("#ask").addEventListener("submit", async (e) => {   // 입력창에 쓴 말로 에이전트와 대화 시작 (지금 위치, 안 되면 지도 가운데)
    e.preventDefault(); const text = q.value.trim(); if (!text) return; sugg.hidden = true;
    const p = await here(); const c = map.getCenter();
    const base = p ? { ...p, 이름: "지금 계신 곳", 종류: "지금 위치" } : { 경도: c.lng, 위도: c.lat, 이름: "지도 가운데", 종류: "지도 가운데" };
    startConv({ ...base, text }, text, text);
  });
  // 이 근처 최근 문 닫은 곳 (지도 가운데에서 가까운 순, 지도를 옮기면 바뀜)
  function drawNearby() {
    const ul = $("#nearby"); if (!ul) return; ul.innerHTML = "";
    const c = map.getCenter(); const items = [];
    closurePins.forEach((p) => p.기록.forEach((r) => { if (kindOk(r)) items.push({ r, d: map.distance(c, [p.위도, p.경도]) }); }));
    items.sort((a, b) => a.d - b.d).slice(0, 8).forEach(({ r, d }) => {
      const li = el("li"), b = el("button");
      b.append(el("span", "nb-name", r.상호), el("span", "nb-meta", `${kw(r.업종)} · ${d < 1000 ? Math.round(d / 10) * 10 + "m" : (d / 1000).toFixed(1) + "km"} · ${ym(r.폐업일자)}`));
      b.addEventListener("click", () => startConv({ fid: r.fid }, r.상호));
      li.append(b); ul.append(li);
    });
    if (!items.length) ul.append(el("li", "empty", "인근 최근 폐업 시설 없음"));
  }
  map.on("moveend", drawNearby);

  // ---------- 주민: 대화 ----------
  let sid = null, origin = null, seek = null, busy = false, useDone = false;
  const log = $("#log"), opts = $("#opts"), msg = $("#msg");
  let lastAsked = "";
  function addMe(text) { lastAsked = String(text || ""); const m = el("div", "msg me", text); log.append(m); m.scrollIntoView({ block: "end" }); }
  // 답이 이상해요 (10/26): 가장 최근 답 아래에만 작게. 동의를 체크해야 보낼 수 있고, 보낸 질문과 답 한 쌍만 저장 (이름·위치 없음)
  function badRow(d) {
    log.querySelectorAll(".bad-row").forEach((x) => x.remove());
    const row = el("div", "bad-row"); const b = el("button", "btn-text bad-btn", "답이 이상해요"); b.type = "button";
    const said = lastAsked, ans = String(d.text || "").replace(/\[카드\]/g, "").replace(/\s+/g, " ").trim();
    b.addEventListener("click", () => {
      row.replaceChildren(); row.classList.add("open");
      const memo = el("textarea", "bad-memo"); memo.rows = 2; memo.placeholder = "어떤 점이 이상했는지 적어 주세요 (적지 않아도 돼요)";
      const lab = el("label", "bad-ok"); const ck = el("input"); ck.type = "checkbox";
      lab.append(ck, el("span", null, "이번 질문과 답을 서비스를 고치는 데 쓰는 것에 동의해요 · 이름과 위치는 남지 않아요"));
      const go = el("button", "btn-solid bad-go", "보내기"); go.type = "button"; go.disabled = true;
      const no = el("button", "btn-text", "취소"); no.type = "button";
      ck.addEventListener("change", () => { go.disabled = !ck.checked; });
      no.addEventListener("click", () => badRow(d));
      go.addEventListener("click", async () => {
        go.disabled = true;
        const x = await api("/api/bad", { sid, 질문: said, 답: ans, 메모: memo.value.slice(0, 300), 동의: ck.checked });
        row.replaceChildren(el("span", "bad-thanks", (x && x.글) || "알려 주셔서 고마워요."));
      });
      const btns = el("div", "bad-btns"); btns.append(no, go);
      row.append(memo, lab, btns); memo.focus();
    });
    row.append(b); log.append(row);
  }
  function addBotText(lines, cls = "msg bot") {
    const m = el("div", cls);
    lines.forEach((t) => {   // 10/25: 이용 안내(나드리콜 등)의 '[이름]' 줄은 괄호 없이 굵은 제목으로
      if (!t || !t.trim()) return;
      const h = t.trim().match(/^\[(.+)\]$/);
      m.append(h ? el("p", "svc-h", h[1]) : el("p", null, t));
    });
    if (m.childNodes.length) log.append(m);
    return m;
  }
  // 블로그 글 목록 (다음 블로그 검색, 그 자리에서 찾아 보여 주기만 함)
  function blogBox(d) {
    const box = el("div", "blogbox");
    const n = d.글수;
    box.append(el("div", "blog-head", n == null ? "블로그 검색이 잠시 안 돼요. 조금 뒤에 다시 눌러 주세요." : n === 0 ? `${d.상호 || "이 가게"} 이야기가 담긴 블로그 글을 찾지 못했어요.` : `${d.상호 || "이 가게"} 이야기가 담긴 블로그 글 ${n}개 · 최근 글`));
    const ul = el("ul", "blog-list");
    (d.글 || []).forEach((p) => {
      const li = el("li"), a = el("a", null, p.제목); a.href = p.주소; a.target = "_blank"; a.rel = "noopener";
      li.append(a, el("span", "blog-meta", [ymd(p.날짜), p.블로그].filter(Boolean).join(" · "))); ul.append(li);
    });
    if ((d.글 || []).length) box.append(ul);
    if (n) box.append(el("div", "blog-foot", "다음 블로그 검색 결과 (광고가 섞여 있을 수 있어요)"));
    return box;
  }
  // 카드: 이름 · 종류 · 가는 길 그림 · (시간 상태) · 주소 · 물어볼 것 · 버튼. 근거·출처 같은 우리끼리의 말은 보여 주지 않음 (헌준님 10/16)
  function cardEl(c, idx) {
    const a = el("div", "alt"); a.dataset.idx = idx;
    a.append(el("div", "rank", String(c.순위 || idx + 1)));
    const name = el("div", "alt-name", c.상호);
    if (c.확실성 === "확인 필요") name.append(el("span", "sure check", "전화로 확인"));   // 주민이 해야 할 일이 있을 때만 표시
    a.append(name);
    // 카드 글은 정리된 값으로만 만듦 (제목 글을 잘라 쓰면 '자격 확인. (노인복지관) — …' 같은 내부 말이 새어 나옴, 헌준님 지적 10/19)
    a.append(el("div", "alt-meta", c.종류 || ""));
    if (c.이동 && c.이동.length) a.append(routeStrip(c.이동));
    else if (c.이동글) a.append(el("div", "alt-meta", c.이동글));
    if (c.기준글) a.append(el("div", "alt-meta alt-from", c.기준글));   // 가는 길은 지금 계신 곳에서, 고른 까닭은 찾는 곳에서 잰 거리
    if (c.까닭 && c.까닭.length) { const w = el("div", "why"); c.까닭.forEach((x) => w.append(el("span", x.주의 ? "warn" : null, x.t))); a.append(w); }   // 왜 이 곳인지 (실제 값으로)
    const body = el("div", "alt-body");
    if (c.시간) {   // 지금 열려 있는지 한눈에
      const h = el("div", "hours");
      h.append(el("span", "hs " + (c.시간.열림 ? "open" : "closed"), c.시간.열림 ? `${c.시간.이름} 중` : `지금은 ${c.시간.이름} 안 해요`));
      if (c.시간.오늘) h.append(el("span", "ht", `오늘 ${c.시간.오늘}`));
      const wk = el("div", "hw", c.시간.요일); wk.title = "국립중앙의료원 자료 (바뀔 수 있어요)";
      body.append(h, wk);
    }
    if (c.주소) body.append(el("div", "addr", c.주소));
    (c.안내 || []).forEach((x) => body.append(el("div", "note", x)));
    if (c.물어볼것 && c.물어볼것.length) body.append(el("div", "ask-tip", "전화로 물어볼 것: " + c.물어볼것.join(", ")));
    const act = el("div", "alt-actions");
    if (c.전화) { const p = el("a", "act", "전화"); p.href = "tel:" + c.전화.replace(/[^\d]/g, ""); p.title = c.전화; act.append(p); }
    if (c.길찾기) { const g = el("a", "act", "길찾기"); g.href = c.길찾기; g.target = "_blank"; g.rel = "noopener"; act.append(g); }
    if (c.누리집) { const w = el("a", "act", "누리집"); w.href = /^https?:/.test(c.누리집) ? c.누리집 : "http://" + c.누리집; w.target = "_blank"; w.rel = "noopener"; act.append(w); }
    body.append(act); a.append(body);
    if (c.fid) {   // 주민 폐업 제보 → AI 교차검증 (분명하면 바로 반영, 공백이 생기는 공공 시설만 지자체 화면 '폐업 확인 필요')
      const rp = el("button", "btn-text report", "폐업·이전 제보");
      rp.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (rp.dataset.step !== "ask") { rp.dataset.step = "ask"; rp.textContent = "한 번 더 누르면 제보가 접수돼요"; return; }
        rp.disabled = true; const x = await api("/api/report", { fid: c.fid, 내용: "주민 화면 카드에서 제보" });
        rp.replaceWith(el("div", "note", x.글 || "제보가 접수됐어요."));
      });
      body.append(rp);
    }
    if (c.블로그 && c.fid) {
      const b = el("a", "act", "블로그"); b.href = "#"; act.append(b);
      let shown = null;
      b.addEventListener("click", async (e) => {
        e.preventDefault(); e.stopPropagation();
        if (shown) { shown.remove(); shown = null; b.textContent = "블로그"; return; }
        b.textContent = "찾는 중…";
        const d = await api("/api/blog?fid=" + encodeURIComponent(c.fid));
        shown = blogBox(d); body.append(shown); b.textContent = "블로그 접기";
      });
    }
    return a;
  }
  // ---------- 가는 길 그림 (카드 띠 + 지도 선) ----------
  const SUBWAY = { "1호선": "#D93F42", "2호선": "#00A54F", "3호선": "#F0A800" };   // 대구 도시철도 노선 색
  const BUS = "#2F6FDB", BUS2 = "#0F9D7A", WALK = "#5D6B69", CAR = "#4B4FA8";   // 갈아탄 두 번째 버스는 다른 색 (10/25)
  const ICON = {
    walk: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="9" cy="2.6" r="1.6"/><path d="M7.6 5.2l-2 1.4-.9 2.6m2.9-4l-.8 4.2 2 1.8.8 3.6m-2.8-5.4l-1.6 5.4M9 5.4l1.3 2.2 2 .6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    bus: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="2" width="10" height="10.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M3 8h10M5.5 12.5v1.5m5-1.5v1.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    subway: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2" width="9" height="10" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 14l1.5-2m3.5 2L9 12M3.5 7.5h9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    car: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 10V8l1.4-3.4h8.2L13.5 8v2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><rect x="2" y="8" width="12" height="3.5" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="5" cy="12.5" r="1"/><circle cx="11" cy="12.5" r="1"/></svg>',
  };
  const svgI = (k) => { const s = el("span", "rs-i"); s.innerHTML = ICON[k]; return s; };
  function routeStrip(segs) {
    const box = el("div", "rs"); const bar = el("div", "rs-bar"); const cap = el("div", "rs-cap");
    const total = segs.reduce((n, g) => n + (g.t === "walk" ? g.분 : g.t === "bus" ? Math.max(4, g.비율 || 8) : 0), 0) || 1;
    segs.forEach((g) => {
      if (g.t === "walk") {
        const seg = el("div", "rs-seg rs-walk"); seg.style.flexGrow = String(Math.max(0.6, g.분 / total * 10));
        seg.append(svgI("walk"), el("span", null, `${g.분}분`)); if (segs.length === 1 && g.m) seg.append(el("span", "rs-sub", `${g.m.toLocaleString("ko-KR")}m`));
        bar.append(seg);
      } else if (g.t === "bus") {
        const col = g.지하철 ? (SUBWAY[g.노선[0]] || BUS) : (g.환승 ? BUS2 : BUS);
        const seg = el("div", "rs-seg rs-ride"); seg.style.flexGrow = String(Math.max(2.2, (g.비율 || 8) / total * 10)); seg.style.setProperty("--c", col);
        seg.append(svgI(g.지하철 ? "subway" : "bus"));
        g.노선.slice(0, 3).forEach((r) => seg.append(el("span", "rs-no", r)));
        seg.title = g.노선.join(", ");
        bar.append(seg);
        const stop = (n) => g.지하철 ? (/역$/.test(n) ? n : n + "역") : (/정류장$/.test(n) ? n : n + " 정류장");
        const what = g.지하철 ? g.노선[0] : `${g.노선.slice(0, 2).join("·")}번 버스`;
        cap.append(el("p", null, g.환승 ? `${stop(g.탈곳)}에서 ${what}${g.지하철 ? "으로" : "로"} 갈아타서 ${stop(g.내릴곳)}에서 내려요.` : `${stop(g.탈곳)}에서 ${what}${g.지하철 ? "을" : "를"} 타서 ${stop(g.내릴곳)}에서 내려요.`));
        if (g.배차) cap.append(el("p", "rs-sub2", `${g.지하철 ? "지하철" : "버스"}는 ${g.배차}분마다 와요.`));
        if (!g.지하철 && !segs.some((x) => x.t === "bus" && x.환승) || g.환승) cap.append(el("p", "rs-sub2", "지도의 버스 길은 노선 정류장 자료로 그린 길이라 실제와 조금 다를 수 있어요. 정확한 길은 '길찾기'에서 볼 수 있어요."));
      } else if (g.t === "car") {
        const seg = el("div", "rs-seg rs-car"); seg.append(svgI("car"), el("span", null, `${g.분}분`), el("span", "rs-sub", `${g.km}km`)); bar.append(seg);
        if (g.요금) cap.append(el("p", null, `택시비는 약 ${Number(g.요금).toLocaleString("ko-KR")}원이에요.`));
      } else if (g.t === "transfer") {
        const seg = el("div", "rs-seg rs-transfer"); seg.append(svgI("bus"), el("span", null, "갈아타야 해요")); bar.append(seg);
        cap.append(el("p", null, "한 번에 가는 노선이 없어요. 갈아타는 길은 카카오맵 길찾기에서 볼 수 있어요."));
      } else if (g.t === "none") {
        const seg = el("div", "rs-seg rs-transfer"); seg.append(svgI("bus"), el("span", null, "가까운 정류장 없음")); bar.append(seg);
      }
    });
    box.append(bar); if (cap.childElementCount) box.append(cap);
    return box;
  }
  const routeLayer = L.layerGroup().addTo(map);
  const stopIcon = (col, label) => L.divIcon({ className: "", html: `<div class="stoppin" style="--c:${col}"><span>${label}</span></div>`, iconSize: [0, 0] });
  function drawRoute(card) {   // 고른 카드의 가는 길을 지도에 (걷는 길은 점선, 버스·지하철은 색 선)
    routeLayer.clearLayers();
    if (!card || !card.경로) return null;
    const pts = [];
    card.경로.forEach((r) => {
      if (!r.선 || r.선.length < 2) return;
      if (r.t === "walk") L.polyline(r.선, { color: WALK, weight: 5, opacity: .9, dashArray: "1 9", lineCap: "round" }).addTo(routeLayer);
      else if (r.t === "car") { L.polyline(r.선, { color: "#fff", weight: 10, opacity: .9 }).addTo(routeLayer); L.polyline(r.선, { color: CAR, weight: 6, opacity: .95 }).addTo(routeLayer); }   // (10/26) 차로 가는 길
      else {
        const col = r.지하철 ? (SUBWAY[r.노선[0]] || BUS) : (r.환승 ? BUS2 : BUS);
        L.polyline(r.선, { color: "#fff", weight: 10, opacity: .9 }).addTo(routeLayer);
        L.polyline(r.선, { color: col, weight: 6, opacity: .95 }).addTo(routeLayer);
        L.marker(r.선[0], { icon: stopIcon(col, r.환승 ? "환승" : "승차"), interactive: false, zIndexOffset: r.환승 ? 700 : 0 }).addTo(routeLayer);
        if (!r.이어짐) L.marker(r.선[r.선.length - 1], { icon: stopIcon(col, "하차"), interactive: false }).addTo(routeLayer);   // 갈아타는 곳은 다음 버스의 '환승' 표시 하나만
        const mid = r.선[Math.floor(r.선.length / 2)];   // 선 가운데에 노선 번호 (지도 앱처럼 어느 버스를 타는지 지도에서 바로)
        L.marker(mid, { icon: L.divIcon({ className: "", html: `<div class="busno" style="--c:${col}">${ICON[r.지하철 ? "subway" : "bus"]}<span>${(r.노선 || []).slice(0, 2).map((x) => String(x).replace(/[<>&"]/g, "")).join(" · ")}</span></div>`, iconSize: [0, 0] }), interactive: false, zIndexOffset: 600 }).addTo(routeLayer);
      }
      pts.push(...r.선);
    });
    return pts;
  }
  function drawResults(cards) {
    resultLayer.clearLayers();
    const pts = [];
    if (origin) {   // 문 닫은 곳에서 출발하면 지도와 같은 빨간 핀, 지도 가운데·장소에서 출발하면 검은 점
      const oi = origin.닫음 ? pinIcon("closed") : icon("pin-origin", "", 22);
      L.marker([origin.위도, origin.경도], { icon: oi, zIndexOffset: 500 }).bindTooltip(origin.이름, { direction: "top", offset: origin.닫음 ? [0, -2] : [0, -12], permanent: true }).addTo(resultLayer);
      pts.push([origin.위도, origin.경도]);
    }
    if (seek) {
      const si = seek.닫음 ? pinIcon("closed") : icon("pin-origin", "", 22);
      L.marker([seek.위도, seek.경도], { icon: si, zIndexOffset: 400 }).bindTooltip(seek.이름, { direction: "top", offset: seek.닫음 ? [0, -2] : [0, -12] }).addTo(resultLayer);
    }
    const marks = [];
    cards.forEach((c, i) => {
      if (c.위도 == null) { marks.push(null); return; }
      const m = L.marker([c.위도, c.경도], { icon: icon("pin-rank", String(c.순위 || i + 1), 28), zIndexOffset: 1000 - i, title: c.상호 }).addTo(resultLayer);
      m.bindTooltip(`${c.순위 || i + 1}순위 ${c.상호}`, { direction: "top", offset: [0, -14] });
      marks.push(m); pts.push([c.위도, c.경도]);
    });
    document.getElementById("map").classList.toggle("has-result", cards.length > 0);   // 대안을 보는 동안 다른 문 닫은 곳 핀은 흐리게
    const rp = drawRoute(cards[0]);   // 처음에는 1순위 가는 길
    const focus = rp && rp.length > 1 ? rp.concat(origin ? [[origin.위도, origin.경도]] : [], cards[0] && cards[0].위도 != null ? [[cards[0].위도, cards[0].경도]] : []) : pts;   // 길이 있으면 그 길에 맞춰 (다른 순위 핀은 화면에 들어오면 함께 보임)
    if (focus.length > 1) map.fitBounds(focus, { padding: [80, 80], maxZoom: 17 });
    else if (focus.length === 1) map.setView(focus[0], 16);
    return marks;
  }
  // 대화창 위 기준 줄: 찾는 곳(어디 근처에서 고르는지)과 출발지(가는 길을 어디서 보여 주는지)를 나눠 보여 줌 (10/25 헌준님)
  //  문 닫은 곳에서 시작: [내 위치에서 출발] 고른 곳 그대로 가는 길만 / [내 주변에서 찾기] 지금 계신 곳 가까이에서 새로
  const O_BTN = { 출발: "내 위치에서 출발", 찾기: "내 주변에서 찾기", 다른곳: "다른 곳" };
  function showOrigin(o) {
    if (!o) return;
    $("#originbar").hidden = false;
    $("#origin-name").textContent = String(o.말 || o.이름 || "").replace(/\s*근처$/, "");
    const st = $("#o-start"); st.hidden = !o.출발; st.textContent = o.출발 ? `${o.출발}에서 출발` : "";
    const acts = $("#o-acts"); acts.innerHTML = "";
    (o.버튼 || []).forEach((k) => {
      const b = el("button", "btn-text", k === "처음" ? `${o.처음 || "처음 곳"} 근처로` : O_BTN[k] || k); b.type = "button";
      b.addEventListener("click", () => originAct(k)); acts.append(b);
    });
  }
  async function originAct(k) {
    if (busy || !sid) return;
    if (k === "다른곳") { addBotText(["어디 근처에서 찾을까요? (예: 서문시장 근처)"]); msg.focus(); return; }
    const body = { sid, 할일: k };
    if (k !== "처음") {
      const p = await here();
      if (!p) { addBotText(["지금 위치를 찾지 못했어요. 위치 사용을 허용해 주시거나 '서문시장 근처'처럼 말씀해 주세요."]); return; }
      Object.assign(body, p, { 이름: "지금 계신 곳", 종류: "지금 위치" });
    }
    busy = true; const wait = addBotText([k === "출발" ? "가는 길을 찾는 중이에요…" : "찾는 중이에요…"]);
    const d = await api("/api/origin", body);
    wait.remove(); busy = false; render(d);
  }
  function render(d, steps) {
    opts.innerHTML = "";
    const work = (steps || []).filter((x) => /골랐어요|확인/.test(x));
    if (work.length) { const w = el("div", "msg bot worked"); w.append(el("span", "wk-i", "✓"), el("span", null, work.join(" · "))); log.append(w); }
    showOrigin(d.기준);
    const firstNew = log.childElementCount;   // 이번 답의 첫 부분부터 보이게 (카드가 길면 1순위가 위로 밀려 안 보이던 것 고침)
    if (d.출발) origin = d.출발;
    seek = d.찾는곳 || null;   // 출발지가 따로 있을 때 찾는 곳(문 닫은 곳 자리)도 지도에 표시
    const blocks = d.blocks && d.blocks.length ? d.blocks : [{ text: d.text || "" }];
    let buf = [], cards = [], cardBox = null; const cardNodes = [];
    const flush = () => { if (buf.length) { addBotText(buf, d.위급 ? "msg note" : "msg bot"); buf = []; } };
    blocks.forEach((b) => {
      if (b.blog) { flush(); cardBox = null; const m = el("div", "msg bot"); m.append(blogBox(b.blog)); log.append(m); return; }
      if (b.links) {   // 대화 모델이 인터넷에서 찾은 내용의 출처
        flush(); cardBox = null;
        const box = el("div", "msg bot src"); box.append(el("span", "src-label", "출처"));
        b.links.forEach((l) => { const a = el("a", null, l.제목 || l.url); a.href = l.url; a.target = "_blank"; a.rel = "noopener"; box.append(a); });
        log.append(box); return;
      }
      if (b.card) {
        flush();
        if (!cardBox) { cardBox = el("div", "msg bot cards"); log.append(cardBox); }
        const ce = cardEl(b.card, cards.length); cardBox.append(ce); cardNodes.push(ce); cards.push(b.card);
      } else { if (cardBox) cardBox = null; buf.push(...String(b.text || "").split("\n")); }
    });
    flush();
    if (cards.length) {   // 10/25: 카드나 지도의 번호 핀을 누르면 그 곳으로 가는 길 (전에는 '맨 마지막 카드 묶음'만 찾아서, 카드 뒤에 글이 붙으면 눌러도 반응이 없었음)
      const marks = drawResults(cards);
      let selI = 0;   // 지금 지도에 길이 그려진 카드 (마우스를 올리면 미리 보기, 떼면 고른 카드의 길로 되돌림)
      const pick = (i) => {
        selI = i; const m = marks[i]; const rp = drawRoute(cards[i]);
        cardNodes.forEach((x, k) => x.classList.toggle("sel", k === i));
        if (rp && rp.length > 1) map.fitBounds(rp.concat(m ? [[m.getLatLng().lat, m.getLatLng().lng]] : []), { padding: [60, 60], maxZoom: 18 });
        else if (m) map.setView(m.getLatLng(), Math.max(map.getZoom(), 16));
        if (m) m.openTooltip();
      };
      cardNodes.forEach((a, i) => {
        const m = marks[i];
        a.addEventListener("click", (e) => { if (e.target.closest("a, button")) return; pick(i); });
        a.addEventListener("mouseenter", () => { drawRoute(cards[i]); a.classList.add("on"); m && m.getElement() && m.getElement().firstChild.classList.add("on"); });
        a.addEventListener("mouseleave", () => { a.classList.remove("on"); m && m.getElement() && m.getElement().firstChild.classList.remove("on"); if (selI !== i) drawRoute(cards[selI]); });
      });
      marks.forEach((m, i) => m && m.on("click", () => { pick(i); cardNodes[i] && cardNodes[i].scrollIntoView({ block: "nearest", behavior: "smooth" }); }));
      if (cardNodes[0]) cardNodes[0].classList.add("sel");
    }
    if (cards.length && sid && !useDone) {   // 이용 결과 (대화마다 한 번): 다녀옴 / 맞는 곳 없음 → 지자체 '주민 이용 결과'·주민 수요
      log.querySelectorAll(".use-ask").forEach((x) => x.remove());
      const box = el("div", "msg bot use-ask"); box.append(el("span", "use-q", "안내받은 곳을 이용해 보셨나요?"));
      const row = el("div", "use-btns");
      [["다녀왔어요", "다녀옴"], ["맞는 곳이 없었어요", "맞는 곳 없음"]].forEach(([t, v]) => {
        const b = el("button", "btn-chip", t); b.type = "button";
        b.addEventListener("click", async () => {
          useDone = true; row.querySelectorAll("button").forEach((x) => (x.disabled = true));
          const x = await api("/api/use", { sid, 결과: v });
          box.replaceChildren(el("span", "use-q", (x && x.글) || "알려 주셔서 고마워요."));
        });
        row.append(b);
      });
      box.append(row); log.append(box);
    }
    if (sid && d.text && !["limit", "expired", "error", "end"].includes(d.type)) badRow(d);
    if (d.질문 && d.질문.length) askBox(d);   // 찾기 전에 한 번에 여쭙는 것 (이동·누구와·언제). 다 고르면 바로 찾음
    (d.options || []).forEach((o) => {
      const b = el("button", null, o);
      b.addEventListener("click", () => send(o));
      opts.append(b);
    });
    const calls = [];
    if (d.connect && d.connect.전화) calls.push(d.connect);
    (d.connect_options || []).forEach((c) => c && c.전화 && calls.push(c));
    calls.forEach((c) => { const a = el("a", "call", `${c.이름} 전화 걸기`); a.href = "tel:" + String(c.전화).replace(/[^\d]/g, ""); opts.append(a); });
    if (d.type === "end" || d.type === "limit" || d.type === "expired") {
      const b = el("button", null, "처음부터 다시 찾기"); b.addEventListener("click", reset); opts.append(b);
    }
    const head = log.children[firstNew] || log.lastElementChild;
    head && head.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  // 서버가 보내는 흐름(SSE)을 읽음: session · status(에이전트가 하는 일) · text(답 글 조각) · reset · done(최종 화면)
  async function stream(path, body, on) {
    let r;
    try { r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
    catch (e) { on("done", { type: "error", text: "서버와 연결이 끊겼어요. 잠시 뒤 다시 해 주세요." }); return; }
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "", got = false;
    for (;;) {
      const { value, done } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = (/^event: (.*)$/m.exec(chunk) || [])[1], data = (/^data: (.*)$/m.exec(chunk) || [])[1];
        if (ev && data) { if (ev === "done") got = true; try { on(ev, JSON.parse(data)); } catch (e) {} }
      }
    }
    if (!got) on("done", { type: "error", text: "답을 받지 못했어요. 다시 한번 말씀해 주세요." });
  }
  // 에이전트가 일하는 모습: 단계 목록(지금 하는 일은 움직이는 점, 끝난 일은 체크) + 흘러나오는 답 글
  function liveBubble() {
    const m = el("div", "msg bot live"); const steps = el("ul", "steps"); const txt = el("p", "live-text");
    const think = el("li", "step now", "생각하는 중"); steps.append(think);
    m.append(steps, txt); log.append(m); m.scrollIntoView({ block: "end", behavior: "smooth" });
    return {
      status(t) { steps.querySelectorAll(".now").forEach((x) => x.classList.replace("now", "ok")); const li = el("li", "step now", t); steps.append(li); },
      text(t) { if (!txt.textContent) steps.querySelectorAll(".now").forEach((x) => x.classList.replace("now", "ok")); txt.textContent += t; m.scrollIntoView({ block: "end" }); },
      reset() { txt.textContent = ""; this.status("답을 다듬는 중"); },
      finish() { steps.querySelectorAll(".now").forEach((x) => x.classList.replace("now", "ok")); const n = steps.children.length; const done = [...steps.children].map((x) => x.textContent).filter((x) => x !== "생각하는 중"); m.remove(); return done; },
    };
  }
  function onStream(lb, after) {
    return (ev, d) => {
      if (ev === "session") { sid = d.sid; if (d.출발) { origin = d.출발; drawResults([]); map.setView([origin.위도, origin.경도], Math.max(map.getZoom(), 15)); } showOrigin(d.기준); }
      else if (ev === "status") lb.status(d);
      else if (ev === "text") lb.text(d);
      else if (ev === "reset") lb.reset();
      else if (ev === "done") { const steps = lb.finish(); if (d.sid) sid = d.sid; if (d.제목) $("#chat-title").textContent = d.제목; render(d, steps); busy = false; after && after(); }
    };
  }
  // 위치 사용을 이미 허용한 경우에만 조용히 지금 위치를 받음 (묻는 창을 띄우지 않음)
  async function hereIfAllowed() {
    try { const q = await navigator.permissions.query({ name: "geolocation" }); if (q.state !== "granted") return null; } catch (e) { return null; }
    return here();
  }
  async function startConv(body, title, said) {
    useDone = false;   // 새 대화마다 이용 결과를 한 번 물음
    if (busy) return; busy = true;
    if (body.fid && body.지금경도 == null) { const p = await hereIfAllowed(); if (p) body = { ...body, 지금경도: p.경도, 지금위도: p.위도 }; }
    $("#start").hidden = true; $("#chat").hidden = false;
    log.innerHTML = ""; opts.innerHTML = ""; resultLayer.clearLayers(); routeLayer.clearLayers();
    $("#chat-title").textContent = body.fid ? `${title} 대체 시설` : "대체 시설 찾기";   // 주민이 쓴 문장은 대화에 그대로 보이고, 제목은 짧게
    if (said) addMe(said);
    const lb = liveBubble();
    await stream("/api/start_stream", body, onStream(lb, () => msg.focus()));
  }
  // 고르기 질문: 그 시설이 하던 일에 맞는 것만 (무엇을 하러 → 고른 일에 따라 '누구랑'·'언제'가 나타남). 보이는 묶음을 다 고르면 바로 찾음
  function askBox(d) {
    const box = el("div", "msg bot ask"); const picked = {}; const rows = [];
    const visible = (g) => !g.보일때 || Object.entries(g.보일때).every(([k, vs]) => vs.includes(picked[k]));
    const refresh = () => {
      rows.forEach(({ g, row }) => { const v = visible(g); row.hidden = !v; if (!v) delete picked[g.key]; });
      const shown = rows.filter(({ g }) => visible(g));
      if (shown.length && shown.every(({ g }) => picked[g.key])) setTimeout(() => go(shown.map(({ g }) => picked[g.key]).join(" · ")), 250);
    };
    const go = (label) => {
      if (busy || box.dataset.sent) return; box.dataset.sent = "1";
      box.querySelectorAll("button").forEach((b) => (b.disabled = true));
      sendAnswers(picked, label);
    };
    d.질문.forEach((g) => {
      const row = el("div", "ask-row"); row.append(el("div", "ask-q", g.말));
      const chips = el("div", "ask-chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", g.말);
      g.보기.forEach((v, i) => {
        const b = el("button", "ask-chip"); b.type = "button"; b.setAttribute("aria-pressed", "false");
        b.append(el("span", null, v)); const sub = (g.설명 || [])[i]; if (sub) b.append(el("span", "ask-sub", sub));
        b.addEventListener("click", () => {
          picked[g.key] = v;
          chips.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
          refresh();
        });
        chips.append(b);
      });
      row.append(chips); box.append(row); rows.push({ g, row });
    });
    if (d.바로) { const sk = el("button", "ask-skip", d.바로); sk.type = "button"; sk.addEventListener("click", () => { for (const k in picked) delete picked[k]; go(d.바로); }); box.append(sk); }
    log.append(box); rows.forEach(({ g, row }) => (row.hidden = !visible(g)));
  }
  async function sendAnswers(ans, label) {
    if (busy || !sid) return;
    busy = true; addMe(label); opts.innerHTML = "";
    const wait = addBotText(["찾는 중이에요…"]);
    const d = await api("/api/turn", { sid, text: label, answers: ans });
    wait.remove(); busy = false;
    if (d.제목) $("#chat-title").textContent = d.제목;
    render(d);
  }
  async function send(text) {
    text = String(text || "").trim();
    if (!text || busy || !sid) return;
    busy = true; addMe(text); opts.innerHTML = "";
    const lb = liveBubble();
    await stream("/api/turn_stream", { sid, text }, onStream(lb));
  }
  function reset() {
    sid = null; origin = null; seek = null; resultLayer.clearLayers(); routeLayer.clearLayers(); drawNearby(); document.getElementById("map").classList.remove("has-result"); $("#originbar").hidden = true;
    $("#chat").hidden = true; $("#start").hidden = false; q.value = ""; grow(q); sugg.hidden = true; q.focus();
  }
  typeBox(msg, $("#say"));
  $("#say").addEventListener("submit", (e) => { e.preventDefault(); const t = msg.value; msg.value = ""; grow(msg); send(t); });
  $("#restart").addEventListener("click", reset);

  // ---------- 지자체: 담당 공무원의 비서 ----------
  // 대화창이 아님. 평일 아침마다 새 자료를 받아 살펴보고, 정말 심각한 공공·복지 공백만 보고함 (engine/gov_agent.py, engine/severity.py)
  let govLoaded = false, govGu = "", brief = null, govPoll = 0, lessons = [];
  try { govGu = localStorage.getItem("govGu") || ""; } catch (e) {}
  // 시설 상태 표시 (10/22 헌준님): 지도 핀·말풍선·대화 목록 꼬리표를 같은 규칙으로 — 문 닫은 곳(네모·셔터) / 운영 확인 필요(노랑 ?) / 영업 중(초록 원, 닫으면 공백 우려는 주황 테두리)
  function ST(k) {
    k = String(k || "");
    if (/긴급/.test(k)) return { f: "closed", c: "urgent", t: "폐업 · 긴급" };
    if (/주의/.test(k)) return { f: "closed", c: "attn", t: "폐업 · 주의" };
    if (/관찰/.test(k)) return { f: "closed", c: "watch", t: "폐업 · 지켜볼 곳" };
    if (/공백 해소/.test(k)) return { f: "closed", c: "none", t: "폐업 · 공백 해소" };
    if (/검토 완료|공백 없음/.test(k)) return { f: "closed", c: "none", t: "폐업 · 공백 없음" };
    if (/판단 확인/.test(k)) return { f: "ask", c: "ask", t: "판단 확인 필요" };
    if (/제보/.test(k)) return { f: "ask", c: "ask", t: "주민 제보 · 확인 중" };
    if (/폐업 확인/.test(k)) return { f: "ask", c: "ask", t: "운영 확인 필요" };
    if (/단절/.test(k)) return { f: "open", c: "risk", t: "영업 중 · 단절 우려" };
    if (/사전 검토/.test(k)) return { f: "open", c: "pre", t: "영업 중 · 폐업 가정 검토" };
    if (/영업/.test(k)) return { f: "open", c: "open", t: "영업 중" };
    return { f: "ref", c: "ref", t: k || "선택한 시설" };
  }
  const ST_SVG = {
    closed: '<svg viewBox="0 0 20 20" aria-hidden="true"><g stroke="#fff" stroke-width="1.7" stroke-linecap="round" fill="none"><path d="M4.5 5.5h11v9h-11z"/><path d="M4.5 8.5h11M4.5 11.5h11"/></g></svg>',
    open: '<svg viewBox="0 0 20 20" aria-hidden="true"><g stroke="#fff" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round" fill="none"><path d="M4 8.5 5.5 4.5h9L16 8.5"/><path d="M4 8.5h12"/><path d="M5.5 8.5v7h9v-7"/><path d="M8.5 15.5v-4h3v4"/></g></svg>',
    ask: '<b>?</b>', ref: "",
  };
  function stIcon(s, big) {
    const z = big ? 30 : 24;
    return L.divIcon({ className: "", html: `<div class="spin ${s.f} ${s.c}${big ? " big" : ""}">${ST_SVG[s.f] || ""}${s.c === "risk" ? '<i class="spin-b">!</i>' : ""}</div>`, iconSize: [z, z], iconAnchor: [z / 2, z / 2], tooltipAnchor: [0, -z / 2] });
  }
  function stTip(name, s) {   // 말풍선: 이름 + 상태 꼬리표 (이름은 글자로만 넣음)
    const w = el("div", "stip-in"); w.append(el("b", null, name || ""), el("span", `stt ${s.f} ${s.c}`, s.t)); return w;
  }
  const govLayer = L.layerGroup(), areaLayer = L.layerGroup(), gapLayer = L.layerGroup(), selLayer = L.layerGroup(), preLayer = L.layerGroup();
  // 지자체 화면 안의 두 칸: 오늘의 보고(실제) / 폐업 사전 검토(가정). 지도 표시도 칸마다 따로 (섞이지 않게)
  let govSub = "report";
  function govLayers(on) {
    const rep = on && govSub === "report", pre = on && govSub === "pre";
    [govLayer, areaLayer, selLayer].forEach((l) => (rep ? l.addTo(map) : map.removeLayer(l)));
    pre ? preLayer.addTo(map) : map.removeLayer(preLayer);
    $(".legend-gov").hidden = !rep; $(".legend-pre").hidden = !pre;
  }
  function setGovSub(k) {
    if (govSub !== k) gcLayer.clearLayers();   // 10/25: 보고·사전 검토 칸을 바꾸면 업무 보조의 지도 표시를 지움
    govSub = k;
    $("#gv-tab-report").setAttribute("aria-selected", String(k === "report")); $("#gv-tab-pre").setAttribute("aria-selected", String(k === "pre"));
    $("#gv-report").hidden = k !== "report"; $("#gv-pre").hidden = k !== "pre";
    $("#gv-date").hidden = k !== "report";
    govLayers(true);
  }
  // 지자체 화면에서 목록의 시설을 누르면 위치 표시 (10/20): 공백 심각도 시설(색 핀·공백 구역)과 구분되는 회색 표시 하나만, 구분 이름을 함께
  function showRef(r, kind) {
    if (!r || r.위도 == null || r.경도 == null) return;
    areaLayer.clearLayers(); selLayer.clearLayers();
    const s = ST(kind || r.구분);
    L.marker([+r.위도, +r.경도], { icon: stIcon(s, true), zIndexOffset: 900 })
      .bindTooltip(stTip(r.상호, s), { permanent: true, direction: "top", className: "stip", offset: [0, -16] }).addTo(selLayer);
    map.setView([+r.위도, +r.경도], Math.max(map.getZoom(), 16));
  }
  function refBtn(r, kind) {   // 목록 안에 다른 버튼이 있는 행에 붙이는 '위치 보기'
    const b = el("button", "btn-text gv-loc", "위치 보기"); b.type = "button";
    b.addEventListener("click", (e) => { e.stopPropagation(); showRef(r, kind); });
    return b;
  }
  const LV = { "긴급": "urgent", "주의": "attn", "관찰": "watch" };
  const won = (n) => (n || 0).toLocaleString("ko-KR");
  const km = (m, cap) => (m == null ? "" : m >= (cap || 30000) ? `${Math.round((cap || 30000) / 1000)}km 이상` : `${(m / 1000).toFixed(1).replace(/\.0$/, "")}km`);
  const jo = (w, pair) => { const c = (w || "").charCodeAt((w || "").length - 1); const h = c >= 0xAC00 && c <= 0xD7A3; return w + (h ? ((c - 0xAC00) % 28 ? pair[0] : pair[1]) : pair[0] + "(" + pair[1] + ")"); };
  // 공백 심각도 단계 설명 (보고 화면 기준표 · 사전 검토 결과에 함께 씀)
  const LV_DESC = { 긴급: "생명·돌봄 기능 단절 · 즉시 조치", 주의: "대체 수단 부족 · 조치 검토", 관찰: "공백 있음 · 조치 불필요 · 매일 재검토", "해당 없음": "공백 없음 또는 생활 필수 기능 아님" };
  const DOW = ["일", "월", "화", "수", "목", "금", "토"];
  const dayLabel = (d) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || ""); if (!m) return ""; const dt = new Date(+m[1], +m[2] - 1, +m[3]); return `${+m[2]}월 ${+m[3]}일(${DOW[dt.getDay()]})`; };
  const bDay = () => (brief && brief.날짜 ? dayShort(brief.날짜) : "오늘");   // (10/29 헌준님) '오늘' 대신 보고서 날짜로 적어 객관적으로
  const clock = (iso) => { const m = /T(\d{2}):(\d{2})/.exec(iso || ""); if (!m) return ""; const h = +m[1]; return `${h < 12 ? "오전" : "오후"} ${h % 12 || 12}시${+m[2] ? ` ${+m[2]}분` : ""}`; };
  function drawGov() {}   // (예전 '전체 목록' 자리. 종류 고르기에서 부름)
  // 담당자 접속 코드 (지자체 화면 잠금)
  function govLock(msg) {
    govLoaded = false;
    let box = $("#gv-lock");
    if (!box) {
      box = el("form", "gv-lock"); box.id = "gv-lock";
      box.append(el("h2", null, "담당자 확인"), el("p", "gv-lead", "지자체 화면은 담당 공무원 전용입니다. 접속 코드를 입력해 주십시오."));
      const inp = el("input"); inp.type = "password"; inp.autocapitalize = "characters"; inp.autocomplete = "current-password"; inp.placeholder = "접속 코드"; inp.setAttribute("aria-label", "접속 코드");
      const go = el("button", "btn-chip solid", "확인"); go.type = "submit"; const err = el("p", "gv-lock-err"); err.setAttribute("role", "alert");
      const row = el("div", "gv-lock-row"); row.append(inp, go); box.append(row, err);
      // (10/29 헌준님) 심사 기간 안내: 심사용 보기 전용 코드 + 정식 운영 시 개인별 코드 발급
      const guide = el("div", "gv-lock-guide"); guide.hidden = true; box.append(guide);
      api("/api/gov-guide").then((g) => {
        if (!g || !g.심사코드) return;
        const r1 = el("p", "gv-lock-code"); r1.append(el("span", null, "심사용 접속 코드"), el("b", null, g.심사코드));
        guide.append(r1, el("p", "gv-lock-note", "심사 기간 고정 코드 · 모든 기능 이용 가능 · 처리 내용 서버 미반영"), el("p", "gv-lock-note", "정식 운영 시 담당자 신원 확인 후 개인별 접속 코드 발급"));
        guide.hidden = false;
      });
      box.addEventListener("submit", async (e) => {
        e.preventDefault(); go.disabled = true;
        const x = await api("/api/gov/login", { code: inp.value });
        go.disabled = false;
        if (x.ok) { box.remove(); $("#gov").classList.remove("locked"); loadGov(); } else { err.textContent = x.글 || "확인하지 못했습니다."; inp.select(); }
      });
      $("#gov").prepend(box);
    }
    $("#gov").classList.add("locked"); gcShow(false);
    const err = box.querySelector(".gv-lock-err"); if (msg && err) err.textContent = "";
    setTimeout(() => { const i = box.querySelector("input"); if (i) i.focus(); }, 50);
  }
  let govSeen = null, govWatch = 0;   // 화면에 보이는 보고서를 만든 점검의 시작 시각
  async function loadGov() {
    govLoaded = true;
    const d = await api("/api/gov/brief");
    if (d.잠김) return govLock();
    brief = d.보고서; lessons = d.배운원칙 || []; drawRun(d); drawBrief();
    viewOnly(d.권한 === "심사"); gcRole = d.권한; gcShow(!$("#gov").hidden);
    govSeen = (d.점검 || {}).시작 || null;
    if (d.진행) watchRun();
    if (!govWatch) govWatch = setInterval(govCheck, 60 * 1000);   // 새로고침 없이: 평일 아침 자동 점검이 시작되면 진행 모습을, 끝나면 새 보고서를 바로 보여 줌
  }
  async function govCheck() {
    if (document.hidden || $("#gov").hidden || govPoll) return;
    let s; try { s = await api("/api/gov/status"); } catch (e) { return; }
    if (!s || s.잠김) return;
    if (s.진행 || (s.점검시작 && s.점검시작 !== govSeen)) loadGov();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && govLoaded) govCheck(); });   // 다른 창을 보다 돌아오면 바로 확인
  // 심사용 보기 전용 표시 (10/21)
  function viewOnly(on) {
    let b = $("#gv-view");
    if (!on) { if (b) b.remove(); return; }
    if (!b) { b = el("p", "gv-view", "심사용 접속 · 모든 기능 이용 가능 · 처리 내용 서버 미반영"); b.id = "gv-view"; $(".gov-head").append(b); }
  }
  // 에이전트가 한 일
  function drawRun(d) {
    const box = $("#gv-run"); box.innerHTML = "";
    const run = d.진행 || d.점검, live = !!d.진행;
    const head = el("div", "gv-run-head");
    const dot = el("span", "gv-dot" + (live ? " live" : "")); dot.setAttribute("aria-hidden", "true");
    const t = el("div", "gv-run-t");
    const today = new Date(); const isToday = run && run.시작.slice(0, 10) === (d.오늘 || `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`);
    if (live) t.append(el("b", null, "점검 중"), el("span", null, "완료 시 보고서 즉시 반영"));
    else if (run) t.append(el("b", null, `${dayLabel(run.시작)} ${clock(run.시작)} 점검 완료`), el("span", null, `${d.일정 || "평일 오전 8시 30분"} 인허가 자료 자동 점검`));
    else t.append(el("b", null, "점검 기록 없음"), el("span", null, "서버 가동 시 즉시 점검"));
    head.append(dot, t);
    const again = el("button", "btn-chip", live ? "점검 중" : "다시 점검"); again.disabled = live;
    again.addEventListener("click", async () => { again.disabled = true; again.textContent = "점검 중"; const r = await api("/api/gov/run", {}); if (r.시작 || r.글) watchRun(); });
    head.append(again); box.append(head);
    if (run && run.단계 && run.단계.length) {
      const steps = el("ol", "gv-steps" + (live ? " open" : ""));
      run.단계.forEach((s) => {
        const li = el("li", "st-" + ({ "완료": "done", "진행": "doing", "실패": "fail", "미룸": "wait" }[s.상태] || "done"));
        li.append(el("span", "gv-step-n", s.단계)); if (s.글) li.append(el("span", "gv-step-t", s.글));
        steps.append(li);
      });
      if (!live) {
        const tg = el("button", "btn-text gv-log", "점검 내역"); tg.setAttribute("aria-expanded", "false");
        tg.addEventListener("click", () => { const o = steps.classList.toggle("open"); tg.setAttribute("aria-expanded", String(o)); tg.textContent = o ? "점검 내역 접기" : "점검 내역"; });
        box.append(tg);
      }
      box.append(steps);
    }
  }
  function watchRun() {
    clearInterval(govPoll);
    govPoll = setInterval(async () => {
      const d = await api("/api/gov/brief"); drawRun(d);
      if (!d.진행) { clearInterval(govPoll); govPoll = 0; govSeen = (d.점검 || {}).시작 || govSeen; brief = d.보고서; lessons = d.배운원칙 || []; drawBrief(); }
    }, 2000);
  }
  // 보고서
  function drawBrief(fit) {
    const gus = $("#gv-gus"); gus.innerHTML = ""; $("#gv-items").innerHTML = "";
    if (!brief) { $("#gv-stat").innerHTML = ""; $("#gv-stat").append(el("div", "gv-stat-l", "아직 보고서가 없습니다")); return; }
    $("#gv-date").textContent = `${dayLabel(brief.날짜)} 보고`;
    const G = brief.구군, names = Object.keys(G);
    const nWatch = (g) => (G[g].보고안함 || []).filter((r) => r.관찰).length;   // (10/26) 숫자는 늘 목록에서 셈 — 칸 숫자와 목록이 어긋나 '관찰 1'인데 시설이 안 보이던 것
    const cnt = (gs) => gs.reduce((a, g) => ({ 긴급: a.긴급 + G[g].긴급, 주의: a.주의 + G[g].주의, 관찰: a.관찰 + nWatch(g) }), { 긴급: 0, 주의: 0, 관찰: 0 });
    const chip = (key, label, c) => {
      const b = el("button", "gv-gu"); b.type = "button"; b.setAttribute("aria-pressed", String(govGu === key));
      b.append(el("span", null, label));
      if (c.긴급) b.append(el("span", "n urgent", String(c.긴급)));
      if (c.주의) b.append(el("span", "n attn", String(c.주의)));
      if (c.관찰) b.append(el("span", "n watch", String(c.관찰)));
      if (!c.긴급 && !c.주의 && !c.관찰) b.classList.add("calm");
      b.addEventListener("click", () => { const was = govGu; govGu = key; try { localStorage.setItem("govGu", key); } catch (e) {} areaLayer.clearLayers(); selLayer.clearLayers(); gcLayer.clearLayers(); drawBrief(true); if (was !== key) gcScope(); });
      gus.append(b);
    };
    chip("", "대구 전체", cnt(names)); names.forEach((g) => chip(g, g, cnt([g])));
    const sel = govGu ? [govGu] : names;
    const items = sel.flatMap((g) => G[g].항목.map((r) => ({ ...r, 구군: g })));
    const c = cnt(sel);
    const asks = sel.flatMap((g) => (G[g].확인요청 || []).map((r) => ({ ...r, 구군: g })));
    const qs = sel.flatMap((g) => (G[g].질문 || []).map((r) => ({ ...r, 구군: g })));
    // 맨 위 두 칸: 담당자가 오늘 볼 것 (누르면 그 목록으로)
    const st = $("#gv-stat"); st.innerHTML = "";
    const tile = (cls, label, n, sub, target) => {
      const t = el("button", "gv-tile " + cls + (n ? "" : " zero")); t.type = "button";
      const h = el("span", "gv-tile-l", label), v = el("span", "gv-tile-n"); v.append(el("b", null, String(n)), el("span", null, "곳"));
      t.append(h, v, el("span", "gv-tile-s", sub));
      t.addEventListener("click", () => $(target).scrollIntoView({ behavior: "smooth", block: "start" }));
      st.append(t);
    };
    tile("check", "폐업 확인 필요", asks.length, asks.length ? "담당자 확인 대기" : "오늘 없음", "#gv-ask");
    {   // 공백 심각도: 긴급·주의·관찰 각각의 수 (관찰도 담당자에게 알림 — AI가 매일 주시 중)
      const t = el("button", "gv-tile urgent sev" + (c.긴급 + c.주의 + c.관찰 ? "" : " zero")); t.type = "button";
      const nums = el("span", "gv-sev-nums");
      [["긴급", "urgent"], ["주의", "attn"], ["관찰", "watch"]].forEach(([k, cls]) => {
        const x = el("span", "gv-sev " + cls + (c[k] ? "" : " zero")); x.append(el("span", null, k), el("b", null, String(c[k]))); nums.append(x);
      });
      t.append(el("span", "gv-tile-l", "공백 심각도"), nums);
      t.addEventListener("click", () => $("#gv-gap").scrollIntoView({ behavior: "smooth", block: "start" }));
      st.append(t);
    }
    const sum = $("#gv-sum"); sum.textContent = govGu && items.length ? String(G[govGu].요약 || "") : ""; sum.hidden = !sum.textContent;
    const order = (a, b) => (a.처리 ? 1 : 0) - (b.처리 ? 1 : 0);
    const urg = items.filter((r) => r.등급 === "긴급").sort(order), attn = items.filter((r) => r.등급 !== "긴급").sort(order);
    {   // 제목 옆: 단계 이름과 수를 함께 (색만으로 단계를 구분하지 않게, 10/21)
      const gn = $("#gv-gap-n"); gn.innerHTML = "";
      const lv = [["긴급", urg.length, "urgent"], ["주의", attn.length, "attn"], ["관찰", c.관찰, "watch"]].filter((x) => x[1]);
      if (!lv.length) gn.append(el("span", "gv-n", "없음"));
      lv.forEach(([k, n, cls]) => gn.append(el("span", "gv-n " + cls, `${k} ${n}`)));
    }
    const ol = $("#gv-items"), ol2 = $("#gv-items2"); ol2.innerHTML = "";
    urg.forEach((r) => ol.append(itemCard(r))); attn.forEach((r) => ol2.append(itemCard(r)));
    $("#gv-urg-h").hidden = !urg.length; $("#gv-urg-n").textContent = String(urg.length);
    $("#gv-attn-h").hidden = !attn.length; $("#gv-attn-n").textContent = String(attn.length);
    const empty = $("#gv-gap-empty");
    empty.textContent = urg.length + attn.length + c.관찰 ? "" : "오늘 없음";
    const other = sel.reduce((n, g) => n + (G[g].대상아님_오늘 || 0), 0), on = $("#gv-quiet-other");   // 오늘 확정분만 ('검토 완료'와 같은 날 기준, 10/26)
    on.hidden = !other; on.textContent = other ? `판정 대상 아님 ${won(other)}곳(${bDay()} 확정분) · 카페·음식점·오락 등` : "";
    empty.hidden = !empty.textContent;
    drawAsk(asks, qs);
    const wait = (brief.확인대기 || []).filter((r) => !govGu || r.구군 === govGu), wn = $("#gv-ask-wait");
    wn.hidden = !wait.length;
    wn.hidden = true;   // (10/22) 담당자가 할 일이 없는 곳(공백 없는 미확정 시설)을 AI가 계속 확인한다는 속사정은 보이지 않음

    drawQuiet(sel.flatMap((g) => (G[g].보고안함 || []).map((r) => ({ ...r, 구군: g }))));
    drawReports(brief.제보검토, brief.제보대기 || 0);
    drawDemand((brief.주민수요 || []).filter((r) => !govGu || r.구군 === govGu));
    drawUse(brief.이용결과 || {}); drawResident();
    drawSolved((brief.해소 || []).filter((r) => !govGu || r.구군 === govGu));
    drawLastOne((brief.하나남은곳 || []).filter((r) => !govGu || r.구군 === govGu));
    drawSport((brief.체육공원 || []).filter((r) => !govGu || r.구군 === govGu));
    drawRules(brief.보고기준);
    drawLessons(); drawGovPins(items);
    if (fit) {
      const ps = items.filter((r) => r.위도).map((r) => [+r.위도, +r.경도]);
      if (ps.length > 1) map.fitBounds(L.latLngBounds(ps).pad(0.3), { maxZoom: 15 });
      else if (ps.length === 1) map.setView(ps[0], 14);
      else if (!govGu) map.setView([35.8714, 128.6014], 11);
    }
  }
  // 거리 그림: 그전·지금 거리와 기준선 (체감 기준, 대구에서 가장 멀리 다니는 5%)
  function distBar(sv, fname) {   // 영향 주민이 가장 가까운 곳까지 가는 거리: 폐업 전·후 두 막대와 보고 기준선 (그림 하나로 읽히게)
    const b = sv.거리_전_m, a = sv.거리_후_m; if (b == null || a == null) return null;
    const cap = sv.잰거리_m || 30000, far = a >= cap, thr = sv.기준_m;
    const max = far ? cap : Math.max(a, thr || 0) * 1.12;
    const pct = (v) => `${Math.max(1.5, Math.min(100, (v / max) * 100))}%`;
    const box = el("div", "dchart"); box.setAttribute("role", "img");
    box.setAttribute("aria-label", `가장 가까운 ${fname}까지 폐업 전 ${km(b, cap)}, 폐업 후 ${km(a, cap)}, 보고 기준 ${km(thr)}`);
    box.append(el("p", "dchart-t", `가장 가까운 ${fname}까지 거리`));
    const rows = el("div", "dchart-rows");
    [["폐업 전", b, "ok"], ["폐업 후", a, far ? "bad far" : "bad"]].forEach(([lab, v, cls]) => {
      const row = el("div", "dchart-row"); const bar = el("div", "dchart-bar"); const fill = el("span", "dchart-fill " + cls); fill.style.width = pct(v);
      bar.append(fill); row.append(el("span", "dchart-lab", lab), bar, el("b", "dchart-v " + cls.split(" ")[0], km(v, cap))); rows.append(row);
    });
    if (thr) { const t = el("span", "dchart-thr"); t.style.left = `calc(52px + (100% - 52px - 76px) * ${Math.min(1, thr / max)})`; t.append(el("span", null, `보고 기준 ${km(thr)}`)); rows.append(t); }
    box.append(rows);
    return box;
  }
  function itemCard(r, pre) {   // pre: 폐업 사전 검토(가정) — 처리·의견·판단 바로잡기 버튼 없음, 실제 보고와 다른 표시
    const dec = pre ? r.판단 : r.등급;
    const li = el("li", "gv-item lv-" + (LV[dec] || "none") + (r.처리 ? " done" : "") + (pre ? " pre" : ""));
    const top = el("div", "gv-i-top");
    if (pre) top.append(el("span", "lv pre", "사전 검토"));
    top.append(el("span", "lv " + (LV[dec] || "none"), dec), el("h3", "gv-i-name", r.상호));
    if (pre && LV_DESC[dec]) top.append(el("p", "gv-lvdesc", `${dec}: ${LV_DESC[dec]}`));
    if (!pre && r.새로) top.append(el("span", "gv-new", "새 보고"));
    if (!pre && r.처리) top.append(el("span", "gv-donetag", "처리 완료"));
    li.append(top);
    li.append(el("p", "gv-i-meta", [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), pre ? "폐업 가정" : `${ymd(r.폐업일자)} 폐업`].join(" · ")));
    if (r.요약) li.append(el("p", "gv-i-sum", r.요약));
    const sv = r.심각 || {};
    const imp = el("div", "gv-impact"); const nums = el("div", "gv-nums");
    const n = (v, lab, cls = "") => { const d = el("div", "gv-num " + cls); d.append(el("b", null, v), el("span", null, lab)); nums.append(d); };
    if ("정원" in sv) {   // 등록해 다니는 기관 (유치원·어린이집·요양): 옮겨야 할 이용자와 받을 곳
      if (sv.현원) n(`${won(sv.현원)}명`, "타 기관 이전 대상 아동", "warn");
      else n(sv.정원 ? `${won(sv.정원)}명` : "확인 필요", "타 기관 이전 대상 이용자 (정원)", "warn");
      n(sv.가장가까운같은기관_m ? km(sv.가장가까운같은기관_m) : "-", "최근접 동종 기관");
      if (sv.주변_여유정원 != null) n(`${won(sv.주변_여유정원)}명`, "2km 내 동종 기관 여유 정원");
      imp.append(nums);
    } else {
      const lost = sv.마을 ? "5km 내" : `${km(sv.기준_m)} 내`, fn = r.기능 || "이용 시설";
      if (sv.아이) n(`${won(sv.밀려난_아이)}명`, `${lost} ${fn} 이용이 어려워지는 ${sv.아이}`, "warn");
      else { n(`${won(sv.밀려난주민)}명`, `${lost} ${fn} 이용이 어려워지는 주민`, "warn"); n(`${won(sv.밀려난_65세이상)}명`, "그중 65세 이상"); }
      nums.classList.add("two"); imp.append(nums);
      if (!sv.마을) { const bar = distBar(sv, fn); if (bar) imp.append(bar); }
    }
    li.append(imp);
    if (r.검토 && r.검토.결과) {   // 보고 전 스스로 한 검토 (계산 교차검증 · 독립 검토관): 결과만 한 줄, 판단에 쓸 참고만 아래에
      (r.검토.참고 || []).filter((x) => !/잰 범위|측정 범위/.test(x)).slice(0, 2).forEach((x) => li.append(el("p", "gv-check-note", x)));
    }
    const sec = (title, cls) => { const s = el("section", "gv-sec " + cls); s.append(el("h4", null, title)); return s; };
    if (r.위험 && r.위험.length) { const s = sec("예상되는 문제", "risk"); const ul = el("ul"); r.위험.forEach((x) => ul.append(el("li", null, x))); s.append(ul); li.append(s); }
    if (r.이어받을자원 && r.이어받을자원.length) {   // 기능상속: 사라진 기능을 이어받을 지역 자원 (공급처 → 공동 수령 거점)
      const s = sec("대체 자원 연계", "relay"); const ul = el("ul");
      r.이어받을자원.forEach((x) => { const i = el("li"); i.append(el("b", null, x.역할), el("span", null, x.글)); ul.append(i); });
      s.append(ul); li.append(s);
    }
    if (r.대응 && r.대응.length) {
      const s = sec("검토하실 일", "act"); const ul = el("ul");
      r.대응.forEach((x) => {
        const i = el("li"); if (x.종류 === "법정 확인") i.append(el("span", "must", "법정 확인"));
        else if (x.종류 === "기관 협의") i.append(el("span", "must ask", "건의·협의"));
        else if (x.종류 === "정부 사업") i.append(el("span", "must ask", "정부 사업"));
        i.append(el("span", null, x.할일)); if (x.담당) i.append(el("span", "owner", x.담당));
        if (x.맞춤) i.append(el("span", "fit", x.맞춤));
        if (x.근거) i.append(el("span", "law", x.근거));
        if (x.요청문) {   // 관련 기관에 보낼 연계 요청문 (계산한 사실로 만든 글)
          const cp = el("button", "btn-text gv-copy", "연계 요청문 복사"); cp.type = "button";
          cp.addEventListener("click", async () => {
            try { await navigator.clipboard.writeText(x.요청문); cp.textContent = "복사했습니다"; }
            catch (e) { const ta = el("textarea", "gv-reqtext"); ta.value = x.요청문; ta.readOnly = true; cp.replaceWith(ta); ta.select(); }
          });
          i.append(cp);
        }
        ul.append(i);
      });
      s.append(ul); li.append(s);
    }
    if (r.판단까닭) { const j = el("p", "gv-judge"); j.append(el("b", null, "판단 근거 "), document.createTextNode(r.판단까닭)); li.append(j); }
    const did = didBox(r.하던일, (r.하던일 || []).map((d) => d.규모).find(Boolean), "주요 기능"); if (did) li.append(did);
    if (r.대체시설 && r.대체시설.length) {
      const s = sec("가까운 대체 시설", "alts"); const ul = el("ul", "gv-alts");
      r.대체시설.forEach((a, i) => { const x = el("li"); x.append(el("span", "alt-n", String(i + 1)), el("span", "alt-name", a.상호), el("span", "alt-t", a.걷는시간_분 != null && a.걷는시간_분 <= 40 ? `걸어서 ${Math.round(a.걷는시간_분)}분` : a.직선_m ? `직선 ${(a.직선_m / 1000).toFixed(1)}km` : "")); ul.append(x); });
      s.append(ul); li.append(s);
    }
    const why = el("details", "gv-why"); why.append(el("summary", null, "계산 방법"));
    const basis = [];
    if (sv.기준_m) basis.push(`보고 기준 거리 ${km(sv.기준_m)}${sv.까닭 ? " · " + String(sv.까닭).replace(/[.。]\s*$/, "") : ""} · 기준값과 대구 주민 실제 이동 거리 중 큰 값 적용`);
    basis.push("인원: 행정동 인구의 100m 격자 배분 추정치 · 거리: 도보 경로 기준");
    const wl = el("ul"); basis.forEach((x) => wl.append(el("li", null, x))); why.append(wl);
    li.append(why);
    if (pre) {   // 사전 검토: 지도 보기만
      const acts = el("div", "gv-acts"); const go = el("button", "btn-chip", "지도에서 보기"); go.addEventListener("click", () => focusPre(r)); acts.append(go); li.append(acts);
      return li;
    }
    const acts = el("div", "gv-acts");
    const go = el("button", "btn-chip", "지도에서 보기"); go.addEventListener("click", () => focusItem(r));
    const done = el("button", "btn-chip " + (r.처리 ? "" : "solid"), r.처리 ? "처리 취소" : "처리 완료");
    const save = async (body) => {
      done.disabled = true;
      const x = await api("/api/gov/mark", { fid: r.fid, ...body });
      if (x.ok) { for (const g of Object.values(brief.구군)) for (const it of g.항목) if (it.fid === r.fid) it.처리 = x.처리 || null; drawBrief(); }
      else done.disabled = false;
    };
    done.addEventListener("click", () => {
      if (r.처리) return save({ done: false });
      // 처리 완료: 한 일을 고르고(선택) 저장 → AI가 그 뒤 공백이 풀렸는지 매일 확인
      const f = el("form", "gv-doneform");
      f.append(el("p", "gv-doneform-h", "조치 내용 (선택 사항)"));
      (r.대응 || []).forEach((a) => { const lb = el("label", "gv-chk"); const c = el("input"); c.type = "checkbox"; c.value = a.id; lb.append(c, document.createTextNode(" " + a.할일)); f.append(lb); });
      const memo = el("input", "gv-memo"); memo.placeholder = "메모 (예: 보건소 방문건강관리팀에 연계)"; memo.maxLength = 200; f.append(memo);
      const ok = el("button", "btn-chip solid", "저장"); ok.type = "submit"; f.append(ok);
      f.addEventListener("submit", (e) => { e.preventDefault(); save({ done: true, 메모: memo.value, 한일: [...f.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value) }); });
      done.replaceWith(f);
    });
    acts.append(go, done, askAI(r, r.등급));
    if (r.처리) acts.append(el("span", "gv-donewhen", `${ymd((r.처리.때 || "").slice(0, 10))} 처리`));
    if (r.보고유지) li.append(el("p", "gv-follow", "주민 안내 기간 종료 · 처리 표시 또는 공백 해소 전까지 보고 유지"));
    if (r.후속) li.append(el("p", "gv-follow", `${ymd(r.후속.처음)} 첫 보고` + (r.후속.처음_주민 && r.후속.지금_주민 != null ? ` · 영향 주민 ${won(r.후속.처음_주민)}명 → ${won(r.후속.지금_주민)}명` : "") + " · 매일 재확인"));
    li.append(acts);
    li.append(teach(r.fid, "이 보고에 의견 보내기"));
    li.append(fixBtn(r.fid, "보고 불필요 시 선택", "관찰"));
    return li;
  }
  // 살펴봤지만 보고하지 않은 공공·복지 시설: 이름·폐업일과 까닭 한 줄만
  const KIND_TAG = { "공백 없음": "k-none", "공백 경미": "k-low" };
  function drawQuiet(list) {   // 공백 심각도 '관찰'(보고 제외·매일 재판단)은 공백 심각도 안에, '해당 없음'은 참고 > 검토 완료 (10/21)
    const row = (r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button";
      const top = el("div", "gv-q-top"); top.append(el("b", null, r.상호));
      if (r.관찰) top.prepend(el("span", "lv watch", "관찰"));
      else if (r.구분 === "공백 경미") top.append(el("span", "gv-tag kind " + KIND_TAG[r.구분], r.구분));   // 검토 완료는 모두 공백 없음이라 '경미'만 표시
      top.append(el("span", null, [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), `${dayShort(r.폐업일자)} ${r.확정상태 === "운영 중단" ? "운영 중단" : "폐업"}`,
        r.확정일 ? `${dayShort(r.확정일)} 확정` + (r.확정근거 ? `(${r.확정근거})` : "") : "", r.공개까지 ? `${dayShort(r.공개까지)}까지 안내` : ""].filter(Boolean).join(" · ")));
      b.append(top, el("p", null, r.까닭));
      b.addEventListener("click", () => { showRef(r, r.관찰 ? "공백 심각도 · 관찰" : "검토 완료 · " + (r.구분 || "공백 없음")); gcNote(r, r.관찰 ? "관찰" : "검토 완료"); });
      li.append(b); if (r.관찰) li.append(fixBtn(r.fid, "조치 필요(주의 이상)로 올리기", "보고"));
      if (r.관찰) li.append(askAI(r, "관찰")); return li;
    };
    const watch = list.filter((r) => r.관찰), allNone = list.filter((r) => !r.관찰);
    const none = allNone.filter((r) => brief && r.확정일 === brief.날짜);   // 담당자에게는 오늘 확정분만 (이전 확정분은 AI가 안내 기간 동안 관리, 업무 보조에서 조회)
    $("#gv-watch-h").hidden = !watch.length; $("#gv-watch-n").textContent = String(watch.length);
    const wl = $("#gv-watch-list"); wl.innerHTML = ""; watch.forEach((r) => wl.append(row(r)));
    $("#gv-quiet").hidden = !none.length && !$("#gv-quiet-other").textContent; $("#gv-quiet-n").textContent = none.length ? `${none.length}곳` : "";
    $("#gv-quiet-today").textContent = (none.length ? `검토 완료 ${none.length}곳(${bDay()} 확정분)` : `검토 완료 해당 없음(${bDay()} 확정분)`) + " · 이전 확정분은 업무 보조에서 조회";
    none.sort((a, b) => (b.확정일 || "").localeCompare(a.확정일 || ""));   // 최근 확정 먼저
    // 검토 완료 (10/21 재정리): ① 공공·복지·의료는 한 곳씩 ② 민간 생활 시설은 공백 경미만 한 곳씩, 공백 없음은 업종별로 묶음(눌러서 펼침)
    const nl = $("#gv-quiet-list"); nl.innerHTML = "";
    const pub = none.filter((r) => r.공공), prv = none.filter((r) => !r.공공);
    const head = (t, n, sub) => { const h = el("li", "gv-qhead"); h.append(el("b", null, t), el("span", null, `${n}곳`)); if (sub) h.append(el("span", "gv-sub", sub)); return h; };
    if (pub.length) { nl.append(head("공공·복지·의료", pub.length)); pub.forEach((r) => nl.append(row(r))); }
    if (prv.length) {
      nl.append(head("민간 생활 시설", prv.length, "식료품·미용·세탁 등 · 업종별"));
      prv.filter((r) => r.구분 === "공백 경미").forEach((r) => nl.append(row(r)));
      const by = {}; prv.filter((r) => r.구분 !== "공백 경미").forEach((r) => (by[r.업종] = by[r.업종] || []).push(r));
      Object.entries(by).sort((a, b) => b[1].length - a[1].length).forEach(([u, rs]) => {
        const li = el("li", "gv-qgroup"); const d = el("details"); const sm = el("summary");
        const nT = rs.filter((r) => brief && r.확정일 === brief.날짜).length;
        sm.append(el("b", null, u), el("span", null, `${rs.length}곳 · 도보권 대체 시설 있음`));
        const ul = el("ul", "gv-quiet-list"); rs.forEach((r) => ul.append(row(r))); d.append(sm, ul); li.append(d); nl.append(li);
      });
    }
  }
  function drawResident() {   // 주민 반응: 세 갈래 가운데 하나라도 있으면 보임
    const parts = ["gv-demand", "gv-use", "gv-reports"].filter((id) => !$("#" + id).hidden);
    $("#gv-resident").hidden = !parts.length;
    $("#gv-resident-n").textContent = "";
  }
  // 주민 제보 검토: 일반 가게 제보는 매주 월요일 AI가 여러 자료로 확인해 지도에 반영 (engine/report_check.py)
  function drawReports(R, wait) {
    const box = $("#gv-reports"); const items = (R && R.항목) || [];
    box.hidden = !R && !wait; if (box.hidden) return;
    const n = R ? R.요약 : null;
    $("#gv-reports-n").textContent = R ? `${dayShort(R.날짜)}` : "";
    $("#gv-reports-sub").textContent = [n && items.length ? `폐업 반영 ${n["폐업 맞음"]} · 운영 중 ${n["영업 중"]} · 판단 보류 ${n["판단 보류"]}` : (R ? "검토 제보 없음" : "검토 기록 없음"),
      wait ? `확인 중 ${wait}건` : ""].filter(Boolean).join(" · ");
    const ul = $("#gv-reports-list"); ul.innerHTML = "";
    items.forEach((r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button"; b.addEventListener("click", () => showRef(r, "주민 제보 검토"));
      const top = el("div", "gv-q-top"); top.append(el("b", null, r.상호), el("span", "gv-tag " + ({ "폐업 맞음": "closed", "영업 중": "open" }[r.판단] || "hold"), { "폐업 맞음": "폐업 반영", "영업 중": "운영 중" }[r.판단] || "판단 보류"),
        el("span", null, [r.업종, r.동네, `제보 ${r.제보수}건`].filter(Boolean).join(" · ")));
      b.append(top); if (r.까닭) b.append(el("p", null, r.까닭));
      li.append(b); ul.append(li);
    });
  }
  const dayShort = (d) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || ""); if (!m) return ""; const y = new Date().getFullYear(); return `${+m[1] !== y ? m[1] + "년 " : ""}${+m[2]}월 ${+m[3]}일`; };
  // 보고 기준: 엔진이 실제로 쓰는 값 그대로 (engine/severity.py, 학습 기준은 새 자료가 들어올 때마다 다시 계산)
  function drawRules(R) {
    const d = $("#gv-rules"); d.hidden = !R; if (!R) return;
    const body = $("#gv-rules-body"); body.innerHTML = "";
    body.append(el("p", "gv-rules-lead", "폐업으로 이용 시설까지 거리가 아래 기준 초과 시 보고 · 공공·민간 구분 없이 시설 기능 기준 판단"));
    const t = el("table", "gv-rules-t");
    const hd = el("tr"); ["이용하는 곳", "보고 기준 거리"].forEach((h) => hd.append(el("th", null, h))); t.append(hd);
    [...R.거리].sort((a, b) => (a.기준_m || 0) - (b.기준_m || 0)).forEach((x) => {   // (10/26) 가까운 기준부터 (뒤에 붙던 생필품·이·미용·반찬도 제자리로)
      const tr = el("tr"); tr.title = x.까닭;
      tr.append(el("td", null, x.기능), el("td", "num", km(x.기준_m)));
      t.append(tr);
    });
    body.append(t);
    body.append(el("h4", "gv-rules-h", "판단 원칙"));
    const ul = el("ul", "gv-rules-notes");
    // 10/25: 원칙 글(AI가 읽는 서술형)은 화면에서 공공기관 개조식으로 (기본 원칙 8개 → 요약, 담당자가 더한 원칙은 그대로)
    const RULES_SHOW = ["판단 기준: 시설 종류가 아닌 주민이 이용하던 생활 기능 · 공공·민간 구분 없음",
      "보고 대상: 담당자 조치가 가능한 공백만 보고",
      "도심(동): 생명 위험·회복 불가 피해 우려 공백만 보고 · 그 외 공백은 '관찰'로 매일 재검토",
      "읍·면: 주민 30명·어르신 10명부터 산정 · 지자체 운영·지정·감독 시설은 공백 규모로 판단 · 민간 가게는 생활권 단절 시만 보고(직선 4km 내 대체 없음, 또는 면 중심 시설 폐업·1km 내 대체 없음·영향 주민 40% 이상 어르신) · 마을 유일 생활 시설 사전 관리",
      "긴급: 법령으로 보장되는 생명·건강·돌봄 기능의 사실상 단절 · 그 외 보고 공백은 주의",
      "불확실 시 보수적 판단 · 취급 여부가 불확실한 인근 가게도 대체 시설로 보고 공백 여부 확인",
      "보고 제외: 호텔·병원·대학·공항·골프장·산업단지·휴게소 내 매점, 농장 직판장 등 주민 생활 시설 아닌 곳 · 같은 자리 동일 기능 신규 개업",
      "도보 30분 내 대체 시설이 있으면 '대체 시설 없음'으로 보고하지 않음"];
    const rl = R.원칙 || [];
    (/^시설의 종류가 아니라/.test(rl[0] || "") ? RULES_SHOW.concat(rl.slice(8)) : rl).forEach((x) => ul.append(el("li", null, x)));
    ul.append(el("li", null, `요양원·어린이집 등 등록 이용 시설: 거리 대신 정원 ${R.돌봄정원}명 이상 또는 ${km(R.돌봄거리_m)} 내 동종 기관 부재 여부 기준`));
    if (R.아이최소) ul.append(el("li", null, `어린이집·유치원·지역아동센터: 도보권 이용 시설을 잃는 아동 수 함께 판단 (도심 ${R.아이최소}명, 읍·면 ${R.아이최소_읍면}명 이상)`));
    ul.append(el("li", null, "기준 거리: 주민 실제 이동 거리로 평일마다 재산정(도심·읍·면 동일)"));
    const M = brief && brief.판단모델;
    if (M) ul.append(el("li", null, M.사례수 ? `판단 모델: 담당자 판단 사례 ${M.사례수}건 학습 · 판단 정정 시 익일 반영` : "판단 모델: 판단 정정 시 사례 학습 후 익일 반영"));
    body.append(ul);
  }
  // 폐업 여부 확인: 인허가가 엇갈리는데, 닫았다면 공백이 큰 공공·복지 시설만
  function drawAsk(asks, qs) {
    qs = qs || [];
    $("#gv-ask-n").textContent = String(asks.length); $("#gv-ask-empty").hidden = !!asks.length;
    const ul = $("#gv-ask-list"); ul.innerHTML = ""; asks.forEach((r) => ul.append(askRow(r)));
    const q = $("#gv-q-list"); q.innerHTML = ""; qs.forEach((r) => q.append(questionRow(r)));
    $("#gv-q-h").hidden = !qs.length; $("#gv-q-n").textContent = String(qs.length);
  }
  // 기능 공백 현황 (아이디어 제안자 답변서 6번): 결손 기능·영향·이전 운영 정보·주민 수요. 지자체 화면(참고)과 공개 화면이 같은 행을 씀
  const yyyymm = (d) => { const m = /^(\d{4})-(\d{2})/.exec(d || ""); return m ? `${m[1]}.${m[2]}` : ""; };
  function gapEffect(e) {
    if (!e) return "";
    if (e.이용자) return `이용자 ${won(e.이용자)}명 다른 기관으로 이전 필요` + (e.최근접_같은기관_m ? ` · 가장 가까운 같은 기관 ${km(e.최근접_같은기관_m)}` : "");
    const who = e.아이구분 ? `${e.아이구분} ${won(e.아이)}명` : `주민 ${won(e.주민)}명(65세 이상 ${won(e["65세이상"])}명)`;
    return `${km(e.기준_m)} 안에 이용 시설이 없어지는 ${who} · 가장 가까운 곳 ${km(e.거리_전_m, e.잰거리_m)} → ${km(e.거리_후_m, e.잰거리_m)}`;
  }
  function gapRow(r, withState) {
    const li = el("li"); const b = el("button", "gv-q gp-row"); b.type = "button";
    const top = el("div", "gv-q-top"); top.append(el("b", null, `${[r.구군, r.행정동, r.리].filter(Boolean).join(" ")} · ${r.기능}`));
    if (withState) top.append(el("span", "gv-tag " + (r.상태 === "보고" ? "closed" : "watch"), r.상태 === "보고" ? "보고 중" : "관찰 중"));
    b.append(top, el("p", "gp-eff", gapEffect(r.영향)));
    const period = (r.개업일자 ? `인허가 ${yyyymm(r.개업일자)} · ` : "") + `폐업 ${yyyymm(r.폐업일자)}`;   // 인허가일자는 공식 자료 그대로 (실제 개업일과 다를 수 있어 '영업 기간'으로 쓰지 않음)
    b.append(el("p", "gp-prev", `이전 시설 ${r.상호}(${r.업종}) · ${period}`));
    if (r.운영시간) b.append(el("p", "gp-meta", `폐업 전 운영시간 ${r.운영시간}`));
    if (r.결손기능 && r.결손기능.length > 1) b.append(el("p", "gp-meta", `결손 기능 ${r.결손기능.join(", ")}`));
    if (r.주민찾음) b.append(el("p", "gp-meta", `주민 상담 중 시설 미확인 ${r.주민찾음}회(최근 90일)`));
    b.addEventListener("click", () => { if (r.위도) map.setView([+r.위도, +r.경도], 15); });
    li.append(b); return li;
  }
  function drawRefill(rows) {
    const d = $("#gv-refill"); d.hidden = !rows.length; if (!rows.length) return;
    $("#gv-refill-n").textContent = `${rows.length}건`;
    const ul = $("#gv-refill-list"); ul.innerHTML = ""; rows.forEach((r) => ul.append(gapRow(r, true)));
  }
  // 공개 화면: 누구나 (판단·조치 없이 계산한 사실만, /api/gaps)
  let gapData = null, gapGu = "";
  // 기능 공백 현황 (10/21): 한 목록. 처음엔 공백이 있는 동을 옅게, 행을 누르면 시설이 없는 100m 칸을 칠함 (지점이 아니라 구역)
  const GP_LEAD = "생활 필수 시설 도보권 부재 구역 · 상시 부재 및 최근 폐업 영향 · 평일 오전 갱신";
  const GP_NOTE = "상시 부재: 식료품점·약국·동네 의원·공원 도보 2km 내 없음(취급 미확인 가게 포함 산정) · 폐업 영향: 폐업(공공 체육시설·공원은 폐쇄)으로 도보권 시설이 없어진 구역 · 주민: 주민등록 인구의 건물 규모별 배분 추정 · 창업 참고: 상권 유형은 용도지역(국토교통부 도시계획정보) 기준, 매출·임대료·폐업 원인 미반영";
  let gapDongs = null, gapOpen = null;
  const gapCanvas = L.canvas({ padding: 0.3 });
  const isPubZone = (r) => !!(r.공공시설 || r.시설 === "공원" || r.시설 === "공공 체육시설");
  const zoneFill = (r) => (isPubZone(r) ? "#1F5FAF" : "#C2410C");   // 지도 구역 색: 공공시설 파랑 / 생활 시설 주황
  function zoneRow(r) {
    const pubF = isPubZone(r);   // 공원·공공 체육시설: 사설 시설과 구분 (파란 표시, '폐업' 대신 '폐쇄')
    const li = el("li", "gz"); const b = el("button", "gv-q gp-row zone" + (r.원인 === "폐업 영향" ? " closed" : "") + (pubF ? " pub" : "")); b.type = "button";
    const top = el("div", "gv-q-top"); top.append(el("b", null, `${[r.구군, r.행정동, r.리].filter(Boolean).join(" ")} · ${r.시설}`));
    const tags = el("span", "gz-tags");
    if (pubF) tags.append(el("span", "gv-tag zt-pub", "공공시설"));
    if (r.원인 === "폐업 영향") tags.append(el("span", "gv-tag zt-closed", pubF ? "폐쇄 영향" : "폐업 영향"));
    else if ((r.관련폐업 || []).length) tags.append(el("span", "gv-tag zt-recent", "최근 폐업"));
    if (r.보고) tags.append(el("span", "gv-tag zt-report", "지자체 보고"));
    if (r.창업참고) tags.append(el("span", "gv-tag zt-biz", "창업 참고"));
    top.append(tags); b.append(top);
    const who = `주민 약 ${won(r.주민)}명` + (r["65세이상"] ? `(65세 이상 ${won(r["65세이상"])}명)` : "");
    if (r.원인 === "폐업 영향") {
      const c = (r.관련폐업 || [])[0] || {};
      b.append(el("p", "gp-eff", `${c.상호 || "시설"} ${pubF ? "폐쇄" : "폐업"} · 도보 ${km(r.기준_m)} 내 ${pubF ? r.시설 : "시설"} 부재 ${who}`));
      if (r.최근접_m != null) b.append(el("p", "gp-prev", `최근접 시설 도보 ${km(r.최근접_m, r.잰거리_m)}`));
    } else {
      b.append(el("p", "gp-eff", `도보 ${km(r.기준_m)} 내 ${r.시설} 없음 · ${who}`));
      if (r.최근접_m != null || r.최근접_직선_m != null)
        b.append(el("p", "gp-prev", "밀집 지점 기준 최근접 " + [r.최근접_m != null ? `도보 ${km(r.최근접_m, r.잰거리_m)}` : "", r.최근접_직선_m != null ? `직선 ${km(r.최근접_직선_m)}` : ""].filter(Boolean).join(" · ")));
    }
    const det = el("div", "gz-det"); det.hidden = true;
    (r.관련폐업 || []).forEach((c) => det.append(el("p", null, `관련 ${pubF ? "폐쇄" : "폐업"}: ${c.상호}(${c.업종}) · ${yyyymm(c.폐업일자)}` + (c.보고 ? " · 지자체 보고" : ""))));
    if (r.창업참고) det.append(el("p", "gz-biz", `창업 참고: ${String(r.창업참고.근거 || "").replace(/(생활\s*)?(필수·)?준필수\s*/g, "").replace(/^필수\s*/, "")}`));
    if (r.상권) det.append(tradeBlock(r));
    det.append(el("p", "gz-hint", "지도: 시설 부재 구역(100m 단위)"));
    b.addEventListener("click", () => focusZone(r, det));
    li.append(b, det); return li;
  }
  // 상권 분석 (10/21): 창업 컨설턴트가 보는 근거 — 계산한 사실(engine/trade_area.py) + 적합도 근거 + AI 요약(사실로만)
  const pct = (v) => `${Math.round((v || 0) * 100)}%`;
  function tradeBlock(r) {
    const f = r.상권, a = r.적합 || {}, z = el("div", "gz-trade");
    const h = el("p", "gz-th"); h.append(el("b", null, r.창업참고 ? "창업 적합도" : "창업 여건"), el("span", "gz-fit f-" + ({ 높음: "hi", 보통: "mid", 조건부: "cond", 낮음: "lo" }[a.적합도] || "mid"), a.적합도 || ""), el("span", null, f.상권유형));
    z.append(h);
    const S = r.창업참고 && r.창업참고.요약;
    if (S) {
      z.append(el("p", "gz-sum", S.요약));
      const ul = el("ul", "gz-pl"); (S.강점 || []).forEach((t) => ul.append(el("li", "pro", t))); (S.유의점 || []).forEach((t) => ul.append(el("li", "con", t))); z.append(ul);
    }
    const dl = el("dl", "gz-facts");
    const row = (k, v) => { if (!v) return; dl.append(el("dt", null, k), el("dd", null, v)); };
    row("용도지역(500m)", Object.entries(f.용도지역_비율 || {}).filter(([, v]) => v >= 0.05).map(([k, v]) => `${k} ${pct(v)}`).join(" · "));
    row("배후 수요", `반경 500m ${won(f.배후인구_500m)}명 · 1km ${won(f.배후인구_1km)}명` + (f.어르신비율_1km != null ? ` · 어르신 ${pct(f.어르신비율_1km)}` : ""));
    row("대중교통", [f.지하철역 ? `${f.지하철역} ${km(f.지하철역_m)}` : "지하철역 800m 내 없음", `버스 정류장 300m 내 ${f.버스정류장_300m}곳` + (f.버스운행_300m ? `(평일 ${won(f.버스운행_300m)}회)` : f.버스정류장_300m ? "(운행 횟수 자료 없음)" : "")].join(" · "));
    row("경쟁", `같은 업종 1km 내 ${f.같은업종_1km}곳` + (f.같은업종_최근접_m != null ? `(최근접 직선 ${km(f.같은업종_최근접_m)})` : "") + (f.대체업종_1km ? ` · 대신할 업종 ${f.대체업종_1km}곳` : ""));
    if (f.의원_500m != null) row("처방전 수요", `반경 500m 의원 ${f.의원_500m}곳`);
    row("상권 활력(1년)", `반경 1km 개업 ${f.상권_개업} · 폐업 ${f.상권_폐업}` + (f.업종_인허가자료 ? ` · 같은 업종 개업 ${f.업종_개업} · 폐업 ${f.업종_폐업}` : ""));
    z.append(dl);
    if ((a.근거 || []).length) z.append(el("p", "gz-why", "판단 근거: " + a.근거.join(" · ")));
    return z;
  }
  async function focusZone(r, det) {
    if (gapOpen && gapOpen !== det) gapOpen.hidden = true;
    det.hidden = false; gapOpen = det;
    drawGapBase(false, r);
    const x = await api("/api/gaps/cells?id=" + encodeURIComponent(r.id)); const cells = (x && x.칸) || [];
    const mx = Math.max(1, ...cells.map((c) => c[2]));
    const pts = [];
    cells.forEach(([lo, la, p]) => {
      pts.push([la, lo]);
      L.rectangle([[la - 0.00045, lo - 0.00055], [la + 0.00045, lo + 0.00055]], { renderer: gapCanvas, stroke: false, fillColor: zoneFill(r), fillOpacity: 0.4 + 0.45 * Math.min(1, p / mx) }).addTo(gapLayer);
    });
    if (r.폐업위치 && r.위도) { pts.push([+r.위도, +r.경도]); L.marker([+r.위도, +r.경도], { icon: L.divIcon({ className: "", html: '<div class="gp-pin"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }) }).bindTooltip(`${(r.관련폐업[0] || {}).상호 || ""} (폐업)`, { direction: "top" }).addTo(gapLayer); }
    if (pts.length > 1) map.fitBounds(L.latLngBounds(pts).pad(0.25), { maxZoom: 15 }); else if (pts.length) map.setView(pts[0], 14);
    if (!cells.length) det.querySelector(".gz-hint").textContent = "지도: 구역 계산 자료 없음";
  }
  const pubOnly = (f) => (f.properties.시설 || []).length > 0 && f.properties.시설.every((x) => x === "공원" || x === "공공 체육시설");   // (10/26) 공원·공공 체육시설만 빈 동은 파랑
  const dongCol = (f) => (pubOnly(f) ? "#1F5FAF" : "#C76A00");
  function drawGapBase(fit, focus) {   // 공백이 있는 동 경계 (옅게, 건수가 많을수록 진하게). 행을 고르면 다른 동은 더 옅게, 고른 동은 테두리만
    gapLayer.clearLayers();
    const feats = ((gapDongs && gapDongs.features) || []).filter((f) => !gapGu || f.properties.구군 === gapGu);
    if (!feats.length) return;
    const mine = (f) => focus && f.properties.구군 === focus.구군 && f.properties.행정동.replace(/[\s.·ㆍ,]/g, "") === String(focus.행정동 || "").replace(/[\s.·ㆍ,]/g, "");
    const g = L.geoJSON({ type: "FeatureCollection", features: feats }, { style: (f) => focus
      ? (mine(f) ? { color: pubOnly(f) ? "#173F78" : "#7C2D12", weight: 2.5, opacity: 0.9, fillOpacity: 0 } : { color: dongCol(f), weight: 0.8, opacity: 0.35, fillColor: dongCol(f), fillOpacity: 0.03 })
      : { color: dongCol(f), weight: 1, opacity: 0.6, fillColor: dongCol(f), fillOpacity: 0.06 + 0.05 * Math.min(3, f.properties.건수) } })
      .eachLayer((l) => l.bindTooltip(`${l.feature.properties.행정동} · ${l.feature.properties.시설.join("·")} 부재`, { sticky: true })).addTo(gapLayer);
    if (fit) map.fitBounds(g.getBounds().pad(0.05), { maxZoom: 13 });
  }
  async function loadGaps() {
    $("#gp-lead").textContent = GP_LEAD; $("#gp-note").textContent = GP_NOTE;
    try { gapData = await (await fetch("/api/gaps")).json(); } catch (e) { gapData = { 구역: [] }; }
    try { gapDongs = await (await fetch("/api/gaps/dongs")).json(); } catch (e) { gapDongs = null; }
    drawGaps(true);
  }
  function drawGaps(fit) {
    const rows = (gapData && gapData.구역) || [];
    $("#gp-date").textContent = gapData && gapData.날짜 ? `${dayLabel(gapData.날짜)} 기준` : "";
    const gus = $("#gp-gus"); gus.innerHTML = "";
    const GU_ORDER = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"];   // (10/29) 구·군 버튼은 행정 순서로 (목록 순서에 따라 뒤섞이던 것)
    const names = [...new Set(rows.map((r) => r.구군))].sort((a, b) => (GU_ORDER.indexOf(a) + 99) % 99 - (GU_ORDER.indexOf(b) + 99) % 99);
    const chip = (key, label, n) => {
      const b = el("button", "gv-gu" + (n ? "" : " calm")); b.type = "button"; b.setAttribute("aria-pressed", String(gapGu === key));
      b.append(el("span", null, label)); if (n) b.append(el("span", "n attn", String(n)));
      b.addEventListener("click", () => { gapGu = key; drawGaps(true); }); gus.append(b);
    };
    chip("", "대구 전체", rows.length); names.forEach((g) => chip(g, g, rows.filter((r) => r.구군 === g).length));
    const sel = rows.filter((r) => !gapGu || r.구군 === gapGu);
    const ul = $("#gp-list"); ul.innerHTML = ""; gapOpen = null; sel.forEach((r) => ul.append(zoneRow(r)));
    const em = $("#gp-empty"); em.hidden = !!sel.length; em.textContent = "현재 해당 구역 없음";
    const sv = ((gapData && gapData.해소) || []).filter((r) => !gapGu || r.구군 === gapGu), sd = $("#gp-solved");   // 최근 해소 구역 (매일 점검 때 시설 신규 개업 등으로 사라진 구역)
    sd.hidden = !sv.length; $("#gp-solved-n").textContent = sv.length ? `${sv.length}곳` : "";
    const sl = $("#gp-solved-list"); sl.innerHTML = "";
    sv.forEach((r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button";
      const top = el("div", "gv-q-top"); top.append(el("b", null, `${[r.구군, r.행정동, r.리].filter(Boolean).join(" ")} · ${r.시설}`), el("span", "gv-tag open", "해소"), el("span", null, `${dayShort(r.해소일)} 확인`));
      b.append(top, el("p", null, r.까닭 || ""));
      b.addEventListener("click", () => { const y = r.밀집_위도 || r.위도, x = r.밀집_경도 || r.경도; if (y) map.setView([+y, +x], 15); });
      li.append(b); sl.append(li);
    });
    drawGapBase(fit);
  }
  // 판단 확인: AI가 스스로 판단하기 애매해 담당자에게 하나만 묻는 곳 (답하면 그 곳에 바로 반영하고 배움)
  function questionRow(r) {
    const li = el("li", "gv-askrow big");
    const top = el("div", "gv-i-top"); top.append(el("span", "lv ask", "판단 확인"), el("h3", "gv-i-name", r.상호)); li.append(top);
    li.append(el("p", "gv-i-meta", [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), r.폐업일자 ? `${ymd(r.폐업일자)} 폐업` : ""].filter(Boolean).join(" · ")));
    li.append(el("p", "gv-ask-why", r.까닭.replace(/\s*\(65세 이상 [\d,]+명\)$/, "") + "."));
    li.append(el("p", "gv-ask-q", r.질문));
    const acts = el("div", "gv-acts");
    const yes = el("button", "btn-chip", "할 수 있습니다"), no = el("button", "btn-chip", "할 수 없습니다");
    const answer = async (label, say) => {
      yes.disabled = no.disabled = true;
      const x = await api("/api/gov/feedback", { fid: r.fid, 판단: label, 메모: r.질문 + " → " + say });
      acts.innerHTML = ""; acts.append(el("span", "gv-donewhen", x.ok ? x.글 : "반영하지 못했습니다."));
      if (x.ok) { li.classList.add("done"); setTimeout(loadGov, 5000); } else { yes.disabled = no.disabled = false; }
    };
    yes.addEventListener("click", () => answer("해당 없음", "할 수 있음")); no.addEventListener("click", () => answer("보고", "할 수 없음"));
    acts.append(yes, no, refBtn(r, "판단 확인 요청"), askAI(r, "판단 확인")); li.append(acts);
    return li;
  }
  // 읍·면에서 하나 남은 곳 (관심 지역 미리 살피기)
  function drawLastOne(list) {
    const box = $("#gv-lastone"); box.hidden = !list.length; if (!list.length) return;
    $("#gv-lastone-n").textContent = `${list.length}곳`;
    const ul = $("#gv-lastone-list"); ul.innerHTML = "";
    list.forEach((r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button";
      const top = el("div", "gv-q-top"); top.append(el("b", null, r.상호), el("span", null, [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), r.기능].join(" · ")));
      b.append(top, el("p", null, `폐업 시 기준 거리 안에 이용할 곳이 없어지는 주민 ${won(r.주민)}명(65세 이상 ${won(r["65세이상"])}명)` + (r.가장가까운_직선_m ? ` · 가장 가까운 다른 시설 직선 ${km(r.가장가까운_직선_m)}` : "")));
      b.addEventListener("click", () => { showRef(r, "단절 우려 시설(영업 중)"); gcNote(r, "단절 우려"); });
      li.append(b); ul.append(li);
    });
  }
  // 공공 체육시설·공원 공백 (10/26): 폐쇄 확정 → 공백 심각도 → 보고 여부까지 같은 절차, 예산 검토용으로 2년간 따로 보여 줌
  const SP_TAG = { 긴급: "urgent", 주의: "attn", 관찰: "watch" };
  function drawSport(list) {
    $("#gv-sport-n").textContent = list.length ? `${list.length}곳` : "";
    $("#gv-sport-empty").hidden = !!list.length;
    const ul = $("#gv-sport-list"); ul.innerHTML = "";
    list.forEach((r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button";
      const top = el("div", "gv-q-top");
      top.append(el("span", "lv " + (SP_TAG[r.판정] || "none"), r.판정 || "공백 없음"), el("b", null, r.상호),
        el("span", null, [r.구분, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), r.폐업일자 ? `${dayShort(r.폐업일자)} 폐쇄` : ""].filter(Boolean).join(" · ")));
      b.append(top, el("p", null, Array.isArray(r.까닭) ? r.까닭.join(" · ") : (r.까닭 || "")));
      if ((r.대응_단계 || []).length) r.대응_단계.forEach((x) => b.append(el("p", "gv-sport-act", `${x.단계}: ${x.할일}`)));   // (10/29) 즉시·단기·중장기 대응
      else {
        const acts = (r.대응 || []).map((x) => (typeof x === "string" ? x : x.할일)).filter(Boolean).slice(0, 2);
        if (acts.length) b.append(el("p", "gv-sport-act", "검토 사항: " + acts.join(" · ")));
      }
      b.addEventListener("click", () => { showRef(r, "공공 체육시설·공원 · " + (r.판정 || "공백 없음")); gcNote(r, "공공 체육시설·공원"); });
      li.append(b); ul.append(li);
    });
  }
  // 해소된 공백: 보고했던 곳 가운데 그 뒤 공백이 풀린 곳 (최근 30일)
  function drawSolved(list) {
    const box = $("#gv-solved"); box.hidden = !list.length; if (!list.length) return;
    $("#gv-solved-n").textContent = `${list.length}곳`;
    const ul = $("#gv-solved-list"); ul.innerHTML = "";
    list.forEach((r) => {
      const li = el("li"); const b = el("button", "gv-q"); b.type = "button"; b.addEventListener("click", () => showRef(r, "공백 해소"));
      const top = el("div", "gv-q-top"); top.append(el("b", null, r.상호), el("span", "gv-tag open", "해소"), el("span", null, [r.업종, r.구군, `${dayShort(r.해소일)} 확인`].filter(Boolean).join(" · ")));
      b.append(top, el("p", null, r.까닭)); li.append(b); ul.append(li);
    });
  }
  // 주민이 찾지 못한 곳: 동네·기능별로 모아 보여 줌 (engine/demand.py)
  // 주민 이용 결과 (아이디어 제안자 답변서 6번 '결과 피드백'): 구·군마다 다녀옴 / 맞는 곳 없음, 기능별
  function drawUse(U) {
    const gs = Object.keys(U).filter((g) => !govGu || g === govGu);
    const box = $("#gv-use"); box.hidden = !gs.length; if (!gs.length) return;
    const t = gs.reduce((a, g) => ({ o: a.o + U[g]["다녀옴"], x: a.x + U[g]["맞는 곳 없음"] }), { o: 0, x: 0 });
    $("#gv-use-n").textContent = `${t.o + t.x}건`;
    const ul = $("#gv-use-list"); ul.innerHTML = "";
    gs.forEach((g) => Object.entries(U[g].기능).forEach(([f, v]) => {
      const li = el("li"); const b = el("div", "gv-q");
      const top = el("div", "gv-q-top"); top.append(el("b", null, `${g} · ${f}`), el("span", null, `이용 ${v["다녀옴"]}건 · 맞는 곳 없음 ${v["맞는 곳 없음"]}건`));
      b.append(top); li.append(b); ul.append(li);
    }));
  }
  function drawDemand(list) {
    const box = $("#gv-demand"); box.hidden = !list.length; if (!list.length) return;
    $("#gv-demand-n").textContent = `${list.reduce((n, r) => n + r.건수, 0)}건`;
    const ul = $("#gv-demand-list"); ul.innerHTML = "";
    list.forEach((r) => {
      const li = el("li"); const b = el("div", "gv-q");
      const top = el("div", "gv-q-top"); top.append(el("b", null, `${r.행정동} · ${r.기능이름}`), el("span", null, [r.구군, `상담 ${r.건수}건`, `최근 ${dayShort(r.마지막)}`].join(" · ")));
      b.append(top); if (r.종류 && r.종류.length) b.append(el("p", null, `찾은 시설: ${r.종류.join(", ")}`));
      li.append(b); ul.append(li);
    });
  }
  // 담당자가 AI 판단을 바로잡을 때 (선택): 누르지 않아도 AI는 스스로 판단함
  function fixBtn(fid, text, label) {
    const b = el("button", "btn-text gv-fix", text);
    b.addEventListener("click", async (e) => {
      e.stopPropagation(); b.disabled = true;
      const x = await api("/api/gov/feedback", { fid, 판단: label });
      b.replaceWith(el("span", "gv-donewhen", x.ok ? x.글 + " 다음 판단에도 씁니다." : "반영하지 못했습니다."));
      if (x.ok) setTimeout(loadGov, 5000);
    });
    return b;
  }
  function askRow(r) {
    const li = el("li", "gv-askrow big");
    const top = el("div", "gv-i-top"); top.append(el("span", "lv ask", "폐업 확인"), el("h3", "gv-i-name", r.상호)); li.append(top);
    const src = r.제보 ? `${ymd(r.폐업일자)} 주민 제보` : /^유치원알리미/.test(r.까닭 || "") ? "유치원 정보공시 중단" : /^어린이집정보공개포털/.test(r.까닭 || "") ? "어린이집 정보공개 목록에 없음" : r.폐업일자 ? `${ymd(r.폐업일자)} 인허가 폐업` : "";
    li.append(el("p", "gv-i-meta", [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), src].filter(Boolean).join(" · ")));
    if (!r.제보 && r.까닭 && /^(유치원알리미|어린이집정보공개포털)/.test(r.까닭)) li.append(el("p", "gv-ask-why", r.까닭.replace(/^[^:]+:\s*/, "").replace(/ — /, " · ").replace(/\.?\s*·?\s*(휴업·폐업|폐지) 여부 확인 필요$/, "")));
    if (r.제보) li.append(el("p", "gv-ask-why", `주민 제보 ${r.제보수 || 1}건 접수 · 확인 전까지 주민 안내 중단`));
    if (r.AI분석) {
      const A = r.AI분석, box = el("div", "gv-ai");
      box.append(el("b", null, { "폐업 맞음": "AI 분석: 폐업 가능성 높음", "영업 중": "AI 분석: 영업 중 가능성 높음" }[A.판단] || "AI 분석: 자료만으로 판단 어려움"));
      if (A.까닭) box.append(el("p", null, A.까닭));
      if (A.확인할점) box.append(el("p", "gv-ai-check", "확인할 점: " + A.확인할점));
      li.append(box);
    }
    const left = (r.남은인허가 || []).map((x) => `'${x.replace(/\s*\(.*$/, "")}'`).filter((x, i, a) => a.indexOf(x) === i);
    if (left.length && !/인허가/.test((r.AI분석 && r.AI분석.까닭) || "")) li.append(el("p", "gv-ask-why", `${left.join(", ")} 인허가 영업 중 유지`));
    if (r.닫았다면) {   // 실제로 문을 닫았을 때의 공백 (이 때문에 확인 요청이 올라옴)
      const p = el("div", "gv-ask-if"); const h = el("p", "gv-ask-if-h"); h.append(el("span", null, "폐업 시 예상 공백"), el("span", "lv " + (LV[r.닫았다면] || ""), r.닫았다면));
      p.append(h); if (r.닫았다면_까닭 && r.닫았다면_까닭[0]) p.append(el("p", "gv-ask-if-t", r.닫았다면_까닭[0])); li.append(p);
    }
    const acts = el("div", "gv-acts");
    if (r.전화) { const a = el("a", "btn-chip", `전화 ${r.전화}`); a.href = `tel:${r.전화.replace(/[^0-9]/g, "")}`; acts.append(a); }
    // 폐업 / 휴원·휴업(운영 중단, 공식 자료에 다시 운영으로 나오면 자동 복귀) / 운영 중
    const yes = el("button", "btn-chip", "폐업 확인"), pause = el("button", "btn-chip", "휴원·휴업 확인"), no = el("button", "btn-chip", "운영 중");
    const answer = async (closed, st) => {
      yes.disabled = pause.disabled = no.disabled = true;
      const x = await api("/api/gov/confirm", { fid: r.fid, 닫음: closed, 상태: st });
      acts.innerHTML = ""; acts.append(el("span", "gv-donewhen", x.ok ? ({ 폐업: "폐업 반영 중", 휴업: "휴원·휴업 반영 중 · 운영 재개 시 자동 복귀", 운영: "운영 중 반영 중" }[st]) : (x.글 || "반영 실패")));
      if (x.ok) { li.classList.add("done"); setTimeout(loadGov, 60000); } else { yes.disabled = pause.disabled = no.disabled = false; }
    };
    yes.addEventListener("click", () => answer(true, "폐업")); pause.addEventListener("click", () => answer(true, "휴업")); no.addEventListener("click", () => answer(false, "운영"));
    acts.append(yes, pause, no, refBtn(r, "폐업 확인 필요"), askAI(r, "폐업 확인 필요")); li.append(acts);
    return li;
  }
  // 담당자 의견: 필요 없는 보고였다고 알려 주면 원칙으로 저장하고 다시 판단
  function teach(fid, label) {
    const box = el("div", "teach");
    const b = el("button", "btn-text teach-b", label);
    b.addEventListener("click", () => {
      b.hidden = true;
      const ta = el("textarea", "teach-t"); ta.rows = 2; ta.placeholder = "예: 이 병원은 지난달 응급실을 먼저 닫았습니다";
      const send = el("button", "btn-chip solid", "보내기");
      send.addEventListener("click", async () => {
        send.disabled = true; const x = await api("/api/gov/lesson", { fid, 내용: ta.value });
        box.innerHTML = ""; box.append(el("span", "gv-donewhen", x.글 || "보내지 못했습니다."));
        if (x.ok) setTimeout(loadGov, 25000);
      });
      box.append(ta, send); ta.focus();
    });
    box.append(b); return box;
  }
  function drawLessons() {
    const d = $("#gv-lessons"); d.hidden = !lessons.length; if (!lessons.length) return;
    d.querySelector("summary").textContent = `반영하고 있는 담당자 의견 ${lessons.length}건`;
    const ul = d.querySelector("ul"); ul.innerHTML = ""; lessons.forEach((x) => ul.append(el("li", null, x.원칙)));
  }
  const lvPin = (lv) => stIcon(ST(lv), true);
  function drawGovPins(items) {
    govLayer.clearLayers();
    items.filter((r) => !r.처리 && r.위도).forEach((r) => {
      L.marker([+r.위도, +r.경도], { icon: lvPin(r.등급), zIndexOffset: r.등급 === "긴급" ? 900 : 500 })
        .bindTooltip(stTip(r.상호, ST(r.등급)), { direction: "top", className: "stip", offset: [0, -14] }).on("click", () => focusItem(r, true)).addTo(govLayer);
    });
  }
  // 사전 검토 응답 확인: 접속 만료 · 서버 응답 없음(서버를 새로 켜지 않은 경우 포함) · 계산 오류를 '결과 없음'과 구분해 알림
  function preFail(d, st) {
    if (d && d.잠김) { st.textContent = "담당자 접속이 만료되었습니다. 접속 코드를 다시 입력해 주십시오."; govLock(); return true; }
    if (d && d.오류) { st.textContent = d.오류; return true; }
    if (!d || d.type === "error" || !(Array.isArray(d.목록) || d.fid)) { st.textContent = "서버가 응답하지 않습니다. 서버를 다시 켠 뒤 시도해 주세요."; return true; }
    return false;
  }
  let preBusy = false;
  async function runPre(r) {
    if (preBusy) return;
    const st = $("#pre-status"), out = $("#pre-result"), btn = $("#pre-form button");
    $("#pre-list").innerHTML = ""; out.innerHTML = ""; preLayer.clearLayers();
    st.hidden = false; st.textContent = `${r.상호}: 공백 산정·AI 판단 중 (약 20초)`;
    preBusy = true; btn.disabled = true;
    let x; try { x = await api("/api/gov/prereview", { fid: r.fid }); } finally { preBusy = false; btn.disabled = false; }
    if (preFail(x, st)) return;
    st.textContent = "사전 검토 결과 · 폐업 가정 · 오늘의 보고와 별도";
    const card = x.공백 ? itemCard(x, true) : preNoGap(x);
    if (x.공립대체) { const at = card.querySelector(".gv-i-sum") || card.querySelector(".gv-i-top"); at.after(pubBox(x.공립대체)); }
    card.append(askAI(x, "사전 검토")); out.append(card); focusPre(x);
  }
  // 공립 유치원 대체 (10/21): 반경 3km 다른 공립 유치원의 남는 자리로 원아 수용 가능 여부 — 공립 선택권
  function pubBox(p) {
    const s = el("section", "gv-sec pubalt " + (p.가능 ? "ok" : "short"));
    const h = el("h4"); h.append(document.createTextNode("공립 유치원 대체"), el("span", "pub-v", p.가능 ? "수용 가능" : "선택권 축소")); s.append(h);
    s.append(el("p", "pub-sum", `반경 ${km(p.반경_m)} 공립 ${p.곳}곳 · 남는 자리 ${won(p.여유)}명` + (p.원아 != null ? ` · 원아 ${won(p.원아)}명` : "")));
    if ((p.목록 || []).length) { const ul = el("ul", "pub-list"); p.목록.forEach((x) => { const li = el("li"); li.append(el("span", null, x.상호), el("span", "pub-d", `${km(x.거리_m)} · 여유 ${won(x.여유)}명`)); ul.append(li); }); s.append(ul); }
    return s;
  }
  function preNoGap(r) {   // 공백이 생기지 않는 경우
    const li = el("li", "gv-item pre");
    const top = el("div", "gv-i-top"); top.append(el("span", "lv pre", "사전 검토"), el("span", "lv none", "해당 없음"), el("h3", "gv-i-name", r.상호), el("p", "gv-lvdesc", `해당 없음: ${LV_DESC["해당 없음"]}`)); li.append(top);
    li.append(el("p", "gv-i-meta", [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), "폐업 가정"].join(" · ")));
    li.append(el("p", "gv-i-sum", r.판단까닭));
    const did = didBox(r.하던일, (r.하던일 || []).map((d) => d.규모).find(Boolean), "이곳이 하는 일"); if (did) li.append(did);
    if (r.대체시설 && r.대체시설.length) {
      const s = el("section", "gv-sec alts"); s.append(el("h4", null, "하는 일별 가장 가까운 대체 시설")); const ul = el("ul", "gv-alts");
      r.대체시설.forEach((a, i) => { const x = el("li"); x.append(el("span", "alt-n", String(i + 1)), el("span", "alt-name", a.기능 ? `${a.상호} (${a.기능})` : a.상호), el("span", "alt-t", a.걷는시간_분 != null ? `걸어서 ${Math.round(a.걷는시간_분)}분` : "")); ul.append(x); });
      s.append(ul); li.append(s);
    }
    return li;
  }
  function focusPre(r) {   // 사전 검토 시설: 점선 테두리 핀 (실제 보고 핀과 구분)
    preLayer.clearLayers(); const pts = [];
    if (r.위도 != null) { pts.push([+r.위도, +r.경도]);
      L.marker([+r.위도, +r.경도], { icon: stIcon(ST("사전 검토"), true), zIndexOffset: 1000 })
        .bindTooltip(stTip(r.상호, ST("사전 검토")), { permanent: true, direction: "top", className: "stip", offset: [0, -16] }).addTo(preLayer); }
    (r.대체시설 || []).forEach((a, i) => { if (a.위도 == null) return; pts.push([+a.위도, +a.경도]);
      L.marker([+a.위도, +a.경도], { icon: L.divIcon({ className: "", html: `<div class="apin">${i + 1}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }) }).bindTooltip(a.상호, { direction: "top" }).addTo(preLayer); });
    if (pts.length > 1) map.fitBounds(L.latLngBounds(pts).pad(0.25), { maxZoom: 16 }); else if (pts.length) map.setView(pts[0], 15);
  }
  async function focusItem(r, fromMap) {
    areaLayer.clearLayers(); selLayer.clearLayers();
    const gj = await api(`/api/gov/area?fid=${encodeURIComponent(r.fid)}`);
    const maxN = Math.max(1, ...(gj.features || []).map((f) => f.properties.주민 || 0));
    const area = L.geoJSON(gj, { style: (f) => ({ color: "#C5221F", weight: 1.5, fillColor: "#C5221F", fillOpacity: 0.05 + 0.1 * ((f.properties.주민 || 0) / maxN) }) })
      .eachLayer((l) => l.bindTooltip(`${l.feature.properties.행정동} · 약 ${won(l.feature.properties.주민)}명`, { sticky: true })).addTo(areaLayer);
    const pts = [];
    if (r.위도) { pts.push([+r.위도, +r.경도]); L.marker([+r.위도, +r.경도], { icon: lvPin(r.등급), zIndexOffset: 1000 }).bindTooltip(stTip(r.상호, ST(r.등급)), { permanent: true, direction: "top", className: "stip", offset: [0, -16] }).addTo(areaLayer); }
    (r.대체시설 || []).forEach((a, i) => {
      if (a.위도 == null) return; pts.push([a.위도, a.경도]);
      L.marker([a.위도, a.경도], { icon: L.divIcon({ className: "", html: `<div class="apin">${i + 1}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }) })
        .bindTooltip(a.상호, { direction: "top" }).addTo(areaLayer);
    });
    let b = null;
    try { b = area.getBounds(); } catch (e) {}
    pts.forEach((p) => { b = b && b.isValid() ? b.extend(p) : L.latLngBounds([p, p]); });
    if (b && b.isValid()) map.fitBounds(b.pad(0.15), { maxZoom: 16 });
    if (fromMap) { const card = [...document.querySelectorAll(".gv-item")].find((x) => x.querySelector(".gv-i-name")?.textContent === r.상호); if (card) { card.scrollIntoView({ behavior: "smooth", block: "start" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1200); } }
  }
  // ---------- 업무 보조 대화 (10/21 헌준님): 기본 화면 옆의 비서. 기본 화면 ↔ 대화가 서로 이어짐 ----------
  //  대화 → 화면: 시설을 누르면 지도·보고 카드 강조, 구·군·칸 옮기기, 확인 카드로 반영하면 보고 화면을 다시 그림
  //  화면 → 대화: 보고 항목의 'AI에게 묻기', 화면에서 누른 버튼(확인·바로잡기·처리·사전 검토)은 다음 말과 함께 에이전트에게 전달
  const gcLayer = L.layerGroup();
  const gcCanvas = L.canvas({ padding: 0.3 });   // 10/25: 기능 공백 화면과 같은 캔버스를 쓰면 지운 칸이 남던 것 → 업무 보조 전용
  let gcSid = null, gcBusy = false, gcFocus = null, gcHello = false, gcRole = null;
  const govEvents = [];
  const GC_TRACK = /\/api\/gov\/(confirm|field|feedback|mark|lesson|prereview)$/;
  function gcTrack(path, body, d) { if (GC_TRACK.test(path) && body && d && (d.ok || d.fid)) govEvents.push({ path, body: { ...body } }); }
  function gcBuild() {
    if ($("#gc")) return;
    const wrap = $(".mapwrap");
    const open = el("button", "gc-open"); open.id = "gc-open"; open.type = "button"; open.hidden = true;
    open.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4h12v9H9l-4 3v-3H4z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg><span>업무 보조</span>';
    const box = el("section", "gc"); box.id = "gc"; box.hidden = true; box.setAttribute("aria-label", "업무 보조 대화");
    const head = el("header", "gc-head");
    const t = el("div", "gc-t"); t.append(el("b", null, "업무 보조"), el("span", null, "자료 조회 · 문서 · 확인 처리"));
    const nw = el("button", "btn-text gc-new", "새 대화"); nw.type = "button";
    const x = el("button", "gc-x", "×"); x.type = "button"; x.setAttribute("aria-label", "업무 보조 닫기");
    head.append(t, nw, x);
    const ctx = el("div", "gc-ctx"); ctx.id = "gc-ctx"; ctx.hidden = true;
    const log = el("div", "gc-log"); log.id = "gc-log"; log.setAttribute("aria-live", "polite");
    const opts = el("div", "gc-opts"); opts.id = "gc-opts";
    const f = el("form", "gc-say"); f.autocomplete = "off";
    const ta = el("textarea"); ta.id = "gc-msg"; ta.rows = 1; ta.placeholder = "예: 수성구 약국 공백"; ta.setAttribute("aria-label", "업무 보조에 요청 입력");
    const go = el("button", "btn-solid", "보내기"); go.type = "submit";
    f.append(ta, go); box.append(head, ctx, log, opts, f);
    wrap.append(open, box);
    open.addEventListener("click", () => gcOpen());
    x.addEventListener("click", () => { box.hidden = true; open.hidden = false; document.body.classList.remove("gc-on"); gcLayer.clearLayers(); });
    nw.addEventListener("click", () => { gcSid = null; gcFocus = null; gcCtx(); log.innerHTML = ""; gcHello = false; gcLayer.clearLayers(); gcGreet(); });
    f.addEventListener("submit", (e) => { e.preventDefault(); const v = ta.value.trim(); if (v) { ta.value = ""; ta.style.height = ""; gcSend(v); } });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); f.requestSubmit(); } });
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(120, ta.scrollHeight) + "px"; });
  }
  function gcShow(on) {
    gcBuild();
    const ok = on && !$("#gov").classList.contains("locked") && govLoaded;
    $("#gc-open").hidden = !ok || !$("#gc").hidden;
    if (!ok) { $("#gc").hidden = true; document.body.classList.remove("gc-on"); }
    ok ? gcLayer.addTo(map) : map.removeLayer(gcLayer);
  }
  function gcOpen(focus, chips) {
    gcBuild(); $("#gc").hidden = false; $("#gc-open").hidden = true; document.body.classList.add("gc-on");
    if (!gcHello) gcGreet(!!focus);
    if (focus) { gcFocus = focus; gcCtx(); if (chips) gcChips(chips); }
    setTimeout(() => $("#gc-msg").focus(), 60);
  }
  function gcCtx() {
    const c = $("#gc-ctx"); c.innerHTML = ""; c.hidden = !gcFocus; if (!gcFocus) return;
    const s_ = ST(gcFocus.구분); c.append(el("span", "gc-ctx-l", "선택"), el("b", null, gcFocus.상호 || ""), el("span", `stt ${s_.f} ${s_.c}`, s_.t));
    const rm = el("button", "btn-text", "해제"); rm.type = "button"; rm.addEventListener("click", () => { gcFocus = null; gcCtx(); }); c.append(rm);
  }
  // (10/26 헌준님) 기본 화면에서 구·군을 바꾸면 업무 보조도 새로고침 없이 그 범위로: 범위 바뀜 줄 + 그 범위의 첫 안내·추천 요청
  let gcHelloGu = null;
  async function gcScope() {
    if (!gcHello || !$("#gc-log")) return;
    if (gcHelloGu === govGu) return;
    const d = await api("/api/gov/chat/hello" + (govGu ? "?gu=" + encodeURIComponent(govGu) : ""));
    if (!d || d.잠김) return;
    gcHelloGu = govGu;
    const sep = el("div", "gc-scope"); sep.append(el("span", null, `조회 범위 변경 · ${govGu || "대구 전체"}`)); $("#gc-log").append(sep);
    const m = el("div", "gc-m bot hello"); (d.blocks || []).forEach((b, i) => m.append(el("p", i ? null : "gc-hello-h", b.text))); $("#gc-log").append(m);
    m.scrollIntoView({ block: "end" });
    if (!gcBusy) gcChips(d.options || []);
  }
  async function gcGreet(quiet) {
    gcHello = true;
    gcHelloGu = govGu;
    const d = await api("/api/gov/chat/hello" + (govGu ? "?gu=" + encodeURIComponent(govGu) : ""));
    if (d.잠김) return govLock();
    const m = el("div", "gc-m bot hello"); (d.blocks || []).forEach((b, i) => m.append(el("p", i ? null : "gc-hello-h", b.text))); $("#gc-log").append(m);
    if (!quiet) gcChips(d.options || []);
  }
  function gcChips(list) {
    const o = $("#gc-opts"); o.innerHTML = "";
    list.forEach((t) => { const b = el("button", null, t); b.type = "button"; b.addEventListener("click", () => gcSend(t)); o.append(b); });
  }
  function gcMe(t) { const m = el("div", "gc-m me"); m.append(el("p", null, t)); $("#gc-log").append(m); m.scrollIntoView({ block: "end" }); }
  function gcLive() {
    const m = el("div", "gc-m bot live"); const steps = el("ul", "steps"); steps.append(el("li", "step now", "요청 확인 중")); m.append(steps); $("#gc-log").append(m); m.scrollIntoView({ block: "end" });
    return {
      status(t) { steps.querySelectorAll(".now").forEach((x) => x.classList.replace("now", "ok")); steps.append(el("li", "step now", t)); m.scrollIntoView({ block: "end" }); },
      reset(t) { this.status(t || "답 다시 확인 중"); },
      finish() { const done = [...steps.children].map((x) => x.textContent).filter((x) => x !== "요청 확인 중"); m.remove(); return done; },
    };
  }
  async function gcSend(text) {
    if (gcBusy) return; gcBusy = true; $("#gc-opts").innerHTML = ""; gcLayer.clearLayers();   // 10/25: 새 요청마다 앞 답의 지도 표시(공백 구역 등)를 지움
    gcMe(text); const lb = gcLive();
    const screen = { gu: govGu, pane: govSub, focus: gcFocus };
    const events = govEvents.splice(0, govEvents.length);
    await stream("/api/gov/chat", { sid: gcSid, text, screen, events }, (ev, d) => {
      if (ev === "status") lb.status(d);
      else if (ev === "reset") lb.reset(d);
      else if (ev === "done") { const steps = lb.finish(); if (d.sid) gcSid = d.sid; gcRender(d, steps, text); gcBusy = false; }
    });
  }
  // 답 글의 숫자(인원·비율·거리)를 굵게: 근거 숫자가 한눈에 들어오게 (글자는 텍스트 노드로만 넣음)
  const NUM_RE = /(약\s?)?\d[\d,]*(\.\d+)?\s?(명|곳|%|km|m|분|건|개소|개|배|시간)(?! 이상)/g;
  function gcEmph(t) {
    const f = document.createDocumentFragment(); let i = 0; t = String(t || "");
    for (const mm of t.matchAll(NUM_RE)) { f.append(document.createTextNode(t.slice(i, mm.index))); f.append(el("b", "num", mm[0])); i = mm.index + mm[0].length; }
    f.append(document.createTextNode(t.slice(i))); return f;
  }
  function gcRender(d, steps, asked) {
    const log = $("#gc-log"); const m = el("div", "gc-m bot");
    // (10/22) 에이전트가 무엇을 조회했는지는 답에 남기지 않음 — 기다리는 동안만 진행 단계를 보임
    if (d.잠김) { govLock(); return; }
    const said = [], nodes = [], prose = [];
    let hasKey = false;
    (d.blocks || [d.text ? { text: d.text } : null]).filter(Boolean).forEach((b) => {
      if (b.kind === "key") { hasKey = true; const k = el("div", "gc-key"); k.append(gcEmph(b.text)); m.append(k); said.push(b.text); return; }   // 에이전트의 핵심 판단: 맨 위에 강조
      if (!b.kind) { prose.push(b.text); said.push(b.text); return; }
      const n = gcBlock(b); if (n) nodes.push([b.kind, n]);
    });
    // (10/29 헌준님: 글이 많아 한눈에 안 들어옴) 답 글은 결론 한 줄 + 나머지 문장을 한 줄씩 점 목록으로
    const sents = prose.join(" ").split(/(?<=[.!?])\s+/).map((x) => x.trim()).filter(Boolean);
    if (sents.length) {
      const body = el("div", "gc-ans");
      const lead = hasKey ? null : sents.shift();
      if (lead) { const p_ = el("p", "gc-lead"); p_.append(gcEmph(lead)); body.append(p_); }
      if (sents.length) { const ul = el("ul", "gc-pts"); sents.forEach((t) => { const li = el("li"); li.append(gcEmph(t)); ul.append(li); }); body.append(ul); }
      m.append(body);
    }
    // 문서·확인 카드를 만든 답은 그것을 먼저 보이고, 중간에 조회한 표·목록은 '근거 자료'로 접어 둠 (좁은 대화창에서 결과물이 묻히지 않게, 10/22)
    const MAIN = new Set(["doc", "action", "effect", "policy"]);   // 답의 결과물 (문서·확인 카드·개설 효과·입지 후보) — 나머지 조회 목록은 근거로 접음
    const main = nodes.filter(([k]) => MAIN.has(k)), rest = nodes.filter(([k]) => !MAIN.has(k));
    if (main.length && rest.length >= 2) {
      main.forEach(([, n]) => m.append(n));
      const det = el("details", "gc-more"); det.append(el("summary", null, `조회한 근거 자료 ${rest.length}건`)); rest.forEach(([, n]) => det.append(n)); m.append(det);
    } else main.concat(rest).forEach(([, n]) => m.append(n));   // 결과물 먼저
    // 10/25 (헌준님): 답 아래 '정확하지 않음' 버튼은 뺌 (서비스 답을 스스로 의심하는 인상) — 판단 정정은 보고 화면의 '이 보고에 의견 보내기'로
    log.append(m); m.scrollIntoView({ block: "start", behavior: "smooth" });
    gcChips(d.options || []);
  }
  // 블록: 표 · 시설 목록 · 카드(보고 화면과 같은 모양) · 기능 공백 구역 · 입지 후보 · 개설 효과 · 확인 카드 · 문서 · 화면 옮기기
  function gcBlock(b) {
    if (b.kind === "table") {
      const w = el("div", "gc-tbl"); if (b.title) w.append(el("p", "gc-bt", b.title));
      const t = el("table"); const h = el("tr"); b.head.forEach((x) => h.append(el("th", null, x))); t.append(h);
      b.rows.forEach((r) => { const tr = el("tr"); r.forEach((v) => tr.append(el("td", typeof v === "number" ? "n" : null, typeof v === "number" ? won(v) : String(v == null ? "" : v)))); t.append(tr); });
      w.append(t); return w;
    }
    if (b.kind === "list") {
      const w = el("div", "gc-list"); w.append(el("p", "gc-bt", b.title));
      const ul = el("ul");
      b.rows.forEach((r) => {
        const li = el("li"); const bt = el("button", "gc-row"); bt.type = "button";
        const s_ = ST(r.구분); const top = el("div", "gc-row-top"); top.append(el("b", null, r.상호), el("span", `stt ${s_.f} ${s_.c}`, s_.t));
        bt.append(top, el("span", "gc-row-m", [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), r.폐업일자 ? `${dayShort(r.폐업일자)} 폐업` : ""].filter(Boolean).join(" · ")));
        if (r.요지) bt.append(el("span", "gc-row-s", r.요지));
        bt.addEventListener("click", () => gcPick(r));
        li.append(bt); ul.append(li);
      });
      w.append(ul);
      if (b.map) gcMapList(b.rows);
      return w;
    }
    if (b.kind === "card") return gcCard(b);
    if (b.kind === "zones") {
      const w = el("div", "gc-list"); w.append(el("p", "gc-bt", b.title)); const ul = el("ul");
      b.rows.forEach((r) => {
        const li = el("li"); const bt = el("button", "gc-row"); bt.type = "button";
        const top = el("div", "gc-row-top"); top.append(el("b", null, `${[r.구군, r.행정동, r.리].filter(Boolean).join(" ")} · ${r.시설}`));
        if (isPubZone(r)) top.append(el("span", "gc-tag t-pub", "공공시설"));
        if (r.원인 === "폐업 영향") top.append(el("span", "gc-tag t-closed", isPubZone(r) ? "폐쇄 영향" : "폐업 영향"));
        if (r.보고) top.append(el("span", "gc-tag t-rep", "지자체 보고"));
        if (r.창업참고) top.append(el("span", "gc-tag t-biz", "창업 참고"));
        bt.append(top, el("span", "gc-row-s", `도보 ${km(r.기준_m)} 내 ${r.시설} 없음 · 주민 약 ${won(r.주민)}명(65세 이상 ${won(r["65세이상"])}명)` + (r.최근접_m != null ? ` · 최근접 도보 ${km(r.최근접_m, r.잰거리_m)}` : "")));
        bt.addEventListener("click", () => gcZone(r));
        li.append(bt); ul.append(li);
      });
      w.append(ul); gcMapZones(b.rows); return w;
    }
    if (b.kind === "policy") {
      const D = b.data, w = el("div", "gc-pol");
      const site = !!D.장소비교;   // 장소별 효과 비교 (순회·이동 서비스 장소)
      w.append(el("p", "gc-bt", b.title || `${b.fn} 입지 후보 · ${D.구군 || "대구 전체"} (가정)`));
      if (!site) w.append(el("p", "gc-note", `현재 도보 ${km(D.기준_m)} 밖 주민 ${won(D.기준밖_주민)}명(65세 이상 ${won(D.기준밖_65세이상)}명) · 현재 시설 ${won(D.지금시설수)}곳 기준`));
      const t = el("table"); const h = el("tr"); ["순위", site ? "장소" : "행정동", `도보권 신규 편입 주민(${km(D.기준_m)})`, D.대상 !== "전체" ? D.대상 : "65세 이상", "기능 공백 구역 해소 주민"].forEach((x) => h.append(el("th", null, x))); t.append(h);
      gcLayer.clearLayers(); const pts = [];
      D.후보.forEach((c, i) => {
        const tr = el("tr", "clk"); tr.tabIndex = 0;
        tr.append(el("td", "n", String(i + 1)), el("td", null, site ? c.행정동 : `${c.구군} ${c.행정동}`), el("td", "n", `${won(c.새로_기준안_주민)}명`), el("td", "n", `${won(D.대상 !== "전체" ? c.대상_인원 : c.그중_65세이상)}명`), el("td", "n", c.공백구역기준_해소_주민 != null ? `${won(c.공백구역기준_해소_주민)}명` : "-"));
        const go = () => map.setView([c.위도, c.경도], 15);
        tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
        t.append(tr); pts.push([c.위도, c.경도]);
        L.marker([c.위도, c.경도], { icon: L.divIcon({ className: "", html: `<div class="gcpin">${i + 1}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }), zIndexOffset: 950 })
          .bindTooltip(`후보 ${i + 1} · ${c.행정동} · 도보권 신규 편입 주민 ${won(c.새로_기준안_주민)}명`, { direction: "top" }).addTo(gcLayer);
      });
      w.append(t);
      w.append(el("p", "gc-note", site ? `순위: ${D.대상 !== "전체" ? D.대상 + " 인원" : "새로 닿는 주민"} 순 · 기능 공백 구역: 도보 ${km((D.후보[0] || {}).공백구역기준_m)} 내 시설 없음` : `순위: ${D.대상 !== "전체" ? D.대상 + " 인원" : "새로 닿는 주민"} 순 · 기능 공백 구역: 도보 ${km((D.후보[0] || {}).공백구역기준_m)} 내 시설 없음 · 후보 지점: 행정동별 도보권 밖 주민 최다 지점 · 실제 입지는 건물·임대 여건 별도 확인`));
      gcFit(pts, 14);
      return w;
    }
    if (b.kind === "effect") {
      const D = b.data, w = el("div", "gc-pol");
      w.append(el("p", "gc-bt", `${b.fn} · 해당 지점 설치 시 (가정)`));
      w.append(el("p", null, `${D.구군} ${D.행정동} · ${D.지점}`));
      const nums = el("div", "gc-nums");
      const n = (v, lab) => { const x = el("div"); x.append(el("b", null, v), el("span", null, lab)); nums.append(x); };
      n(`${won(D.새로_기준안_주민)}명`, `도보권 신규 편입 주민(${km(D.기준_m)})`); n(`${won(D.대상 !== "전체" && D.대상_인원 != null ? D.대상_인원 : D.그중_65세이상)}명`, D.대상 !== "전체" ? `그중 ${D.대상}` : "그중 65세 이상");
      w.append(nums);
      if (D.공백구역기준_해소_주민 != null) w.append(el("p", "gc-note", `기능 공백 구역(도보 ${km(D.공백구역기준_m)} 내 시설 없음) 해소 주민 ${won(D.공백구역기준_해소_주민)}명(65세 이상 ${won(D.공백구역기준_해소_65세이상)}명)`));
      if ((D.동네별 || []).length > 1) w.append(el("p", "gc-note", "행정동별: " + D.동네별.map(([k, v]) => `${k} ${won(v)}명`).join(" · ")));
      if (D.주의) w.append(el("p", "gc-note warn", D.주의));
      gcLayer.clearLayers();
      L.marker([D.위도, D.경도], { icon: L.divIcon({ className: "", html: '<div class="gcpin">+</div>', iconSize: [26, 26], iconAnchor: [13, 13] }), zIndexOffset: 950 }).bindTooltip(`${b.fn} · ${D.지점 || "가정 지점"}`, { permanent: true, direction: "top", className: "gtip", offset: [0, -12] }).addTo(gcLayer);
      gcFit([[D.위도, D.경도]], 15);
      return w;
    }
    if (b.kind === "action") {
      const w = el("div", "gc-act");
      const h = el("p", "gc-act-h"); h.append(el("b", null, b.title), el("span", null, b.target)); w.append(h, el("p", "gc-act-d", b.desc));
      const row = el("div", "gc-act-b");
      const ok = el("button", "btn-chip solid", b.button || "반영"), no = el("button", "btn-chip", "취소"); ok.type = no.type = "button";
      if (b.view_only) w.append(el("p", "gc-note", "심사용 접속 · 서버 미반영 (정식 운영 시 즉시 반영)"));   // (10/29) 눌러 볼 수는 있게 (서버가 반영 없이 알림만)
      ok.addEventListener("click", async () => {
        ok.disabled = no.disabled = true;
        const x = await api(b.endpoint, b.body);
        const good = x.ok || x.시작;
        row.replaceChildren(el("span", "gc-act-r" + (good ? " ok" : ""), good ? (x.시작 ? "점검 시작 · 진행 상황은 왼쪽 점검 내역에 표시" : (x.글 || `${b.title} 반영 중 · 보고 화면에 곧 반영`)) : (x.글 || "반영하지 못함")));
        if (x.시작) { w.classList.add("done"); watchRun(); }
        else if (good) { w.classList.add("done"); setTimeout(loadGov, /confirm|field/.test(b.endpoint) ? 45000 : /lesson/.test(b.endpoint) ? 25000 : 5000); }
      });
      no.addEventListener("click", () => { row.replaceChildren(el("span", "gc-act-r", "취소함")); w.classList.add("done"); });
      row.append(ok, no); w.append(row); return w;
    }
    if (b.kind === "doc") {
      const w = el("div", "gc-doc"); const h = el("p", "gc-doc-h"); h.append(el("span", "gc-doc-i", { pdf: "PDF", xlsx: "XLSX", text: "글" }[b.fmt] || "문서"), el("b", null, b.title)); w.append(h);
      if (b.sub) w.append(el("p", "gc-note", b.sub));
      if (b.fmt === "pdf") { const a = el("button", "btn-chip solid", "보고서 열기"); a.type = "button"; a.addEventListener("click", () => window.open(b.url + "&print=1", "_blank", "noopener")); w.append(a); }
      else if (b.fmt === "xlsx") { const a = el("a", "btn-chip solid", "엑셀 내려받기"); a.href = b.url; a.setAttribute("download", ""); w.append(a); }
      else if (b.fmt === "text") {
        const pre = el("pre", "gc-pre", b.text); const cp = el("button", "btn-chip solid", "복사"); cp.type = "button";
        cp.addEventListener("click", async () => { try { await navigator.clipboard.writeText(b.text); cp.textContent = "복사함"; } catch (e) { const r = document.createRange(); r.selectNodeContents(pre); const s = getSelection(); s.removeAllRanges(); s.addRange(r); cp.textContent = "선택함 · Ctrl+C"; } });
        w.append(pre, cp);
      }
      return w;
    }
    if (b.kind === "screen") { gcScreen(b); return null; }
    return null;
  }
  function gcCard(b) {
    const r = b.row, w = el("div", "gc-card");
    if (b.card_type === "item") { const ol = el("ol", "gv-items"); ol.append(itemCard(r)); w.append(ol); }
    else if (b.card_type === "ask") { const ul = el("ul", "gv-ask-list"); ul.append(askRow(r)); w.append(ul); }
    else if (b.card_type === "question") { const ul = el("ul", "gv-ask-list"); ul.append(questionRow(r)); w.append(ul); }
    else if (b.card_type === "pre") {
      const card = r.공백 ? itemCard(r, true) : preNoGap(r);
      if (r.공립대체) { const at = card.querySelector(".gv-i-sum") || card.querySelector(".gv-i-top"); at.after(pubBox(r.공립대체)); }
      const ol = el("ol", "gv-items"); ol.append(card); w.append(ol);
      preLayer.clearLayers(); focusPre(r); preLayer.eachLayer((l) => l.addTo(gcLayer));
    } else {
      const s_ = ST(b.label); const top = el("div", "gc-row-top"); top.append(el("b", null, r.상호), el("span", `stt ${s_.f} ${s_.c}`, s_.t)); w.append(top);
      w.append(el("p", "gc-row-m", [r.업종, [r.구군, r.행정동, r.리].filter(Boolean).join(" "), r.폐업일자 ? `${dayShort(r.폐업일자)} 폐업` : ""].filter(Boolean).join(" · ")));
      const s = b.card_type === "lastone" ? `폐업 시 기준 거리 안에 이용할 곳이 없어지는 주민 ${won(r.주민)}명(65세 이상 ${won(r["65세이상"])}명) · ${r.기능 || ""}` : b.card_type === "quiet" ? [r.까닭, r.확정일 ? `${dayShort(r.확정일)} 확정(${r.확정근거 || ""})` : "", r.공개까지 ? `${dayShort(r.공개까지)}까지 안내` : ""].filter(Boolean).join(" · ") : (r.주소 || "");
      if (s) w.append(el("p", "gc-row-s", s));
      const did = didBox(r.하던일, (r.하던일 || []).map((x) => x.규모).find(Boolean), b.card_type === "open" ? "이곳이 하는 일" : null); if (did) w.append(did);
      if (r.위도 != null) { const loc = el("button", "btn-text", "위치 보기"); loc.type = "button"; loc.addEventListener("click", () => gcPick(dict(r, { 구분: b.label }))); w.append(loc); }
    }
    return w;
  }
  const dict = (a, b) => Object.assign({}, a, b);
  function gcFit(pts, maxZoom) {   // 대화창이 지도 오른쪽을 가리므로 그만큼 비워서 맞춤
    if (!pts.length) return;
    const w = document.body.classList.contains("gc-on") && $("#gc") ? $("#gc").offsetWidth + 24 : 0;
    if (pts.length === 1) { const z = maxZoom || 16; const c = map.unproject(map.project(L.latLng(pts[0]), z).add([w / 2, 0]), z); map.setView(c, z); return; }   // 보이는 칸 가운데에 오게 (대화창 폭의 절반만큼 옮김)
    map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [40, 40], paddingBottomRight: [w + 40, 70], maxZoom: maxZoom || 16 });
  }
  // 대화의 기능 공백 구역 목록 → 지도 (10/22): 구역마다 표시, 누르면 그 구역의 주민 분포
  function gcMapZones(rows) {
    if (govSub !== "report") setGovSub("report");
    gcLayer.clearLayers(); const pts = [];
    rows.forEach((r) => {
      const la = r.밀집_위도 || r.위도, lo = r.밀집_경도 || r.경도; if (la == null || lo == null) return; pts.push([+la, +lo]);
      const ch = ({ "동네 의원": "의", 약국: "약", 식료품점: "식" })[r.시설] || String(r.시설 || "").slice(0, 1);
      const tip = el("div", "stip-in"); tip.append(el("b", null, `${[r.행정동, r.리].filter(Boolean).join(" ")} · ${r.시설}`), el("span", "stt zone", `도보 ${km(r.기준_m)} 안에 ${r.시설} 없음 · 주민 ${won(r.주민)}명`));
      L.marker([+la, +lo], { icon: L.divIcon({ className: "", html: `<div class="zpin">${ch}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }), zIndexOffset: 600 })
        .bindTooltip(tip, { direction: "top", className: "stip", offset: [0, -12] }).on("click", () => gcZone(r)).addTo(gcLayer);
    });
    gcFit(pts, 15);
  }
  // 대화의 시설 목록 → 지도 (10/22): 목록의 시설을 상태별 핀으로 한꺼번에 표시, 핀을 누르면 그 시설을 고름
  function gcMapList(rows) {
    if (govSub !== "report") setGovSub("report");
    gcLayer.clearLayers(); selLayer.clearLayers(); areaLayer.clearLayers(); const pts = [];
    rows.forEach((r) => {
      if (r.위도 == null || r.경도 == null) return; const s = ST(r.구분); pts.push([+r.위도, +r.경도]);
      L.marker([+r.위도, +r.경도], { icon: stIcon(s, false), zIndexOffset: s.f === "closed" ? 800 : s.f === "ask" ? 850 : 700 })
        .bindTooltip(stTip(r.상호, s), { direction: "top", className: "stip" }).on("click", () => gcPick(r)).addTo(gcLayer);
    });
    gcFit(pts, 16);
  }
  // 대화의 시설 → 기본 화면: 지도 표시 + 보고 화면의 같은 카드 강조 + 대화의 '선택'
  function gcPick(r) {
    if (govSub !== "report" && r.출처 !== "영업중") setGovSub("report");
    if (r.항목) focusItem(r, true); else if (r.위도 != null) showRef(r, r.구분 || "선택한 시설");
    gcFocus = { fid: r.fid, 상호: r.상호, 구분: r.구분 }; gcCtx();
    const chips = r.구분 === "영업 중" || r.구분 === "단절 우려" ? [`${r.상호} 폐업 사전 검토`, `${r.상호} 하는 일`] : r.구분 === "폐업 확인 필요" ? [`${r.상호} 확인 사유`, "폐업 확인 처리", "운영 중 확인 처리"] : [`${r.상호} 판단 근거`, `${r.상호} 대체 시설`];
    gcChips(chips);
    const card = [...document.querySelectorAll("#gv-report .gv-item, #gv-report .gv-askrow, #gv-report .gv-q")].find((x) => (x.querySelector(".gv-i-name, b") || {}).textContent === r.상호);
    if (card && !$("#gv-report").hidden) { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1400); }
  }
  async function gcZone(r) {
    gcLayer.clearLayers();
    const x = await api("/api/gaps/cells?id=" + encodeURIComponent(r.id)); const cells = (x && x.칸) || [];
    const mx = Math.max(1, ...cells.map((c) => c[2])); const pts = [];
    cells.forEach(([lo, la, p]) => { pts.push([la, lo]); L.rectangle([[la - 0.00045, lo - 0.00055], [la + 0.00045, lo + 0.00055]], { renderer: gcCanvas, stroke: false, fillColor: zoneFill(r), fillOpacity: 0.35 + 0.45 * Math.min(1, p / mx) }).addTo(gcLayer); });
    if (pts.length > 1) gcFit(pts, 15); else if (r.위도) gcFit([[+r.위도, +r.경도]], 14);
    gcChips([`${r.행정동} ${r.시설} 신설 효과`, `${r.시설} 입지 후보`, "공백 구역 엑셀"]);
  }
  function gcScreen(b) {
    if ("gu" in b && b.gu !== govGu) { govGu = b.gu; gcHelloGu = govGu; try { localStorage.setItem("govGu", govGu); } catch (e) {} areaLayer.clearLayers(); selLayer.clearLayers(); gcLayer.clearLayers(); drawBrief(true); }
    if (b.section === "사전검토") setGovSub("pre");
    else if (b.section) {
      setGovSub("report");
      const sel = { 확인요청: "#gv-ask", 공백심각도: "#gv-gap", 관찰: "#gv-watch-h", 검토완료: "#gv-quiet", 주민반응: "#gv-resident", 단절우려: "#gv-lastone", 체육공원: "#gv-sport", 보고기준: "#gv-rules" }[b.section];
      const t = sel && $(sel);
      if (t) { const det = t.tagName === "DETAILS" ? t : t.closest("details"); if (det) det.open = true; t.scrollIntoView({ behavior: "smooth", block: "start" }); t.classList.add("flash"); setTimeout(() => t.classList.remove("flash"), 1400); }
    }
    if (b.focus) gcPick(dict(b.focus, { 구분: "선택한 시설", 항목: b.focus.항목 }));
  }
  // 기본 화면 → 대화: 목록에서 누른 시설은 대화창이 열려 있으면 '선택'으로 (다음 말에서 '이곳'으로 알아들음)
  function gcChipsFor(r, kind) {
    return kind === "폐업 확인 필요" ? [`${r.상호} 확인 사유`, `${r.상호} 폐업 시 공백`] : kind === "사전 검토" ? [`${r.상호} 판단 근거`, `${r.상호} 요약`] : kind === "단절 우려" ? [`${r.상호} 폐업 사전 검토`, `${r.행정동 || ""} 대체 수단`] : [`${r.상호} 판단 근거`, `${r.상호} 대체 시설`, `${r.상호} 요약`];
  }
  function gcNote(r, kind) {
    if (!$("#gc") || $("#gc").hidden) return;
    gcFocus = { fid: r.fid, 상호: r.상호, 구분: kind }; gcCtx(); if (!gcBusy) gcChips(gcChipsFor(r, kind));
  }
  // 기본 화면 → 대화: 보고 카드마다 'AI에게 묻기'
  function askAI(r, kind) {
    const b = el("button", "btn-text gv-askai", "AI에게 묻기"); b.type = "button";
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      gcOpen({ fid: r.fid, 상호: r.상호, 구분: kind }, gcChipsFor(r, kind));
    });
    return b;
  }
})();
