import json
import math
from pathlib import Path
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from sqlalchemy import text

from database.db import db, init_db

app = Flask(__name__)
CORS(app)  # Allows index.html to talk to Flask without browser CORS errors

# Initialize MySQL connection
init_db(app)

ROAD_FILE = Path(__file__).resolve().parent / "data" / "dsu_roads.geojson"


@app.route("/")
def home():
    return jsonify({
        "project": "Campus Compass",
        "message": "Welcome to Campus Compass!",
        "status": "Backend is running successfully"
    })


@app.route("/api/health")
def health():
    return jsonify({
        "status": "healthy",
        "application": "Campus Compass"
    })


@app.route("/api/db-check")
def db_check():
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return jsonify({
            "status": "connected",
            "database": "campus_compass",
            "message": "MySQL connection successful"
        })
    except Exception:
        app.logger.exception("Database connection failed")
        return jsonify({
            "status": "connection_failed",
            "message": "Could not connect to MySQL"
        }), 500


@app.route("/api/locations", methods=["GET"])
def get_locations():
    try:
        with db.engine.connect() as connection:
            query = text("""
                SELECT
                    l.location_id,
                    l.location_name,
                    l.description,
                    l.latitude,
                    l.longitude,
                    c.category_name,
                    cp.campus_name
                FROM locations l
                JOIN categories c ON l.category_id = c.category_id
                JOIN campuses cp ON l.campus_id = cp.campus_id
                ORDER BY l.location_id
            """)
            result = connection.execute(query)
            locations = [dict(row) for row in result.mappings().all()]

        return jsonify({
            "count": len(locations),
            "locations": locations
        })
    except Exception:
        app.logger.exception("Error fetching campus locations")
        return jsonify({
            "status": "error",
            "message": "Unable to fetch campus locations"
        }), 500


@app.route("/api/locations/search", methods=["GET"])
def search_locations():
    try:
        search_query = request.args.get("q", "").strip()
        if not search_query:
            return jsonify({"message": "Please enter a location to search"}), 400

        with db.engine.connect() as connection:
            query = text("""
                SELECT
                    l.location_id,
                    l.location_name,
                    l.description,
                    l.latitude,
                    l.longitude,
                    c.category_name,
                    cp.campus_name
                FROM locations l
                JOIN categories c ON l.category_id = c.category_id
                JOIN campuses cp ON l.campus_id = cp.campus_id
                WHERE
                    l.location_name LIKE :search
                    OR c.category_name LIKE :search
                    OR l.description LIKE :search
                ORDER BY l.location_id
            """)
            result = connection.execute(query, {"search": f"%{search_query}%"})
            locations = [dict(row) for row in result.mappings().all()]

        return jsonify({
            "search_query": search_query,
            "count": len(locations),
            "locations": locations
        })
    except Exception:
        app.logger.exception("Error searching campus locations")
        return jsonify({
            "status": "error",
            "message": "Unable to search campus locations"
        }), 500


@app.route("/api/locations/category/<category_name>", methods=["GET"])
def get_locations_by_category(category_name):
    try:
        with db.engine.connect() as connection:
            query = text("""
                SELECT
                    l.location_id,
                    l.location_name,
                    l.description,
                    l.latitude,
                    l.longitude,
                    c.category_name,
                    cp.campus_name
                FROM locations l
                JOIN categories c ON l.category_id = c.category_id
                JOIN campuses cp ON l.campus_id = cp.campus_id
                WHERE LOWER(c.category_name) = LOWER(:category)
                ORDER BY l.location_id
            """)
            result = connection.execute(query, {"category": category_name})
            locations = [dict(row) for row in result.mappings().all()]

        return jsonify({
            "category": category_name,
            "count": len(locations),
            "locations": locations
        })
    except Exception:
        app.logger.exception("Error filtering campus locations")
        return jsonify({
            "status": "error",
            "message": "Unable to filter campus locations"
        }), 500


@app.route("/api/locations/<int:location_id>", methods=["GET"])
def get_location_details(location_id):
    try:
        with db.engine.connect() as connection:
            query = text("""
                SELECT
                    l.location_id,
                    l.location_name,
                    l.description,
                    l.latitude,
                    l.longitude,
                    c.category_name,
                    cp.campus_name,
                    cp.address
                FROM locations l
                JOIN categories c ON l.category_id = c.category_id
                JOIN campuses cp ON l.campus_id = cp.campus_id
                WHERE l.location_id = :location_id
            """)
            result = connection.execute(query, {"location_id": location_id})
            location = result.mappings().first()

            if location is None:
                return jsonify({"message": "Location not found"}), 404

            return jsonify({"location": dict(location)})
    except Exception:
        app.logger.exception("Error fetching location details")
        return jsonify({
            "status": "error",
            "message": "Unable to fetch location details"
        }), 500


@app.route("/api/categories", methods=["GET"])
def get_categories():
    try:
        with db.engine.connect() as connection:
            query = text("""
                SELECT category_id, category_name, description
                FROM categories
                ORDER BY category_id
            """)
            result = connection.execute(query)
            categories = [dict(row) for row in result.mappings().all()]

        return jsonify({
            "count": len(categories),
            "categories": categories
        })
    except Exception:
        app.logger.exception("Error fetching categories")
        return jsonify({
            "status": "error",
            "message": "Unable to fetch categories"
        }), 500


