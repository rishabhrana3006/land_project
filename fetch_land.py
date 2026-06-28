"""
HSAC Land Coordinate Extractor
================================
Fetches polygon coordinates for every khasra (kila) owned by the Rana family
across multiple villages in District Karnal, Tehsil Gharaunda, from the HSAC
Haryana ArcGIS API, and writes:
  - girwar_singh_land.txt      (human-readable, grouped by village/khewat/murabba/khasra)
  - girwar_singh_land.geojson  (map-ready FeatureCollection)
  - land_data.js               (window.LAND_DATA consumed by index.html)

Run:
    pip install -r requirements.txt
    python fetch_land.py
"""

import json
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# CONFIG  -- update AUTH_TOKEN here when it expires (JWT, ~24h lifetime)
# ---------------------------------------------------------------------------
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTY4ODEsImVtYWlsIjoidXNlcl8xNzgyNTQ5Mjg0ODI3QGVvZGIuY29tIiwibW9iaWxlIjoiKzkxODY4MzA4ODgyNCIsInJvbGUiOiJ1c2VyIiwic2Vzc2lvbklkIjoic2Vzc2lvbl8xNzgyNjc0NTAwMjI4X2FzNGV3amRoaiIsInNpZCI6InNlc3Npb25fMTc4MjY3NDUwMDIyOF9hczRld2pkaGoiLCJpYXQiOjE3ODI2NzQ1MDAsImV4cCI6MTc4Mjc2MDkwMH0.pG1GTk-EVWrwea6WZjvA1opdD9HaLwT9A6C3Kb2g-44"
BASE_URL = "https://hsac.in/eodb_backend/mapserver/service/hsacMain/10/query"

OUT_TXT = "girwar_singh_land.txt"
OUT_GEOJSON = "girwar_singh_land.geojson"
OUT_LANDDATA = "land_data.js"

REQUEST_DELAY = 0.3   # seconds between requests (politeness)
MAX_RETRIES = 2
TIMEOUT = 30

AREA_KEY = "st_area(shape)"
SQM_PER_ACRE = 4046.8564224

DISTRICT_NAME = "Karnal"
TEHSIL_NAME = "Gharaunda"

