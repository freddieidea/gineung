"""인허가 자료 좌표(EPSG:5174, 한국 중부원점 Bessel) → 경위도(WGS84)
pyproj를 깔지 않아도 되도록 직접 계산함 (pyproj가 쓰는 변환과 같은 단계: 횡메르카토르 역변환 → Bessel 3차원 좌표 → Molodensky-Badekas 7변수 → WGS84)
pyproj와 견준 차이는 1cm 안 (engine/test_permits.py에서 확인)"""
import numpy as np

_BESSEL = (6377397.155, 1 / 299.1528128)
_WGS84 = (6378137.0, 1 / 298.257223563)
_LAT0, _LON0, _K0, _X0, _Y0 = np.radians(38.0), np.radians(127.002890277778), 1.0, 200000.0, 500000.0
# Korean 1985 to WGS 84 (1): Molodensky-Badekas, coordinate frame 회전
_T = np.array([-145.907, 505.034, 685.756]); _R = np.radians(np.array([-1.162, 2.347, 1.592]) / 3600.0); _S = 6.342e-6
_P = np.array([-3159521.31, 4068151.32, 3748113.85])


def _mlen(phi, a, e2):   # 적도에서 위도 phi까지 자오선 길이
    e4, e6 = e2 * e2, e2 ** 3
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * phi) - (35 * e6 / 3072) * np.sin(6 * phi))


def _inv_tm(x, y):
    a, f = _BESSEL; e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    M = _mlen(_LAT0, a, e2) + (y - _Y0) / _K0
    mu = M / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - np.sqrt(1 - e2)) / (1 + np.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * np.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * np.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * np.sin(6 * mu) + (1097 * e1 ** 4 / 512) * np.sin(8 * mu))
    C1 = ep2 * np.cos(p1) ** 2; T1 = np.tan(p1) ** 2
    N1 = a / np.sqrt(1 - e2 * np.sin(p1) ** 2); R1 = a * (1 - e2) / (1 - e2 * np.sin(p1) ** 2) ** 1.5
    D = (x - _X0) / (N1 * _K0)
    lat = p1 - (N1 * np.tan(p1) / R1) * (D ** 2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * ep2) * D ** 4 / 24
                                       + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * ep2 - 3 * C1 ** 2) * D ** 6 / 720)
    lon = _LON0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6 + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * ep2 + 24 * T1 ** 2) * D ** 5 / 120) / np.cos(p1)
    return lat, lon


def _to_cart(lat, lon, ell):
    a, f = ell; e2 = f * (2 - f); N = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    return np.stack([N * np.cos(lat) * np.cos(lon), N * np.cos(lat) * np.sin(lon), N * (1 - e2) * np.sin(lat)])


def _from_cart(X, ell):
    a, f = ell; e2 = f * (2 - f); x, y, z = X; p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - e2))
    for _ in range(6):
        N = a / np.sqrt(1 - e2 * np.sin(lat) ** 2); lat = np.arctan2(z + e2 * N * np.sin(lat), p)
    return lat, np.arctan2(y, x)


def to_wgs84(x, y):
    """x, y: EPSG:5174 좌표(미터, 숫자 또는 배열) → (경도, 위도) 도 단위. 숫자가 아닌 값은 nan"""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    lat, lon = _inv_tm(x, y)
    X = _to_cart(lat, lon, _BESSEL).reshape(3, -1)
    rx, ry, rz = _R
    R = np.array([[1, rz, -ry], [-rz, 1, rx], [ry, -rx, 1]])   # coordinate frame
    Xw = _T[:, None] + _P[:, None] + (1 + _S) * (R @ (X - _P[:, None]))
    la, lo = _from_cart(Xw, _WGS84)
    lo, la = np.degrees(lo).reshape(x.shape), np.degrees(la).reshape(x.shape)
    return (float(lo), float(la)) if x.ndim == 0 else (lo, la)


class Transformer:
    """pyproj.Transformer와 같은 쓰임새 (transform(x, y) → 경도, 위도)"""
    @staticmethod
    def from_crs(*a, **k): return Transformer()
    def transform(self, x, y): return to_wgs84(x, y)


def _ring_has(ring, x, y):   # 점이 고리(다각형 경계) 안에 있는지: 반직선 교차 수
    r = np.asarray(ring, dtype=float); xs, ys = r[:, 0], r[:, 1]; xe, ye = np.roll(xs, -1), np.roll(ys, -1)
    cross = (ys > y) != (ye > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = xs + (y - ys) * (xe - xs) / (ye - ys)
    return bool(np.count_nonzero(cross & (x < xi)) % 2)


class Areas:
    """GeoJSON 다각형들에서 점이 든 곳 찾기 (shapely 없이). features: GeoJSON feature 목록"""
    def __init__(self, features):
        self.polys = []   # [(이름 자리 i, [(바깥 고리, [구멍들])...], 경계 상자)]
        for i, g in enumerate(features):
            geo = g["geometry"]; parts = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
            pts = np.concatenate([np.asarray(p[0], dtype=float) for p in parts])
            self.polys.append((i, parts, (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())))
    def find(self, x, y):
        for i, parts, (x0, y0, x1, y1) in self.polys:
            if not (x0 <= x <= x1 and y0 <= y <= y1): continue
            for p in parts:
                if _ring_has(p[0], x, y) and not any(_ring_has(h, x, y) for h in p[1:]): return i
        return None
