# CLAUDE.md — Project notes & hard-won learnings

Project: Viewer for **Girwar Singh Rana**'s land holdings in
**District Karnal → Tehsil Gharaunda → Village Raseen**, sourced from the
HSAC Haryana (eodb) digital land-record GIS, rendered on a Leaflet + Esri map.

## Files
- `fetch_land.py` — pulls polygons from the HSAC ArcGIS API and writes:
  - `girwar_singh_land.txt` (human-readable)
  - `girwar_singh_land.geojson` (FeatureCollection, `[lng,lat]`)
  - `land_data.js` (`window.LAND_DATA`, coords already in Leaflet `[lat,lng]`)
- `index.html` — single deployable page (Leaflet + Esri imagery), loads `land_data.js`
  via `<script src>` so it works from `file://` (no server / no CORS).
- `source_of_land/*.html` — Jamabandi records used to verify ownership.

## HSAC API — how it actually works
- Base (parcels): `https://hsac.in/eodb_backend/mapserver/service/hsacMain/10/query`
- Boundaries: `https://hsac.in/eodb_backend/mapserver/service/hsacBoundaries/2/query`
- It's a standard **ArcGIS REST FeatureServer**. Useful params:
  `f=json`, `where=...`, `outFields=*`, `returnGeometry=true|false`,
  `returnDistinctValues=true`, `orderByFields=...`, `outSR=4326`,
  `spatialRel=esriSpatialRelIntersects`.
- Location filter columns (strings, keep the quotes and leading zeros):
  `n_d_code='10'` (district), `n_t_code='063'` (tehsil),
  `n_v_code='06056'` (village), `n_murr_no='16'` (murabba), `n_khas_no` (khasra).
- Area field is literally named `st_area(shape)` (sqm). Convert with
  `acres = sqm / 4046.8564224`.
- **Coordinate order**: ArcGIS returns rings as `[lng, lat]`. Leaflet wants
  `[lat, lng]`. We convert in `fetch_land.py` so the frontend stays simple.
  (GeoJSON output stays `[lng, lat]` per spec.)

## Authentication — the part that cost the most time
- Auth is a **JWT in a cookie named `auth_token`**, NOT a Bearer header.
  Send it as: `Cookie: auth_token=<JWT>`. We set
  `session.headers["cookie"] = f"auth_token={AUTH_TOKEN}"` (setting it via the
  cookie *jar* with a domain was flaky — the explicit header is reliable).
- The JWT lifetime is **~24h** (`exp` in the payload). When it expires the API
  returns **HTTP 401** and `fetch_land.py` prints a clear "AUTH FAILURE" message.
- The extra `_ga*` analytics cookies and `sec-fetch-*` headers from the browser
  curl are **not required** — `auth_token` alone returns 200.
- To refresh: in the browser DevTools → Network, copy the `auth_token` cookie
  from any `.../query` request and paste it into `AUTH_TOKEN` (line ~25 of
  `fetch_land.py`), then re-run.

### Gotcha that burned us: stale editor view
- The IDE once showed a *new* token on line 25 while the file on disk still held
  the *old, expired* one — every string-replace silently "matched the new value"
  but the run kept 401-ing. **Verify the real value** by importing it
  (`python -c "import fetch_land; print(fetch_land.AUTH_TOKEN[-12:])"`) or by
  doing the replacement with a small Python script (`re.subn`) rather than
  trusting the rendered buffer.

## Data / ownership correctness
- Khasra IDs are taken **verbatim** from the Jamabandi (e.g. `24/1/2`, not `24/1`).
  Do **exact matching only** — prefix matching wrongly grabs co-sharers'
  sub-plots. See `resolve_kila()` (exact) vs `subdivisions_of()` (review hint).
- **Khewat 11** = sole ownership. **Khewats 5 & 6** = co-ownership: the GIS
  polygons are the **full plots**, not Girwar's fractional share — the viewer
  shows a co-ownership note for these.
- **Kila 64 (Khewat 11 / Murabba 19)** is a real plot but has **no GIS polygon**
  in the layer, so it appears in the tree disabled/greyed and can't be highlighted.
- The "murabba box" (white square) is the bounding box across **ALL** khasras of a
  murabba (the true murabba extent), computed in `murabba_bbox()`.

## Map rendering conventions
- Base: Esri `World_Imagery` (keyless satellite) + `World_Boundaries_and_Places`
  labels overlay. `maxZoom: 19`.
- Khasra: yellow semi-opaque polygon, centered tooltip `"{murabba} // {khasra}"`.
- Murabba: white **unfilled** rectangle, centered tooltip = murabba number.
- Two `L.layerGroup`s (khasras, boxes) are cleared & redrawn on each selection.

## Running
```
pip install -r requirements.txt
python fetch_land.py          # needs a valid auth_token
# then open index.html in a browser (works from file://)
```

## Operational rule
- If a token is expired, **stop and ask the user for a fresh `auth_token`** rather
  than guessing — there is no programmatic way to mint one here.