# ---------------------------------------------------------------------------
# OWNERSHIP DATA
# ---------------------------------------------------------------------------
# One entry per village. Khasra numbers are the EXACT cadastral IDs taken from
# the Jamabandi (Nakal) records, cross-verified against the source HTML. We
# match EXACTLY (no prefix expansion) so we never pull in a neighbouring
# co-sharer's sub-plot (e.g. 21/1/2 is Girwar's, 21/1/1 is not).
#
# codes:
#   d, t  -> district / tehsil codes
#   v     -> fixed village code (used when the whole village is one v_code)
#   v_name_like -> when set, the village v_code is auto-resolved PER MURABBA via
#                  a name-LIKE query (used where one estate spans several
#                  chak-mustarka v_codes, e.g. Kehrawali 97/98/99).
#
# khewats[label]:
#   owners   -> [{name, ratio}]  (ratio None => treated as full/sole for display)
#   share    -> Rana family's fraction of the (full) GIS polygons in this khewat.
#               Co-owned plots come back as the FULL plot, so "owned land" shown
#               in the viewer = polygon area x share. Sole ownership => 1.0.
#   murabbas -> {murabba: [requested kilas]}
VILLAGES = [
    {
        "id": "raseen",
        "name": "Raseen",
        "hadbast": "10",
        "codes": {"d": "10", "t": "063", "v": "06056"},
        "khewats": {
            "Khewat 11 (Sole Ownership - 15.8 Acres)": {
                "owners": [{"name": "Girwar Singh Rana", "ratio": None}],
                "share": 1.0,
                "murabbas": {
                    "16": ["18/4", "19/4", "22/2", "23/2", "24/1/2", "25/2/2", "26"],
                    "17": ["10/1", "11/3", "20/1", "20/4", "21/1/2", "22/2/2"],
                    "19": ["4/2", "5/2", "6", "7", "8", "14", "15", "16/2", "17", "18", "23", "24", "64"],
                },
            },
            "Khewat 5 (Co-Ownership - 4.81 Acres Share)": {
                "owners": [{"name": "Girwar Singh Rana", "ratio": None}],
                "share": 385 / 1248,
                "murabbas": {
                    "16": ["18/2", "19/2"],
                    "19": ["1/2", "2/3/2", "3/2", "9", "10", "11/1/1", "11/2", "12", "13", "16/1", "19", "20/1/1", "22/2", "25"],
                    "20": ["5/2", "6"],
                    "26": ["2/2/2"],
                    "27": ["2/2/1", "3/2", "7/2", "8/1", "13/1"],
                },
            },
            "Khewat 6 (Co-Ownership - 3.05 Acres Share)": {
                "owners": [{"name": "Girwar Singh Rana", "ratio": None}],
                "share": 488 / 1493,
                "murabbas": {
                    "17": ["10/2", "11/2", "20/2", "21/2/2", "22/1/2"],
                    "18": ["1/2/2", "2/2", "9", "10", "11/1", "12", "18", "19", "22", "23"],
                    "27": ["2/1", "2/2/2", "3/1", "8/2", "9/1"],
                },
            },
        },
    },
    {
        "id": "amritpur",
        "name": "Amritpur Khurd / Kherawali",
        "hadbast": "97-98-99",
        # One v_code (07100) is known to hold murabba 97; the higher murabbas
        # (63/124/125/126/127) may sit under sibling Kehrawali chak v_codes, so
        # we auto-resolve the v_code per murabba by name.
        "codes": {"d": "10", "t": "063", "v": None, "v_name_like": "KEHRAWALI"},
        "khewats": {
            "Khewat 406 (Co-Ownership)": {
                "owners": [
                    {"name": "Mohar Singh, Randheer, Hansraj (sons of Girwar Singh)", "ratio": "12/17 (jointly)"},
                ],
                "share": 12 / 17,
                "murabbas": {
                    "97": ["24", "25"],
                    "124": ["4/2", "5"],
                },
            },
            "Khewat 436 (Co-Ownership)": {
                "owners": [
                    {"name": "Shakuntala Devi (widow of Girwar Singh)", "ratio": "640/1747"},
                    {"name": "Mohar Singh, Hansraj, Randheer Singh (sons)", "ratio": "240/1747"},
                ],
                "share": 880 / 1747,
                "murabbas": {
                    "63": ["1", "2", "3", "4"],
                    "125": ["15/2", "16"],
                    "126": ["2", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "24"],
                    "127": ["11"],
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------
session = requests.Session()
session.headers.update({
    "accept": "*/*",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,hi;q=0.7",
    "referer": "https://hsac.in/eodb/map",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
})
session.headers["cookie"] = f"auth_token={AUTH_TOKEN}"


class AuthError(Exception):
    pass


def _base_where(d, t, v, murabba):
    return (
        f"n_d_code='{d}' AND n_t_code='{t}' AND n_v_code='{v}' "
        f"AND n_murr_no='{murabba}'"
    )


def query(params):
    """Run a query against the API with retries and auth-failure detection."""
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session.get(BASE_URL, params=params, timeout=TIMEOUT)
            if resp.status_code == 401:
                raise AuthError("HTTP 401 Unauthorized")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "error" in data:
                err = data["error"]
                code = err.get("code")
                if code in (401, 403, 498, 499):
                    raise AuthError(f"API error {code}: {err.get('message')}")
                raise RuntimeError(f"API error: {err}")
            return data
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * (attempt + 1))
            else:
                raise RuntimeError(f"Request failed after retries: {exc}") from last_exc
    raise RuntimeError(f"Request failed: {last_exc}")


# ---------------------------------------------------------------------------
# Per-(village, murabba) fetches (cached)
# ---------------------------------------------------------------------------
_vcode_cache = {}       # (d, t, name_like, murabba) -> v_code | None
_discovery_cache = {}   # (v, murabba) -> [khas_no]
_geometry_cache = {}    # (v, murabba) -> {khas_no: [features]}


def resolve_v_code(codes, murabba):
    """Return the village v_code holding this murabba.

    If the village has a fixed `v`, use it. Otherwise auto-resolve via a
    name-LIKE query over the tehsil (used for Kehrawali chak-mustarka, whose
    murabbas are spread across sibling v_codes)."""
    if codes.get("v"):
        return codes["v"]
    like = codes.get("v_name_like")
    key = (codes["d"], codes["t"], like, murabba)
    if key in _vcode_cache:
        return _vcode_cache[key]
    params = {
        "f": "json",
        "where": (
            f"n_d_code='{codes['d']}' AND n_t_code='{codes['t']}' "
            f"AND n_murr_no='{murabba}' AND n_v_name LIKE '%{like}%'"
        ),
        "outFields": "n_v_code,n_v_name",
        "returnDistinctValues": "true",
        "returnGeometry": "false",
        "outSR": "4326",
    }
    data = query(params)
    time.sleep(REQUEST_DELAY)
    vcodes = sorted({
        (f["attributes"].get("n_v_code"), f["attributes"].get("n_v_name"))
        for f in data.get("features", [])
    })
    if not vcodes:
        print(f"  WARNING: no v_code found for murabba {murabba} (LIKE '%{like}%').")
        _vcode_cache[key] = None
        return None
    if len(vcodes) > 1:
        print(f"  NOTE: murabba {murabba} matched multiple villages {vcodes}; "
              f"using {vcodes[0][0]} ({vcodes[0][1]}).")
    v = vcodes[0][0]
    _vcode_cache[key] = v
    return v


def discover_khasras(v, murabba, codes):
    if (v, murabba) in _discovery_cache:
        return _discovery_cache[(v, murabba)]
    params = {
        "f": "json",
        "where": _base_where(codes["d"], codes["t"], v, murabba)
        + " AND n_khas_no IS NOT NULL AND n_khas_no <> ''",
        "outFields": "n_khas_no",
        "returnDistinctValues": "true",
        "returnGeometry": "false",
        "orderByFields": "n_khas_no",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
    }
    data = query(params)
    time.sleep(REQUEST_DELAY)
    valid = [f["attributes"]["n_khas_no"] for f in data.get("features", [])]
    _discovery_cache[(v, murabba)] = valid
    return valid


def fetch_geometry(v, murabba, codes):
    """Return dict: n_khas_no -> list of features (with attributes + geometry)."""
    if (v, murabba) in _geometry_cache:
        return _geometry_cache[(v, murabba)]
    params = {
        "f": "json",
        "where": _base_where(codes["d"], codes["t"], v, murabba),
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }
    data = query(params)
    time.sleep(REQUEST_DELAY)
    if data.get("exceededTransferLimit"):
        print(f"  WARNING: transfer limit exceeded for murabba {murabba}; results may be incomplete.")
    by_khasra = {}
    for feat in data.get("features", []):
        khas = feat.get("attributes", {}).get("n_khas_no")
        by_khasra.setdefault(khas, []).append(feat)
    _geometry_cache[(v, murabba)] = by_khasra
    return by_khasra


def resolve_kila(req, valid):
    """Exact match only. Khasra IDs are taken verbatim from the Jamabandi,
    so we must NOT auto-expand subdivisions (that would grab co-sharers' plots)."""
    return [k for k in valid if k == req]


def subdivisions_of(req, valid):
    """GIS sub-plots under a requested khasra, for review when exact match fails."""
    return [k for k in valid if k.startswith(req + "/")]


# ---------------------------------------------------------------------------
# Geometry helpers (ArcGIS rings are [lng, lat]; Leaflet wants [lat, lng])
# ---------------------------------------------------------------------------
def rings_to_latlng(rings):
    return [[[pt[1], pt[0]] for pt in ring] for ring in rings]


def ring_centroid_latlng(rings):
    """Average of the outer-ring vertices (excluding the closing point)."""
    outer = rings[0]
    pts = outer[:-1] if len(outer) > 1 and outer[0] == outer[-1] else outer
    if not pts:
        return None
    lat = sum(p[1] for p in pts) / len(pts)
    lng = sum(p[0] for p in pts) / len(pts)
    return [lat, lng]


def murabba_bbox(geom_map):
    """Bounding box [[south, west], [north, east]] + center across ALL khasras
    of a murabba (the true murabba square), in Leaflet [lat, lng] order."""
    min_lat = min_lng = float("inf")
    max_lat = max_lng = float("-inf")
    found = False
    for feats in geom_map.values():
        for feat in feats:
            for ring in feat.get("geometry", {}).get("rings", []):
                for lng, lat in ring:
                    found = True
                    min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
                    min_lng, max_lng = min(min_lng, lng), max(max_lng, lng)
    if not found:
        return None
    return {
        "bounds": [[min_lat, min_lng], [max_lat, max_lng]],
        "center": [(min_lat + max_lat) / 2, (min_lng + max_lng) / 2],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    txt_lines = []
    geojson_features = []
    not_found = []   # list of (village, khewat, murabba, kila)
    total_requested = 0
    total_matched = 0

    # Front-end data consumed by index.html (window.LAND_DATA)
    frontend = {
        "meta": {
            "district": DISTRICT_NAME,
            "tehsil": TEHSIL_NAME,
        },
        "villages": [],
    }

    def w(line=""):
        txt_lines.append(line)

    w("=" * 70)
    w("RANA FAMILY - LAND HOLDINGS")
    w(f"District: {DISTRICT_NAME} | Tehsil: {TEHSIL_NAME}")
    w(f"Generated: {generated}")
    w("Coordinate order in this file: [longitude, latitude], WGS84 (EPSG:4326)")
    w("=" * 70)
    w()

    try:
        for village in VILLAGES:
            codes = village["codes"]
            fe_village = {
                "id": village["id"],
                "name": village["name"],
                "hadbast": village.get("hadbast"),
                "khewats": [],
            }
            frontend["villages"].append(fe_village)

            w("=" * 70)
            w(f"VILLAGE: {village['name'].upper()}  (Hadbast {village.get('hadbast')})")
            w("=" * 70)
            w()

            for khewat, kdef in village["khewats"].items():
                owners = kdef.get("owners", [])
                murabbas = kdef["murabbas"]
                ownership_type = "Sole" if "Sole" in khewat else "Co-ownership"
                try:
                    khewat_no = int(khewat.split()[1])
                except (IndexError, ValueError):
                    khewat_no = None
                fe_khewat = {
                    "id": f"{village['id']}-khewat-{khewat_no}",
                    "number": khewat_no,
                    "label": khewat,
                    "ownership_type": ownership_type,
                    "owners": owners,
                    "share": round(kdef.get("share", 1.0), 6),
                    "murabbas": [],
                }
                fe_village["khewats"].append(fe_khewat)

                w("#" * 70)
                w(f"### {khewat}")
                if owners:
                    for o in owners:
                        ratio = f"  [{o['ratio']}]" if o.get("ratio") else ""
                        w(f"    Owner: {o['name']}{ratio}")
                w("#" * 70)
                w()

                for murabba, kilas in murabbas.items():
                    print(f"Fetching {village['name']} / Murabba {murabba} ({khewat}) ...")
                    v = resolve_v_code(codes, murabba)
                    if not v:
                        valid, geom_map = [], {}
                    else:
                        valid = discover_khasras(v, murabba, codes)
                        geom_map = fetch_geometry(v, murabba, codes)

                    fe_murabba = {
                        "number": murabba,
                        "box": murabba_bbox(geom_map),
                        "khasras": [],
                    }
                    fe_khewat["murabbas"].append(fe_murabba)

                    w(f"-- Murabba {murabba} (v_code {v or '?'}) --")
                    w(f"   Valid khasras in cadastre: {', '.join(valid) if valid else '(none)'}")
                    w()

                    for kila in kilas:
                        total_requested += 1
                        matches = resolve_kila(kila, valid)

                        if not matches:
                            not_found.append((village["name"], khewat, murabba, kila))
                            fe_murabba["khasras"].append({
                                "khas_no": kila,
                                "mapped": False,
                            })
                            subs = subdivisions_of(kila, valid)
                            if subs:
                                w(f"   Requested Kila {kila} -> NOT FOUND exactly; "
                                  f"GIS has subdivisions {', '.join(subs)} (REVIEW: verify which is owned)")
                            else:
                                w(f"   Requested Kila {kila} -> NOT FOUND in cadastre "
                                  f"(not present in HSAC GIS layer)")
                            w()
                            continue

                        w(f"   Requested Kila {kila} -> {', '.join(matches)} (exact)")

                        any_geom = False
                        for khas in matches:
                            for feat in geom_map.get(khas, []):
                                attrs = feat.get("attributes", {})
                                rings = feat.get("geometry", {}).get("rings", [])
                                if not rings:
                                    continue
                                any_geom = True
                                total_matched += 1

                                area_sqm = attrs.get(AREA_KEY)
                                try:
                                    acres = round(float(area_sqm) / SQM_PER_ACRE, 4)
                                except (TypeError, ValueError):
                                    acres = None
                                latlng_rings = rings_to_latlng(rings)
                                fe_murabba["khasras"].append({
                                    "khas_no": khas,
                                    "requested_kila": kila,
                                    "mapped": True,
                                    "objectid": attrs.get("objectid"),
                                    "kanal": attrs.get("n_kanal"),
                                    "marla": attrs.get("n_marla"),
                                    "area_sqm": area_sqm,
                                    "acres": acres,
                                    "centroid": ring_centroid_latlng(rings),
                                    "rings": latlng_rings,
                                })

                                w(f"      Khasra {khas} | objectid {attrs.get('objectid')} | "
                                  f"{attrs.get('n_kanal')} Kanal {attrs.get('n_marla')} Marla | "
                                  f"area {attrs.get(AREA_KEY)} sqm")
                                for ri, ring in enumerate(rings, start=1):
                                    w(f"        Ring {ri} ({len(ring)} points):")
                                    for pt in ring:
                                        w(f"          [{pt[0]}, {pt[1]}]")

                                geojson_features.append({
                                    "type": "Feature",
                                    "properties": {
                                        "village": village["name"],
                                        "khewat": khewat,
                                        "ownership_type": ownership_type,
                                        "murabba": murabba,
                                        "requested_kila": kila,
                                        "khas_no": khas,
                                        "kanal": attrs.get("n_kanal"),
                                        "marla": attrs.get("n_marla"),
                                        "area_sqm": attrs.get(AREA_KEY),
                                        "objectid": attrs.get("objectid"),
                                    },
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": rings,
                                    },
                                })

                        if not any_geom:
                            not_found.append((village["name"], khewat, murabba, kila))
                            w(f"      (matched khasra had no geometry returned)")
                        w()
                    w()
    except AuthError as exc:
        print()
        print("=" * 60)
        print("AUTH FAILURE:", exc)
        print("Your auth_token has likely EXPIRED.")
        print("Update the AUTH_TOKEN constant near the top of fetch_land.py")
        print("with a fresh token, then re-run.")
        print("=" * 60)
        sys.exit(1)

    # Summary
    w("=" * 70)
    w("SUMMARY")
    w(f"   Total requested kilas : {total_requested}")
    w(f"   Polygons written      : {total_matched}")
    w(f"   Kilas not found       : {len(not_found)}")
    if not_found:
        w("   Not-found list:")
        for village_name, khewat, murabba, kila in not_found:
            w(f"      - {village_name} / {khewat} / Murabba {murabba} / Kila {kila}")
    w("=" * 70)

    with open(OUT_TXT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(txt_lines) + "\n")

    feature_collection = {
        "type": "FeatureCollection",
        "name": "Rana family land holdings (Gharaunda, Karnal)",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": geojson_features,
    }
    with open(OUT_GEOJSON, "w", encoding="utf-8") as fh:
        json.dump(feature_collection, fh, indent=2)

    # Sort khewats ascending by number within each village for a tidy tree
    for fe_village in frontend["villages"]:
        fe_village["khewats"].sort(key=lambda k: (k["number"] is None, k["number"]))
    frontend["meta"]["generated"] = generated
    with open(OUT_LANDDATA, "w", encoding="utf-8") as fh:
        fh.write("window.LAND_DATA = ")
        json.dump(frontend, fh, ensure_ascii=False, indent=2)
        fh.write(";\n")

    print()
    print(f"Wrote {OUT_TXT}, {OUT_GEOJSON}, and {OUT_LANDDATA}")
    print(f"Requested kilas: {total_requested} | Polygons: {total_matched} | "
          f"Not found: {len(not_found)}")
    if not_found:
        print("Not found:")
        for village_name, khewat, murabba, kila in not_found:
            print(f"  - {village_name} / {khewat} / M{murabba} / {kila}")


if __name__ == "__main__":
    main()