# ==========================================================
# GEOJSON ROAD GRAPH + SHORTEST PATH ROUTING (/api/route)
# ==========================================================
def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_road_graph():
    if not ROAD_FILE.exists():
        return [], {}

    with open(ROAD_FILE, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    nodes = []       # list of (lat, lng)
    adj = {}         # idx -> list of (neighbor_idx, dist_m, road_name)

    def get_or_add_node(lat, lng):
        # Snap vertices within 12 meters so nearby GeoJSON segments connect
        for i, (nlat, nlng) in enumerate(nodes):
            if haversine_m(lat, lng, nlat, nlng) <= 12.0:
                return i
        idx = len(nodes)
        nodes.append((lat, lng))
        adj[idx] = []
        return idx

    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        road_name = feat.get("properties", {}).get("name", "Campus Road")
        coords = geom.get("coordinates", [])  # GeoJSON is [lng, lat]
        prev_idx = None
        for lon, lat in coords:
            curr_idx = get_or_add_node(lat, lon)
            if prev_idx is not None and prev_idx != curr_idx:
                d = haversine_m(*nodes[prev_idx], *nodes[curr_idx])
                adj[prev_idx].append((curr_idx, d, road_name))
                adj[curr_idx].append((prev_idx, d, road_name))
            prev_idx = curr_idx

    # Bridge any remaining disconnected road components within 65 meters
    n = len(nodes)
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_m(*nodes[i], *nodes[j])
            if 12.0 < d <= 65.0 and len(adj[i]) <= 2 and len(adj[j]) <= 2:
                adj[i].append((j, d * 1.2, "Campus Connector"))
                adj[j].append((i, d * 1.2, "Campus Connector"))

    return nodes, adj


def dijkstra_route(start_lat, start_lng, end_lat, end_lng):
    nodes, adj = build_road_graph()
    if not nodes:
        return None

    start_idx = min(range(len(nodes)), key=lambda i: haversine_m(start_lat, start_lng, *nodes[i]))
    end_idx = min(range(len(nodes)), key=lambda i: haversine_m(end_lat, end_lng, *nodes[i]))

    dist = {i: float("inf") for i in range(len(nodes))}
    prev = {i: None for i in range(len(nodes))}
    dist[start_idx] = 0.0
    unvisited = set(range(len(nodes)))

    while unvisited:
        curr = min(unvisited, key=lambda i: dist[i])
        if curr == end_idx or dist[curr] == float("inf"):
            break
        unvisited.remove(curr)

        for nxt, w, rname in adj[curr]:
            if nxt in unvisited and dist[curr] + w < dist[nxt]:
                dist[nxt] = dist[curr] + w
                prev[nxt] = (curr, rname)

    if dist[end_idx] == float("inf"):
        return None

    path_coords = []
    road_names = []
    step = end_idx
    while step is not None:
        path_coords.append([nodes[step][0], nodes[step][1]])
        if prev[step]:
            road_names.append(prev[step][1])
            step = prev[step][0]
        else:
            step = None

    path_coords.reverse()
    road_names.reverse()
    unique_roads = list(dict.fromkeys(road_names))

    total_m = max(15, round(dist[end_idx]))
    return total_m, path_coords, unique_roads


@app.route("/api/roads", methods=["GET"])
def get_raw_roads():
    if not ROAD_FILE.exists():
        return jsonify({"error": "Road file not found"}), 404
    return send_file(ROAD_FILE, mimetype="application/geo+json")


@app.route("/api/route", methods=["GET"])
def get_route():
    from_param = request.args.get("from", "")
    to_param = request.args.get("to", "")
    mode = request.args.get("mode", "walk")

    # If called with no query params, return raw GeoJSON so health checks still work
    if not from_param or not to_param:
        if not ROAD_FILE.exists():
            return jsonify({"error": "Road file not found"}), 404
        return send_file(ROAD_FILE, mimetype="application/geo+json")

    try:
        s_lat, s_lng = map(float, from_param.split(","))
        e_lat, e_lng = map(float, to_param.split(","))
    except ValueError:
        return jsonify({"error": "Invalid from/to coordinates"}), 400

    speed = 1.35 if mode == "walk" else (5.5 if mode == "bike" else 4.5)
    result = dijkstra_route(s_lat, s_lng, e_lat, e_lng)

    if result:
        total_m, coords, roads = result
        # Include short walk connector from pin to nearest road vertex
        full_coords = [[s_lat, s_lng]] + coords + [[e_lat, e_lng]]
        mins = max(1, round((total_m / speed) / 60))
        return jsonify({
            "routes": [{
                "label": "Shortest Campus Road",
                "distanceMeters": total_m,
                "durationMins": mins,
                "viaSummary": " → ".join(roads[:2]) if roads else "DSU Campus Road",
                "coords": full_coords,
                "steps": [f"Follow <b>{r}</b>" for r in roads] or ["Follow campus road"]
            }]
        })

    # Fallback if a pin is far from the draft GeoJSON lines
    direct_m = max(15, round(haversine_m(s_lat, s_lng, e_lat, e_lng)))
    mins = max(1, round((direct_m / speed) / 60))
    return jsonify({
        "routes": [{
            "label": "Campus Path",
            "distanceMeters": direct_m,
            "durationMins": mins,
            "viaSummary": "Campus Pathway",
            "coords": [[s_lat, s_lng], [e_lat, e_lng]],
            "steps": ["Proceed along campus pathway"]
        }]
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
