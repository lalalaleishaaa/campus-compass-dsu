from pathlib import Path
from flask import send_file
from flask import Flask, jsonify, request
from sqlalchemy import text

from database.db import db, init_db

app = Flask(__name__)

# Initialize MySQL connection
init_db(app)


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


# Test MySQL database connection
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

# Get all campus locations
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
                JOIN categories c
                    ON l.category_id = c.category_id
                JOIN campuses cp
                    ON l.campus_id = cp.campus_id
                ORDER BY l.location_id
            """)

            result = connection.execute(query)

            locations = [
                dict(row)
                for row in result.mappings().all()
            ]

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


# Search campus locations
@app.route("/api/locations/search", methods=["GET"])
def search_locations():
    try:
        # Get search text from the URL
        search_query = request.args.get("q", "").strip()

        if not search_query:
            return jsonify({
                "message": "Please enter a location to search"
            }), 400

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
                JOIN categories c
                    ON l.category_id = c.category_id
                JOIN campuses cp
                    ON l.campus_id = cp.campus_id
                WHERE
                    l.location_name LIKE :search
                    OR c.category_name LIKE :search
                    OR l.description LIKE :search
                ORDER BY l.location_id
            """)

            result = connection.execute(
                query,
                {"search": f"%{search_query}%"}
            )

            locations = [
                dict(row)
                for row in result.mappings().all()
            ]

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

# Get campus locations by category
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
                JOIN categories c
                    ON l.category_id = c.category_id
                JOIN campuses cp
                    ON l.campus_id = cp.campus_id
                WHERE LOWER(c.category_name) = LOWER(:category)
                ORDER BY l.location_id
            """)

            result = connection.execute(
                query,
                {"category": category_name}
            )

            locations = [
                dict(row)
                for row in result.mappings().all()
            ]

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

# Get details of a specific campus location
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
                JOIN categories c
                    ON l.category_id = c.category_id
                JOIN campuses cp
                    ON l.campus_id = cp.campus_id
                WHERE l.location_id = :location_id
            """)

            result = connection.execute(
                query,
                {"location_id": location_id}
            )

            location = result.mappings().first()

            if location is None:
                return jsonify({
                    "message": "Location not found"
                }), 404

            return jsonify({
                "location": dict(location)
            })

    except Exception:
        app.logger.exception("Error fetching location details")

        return jsonify({
            "status": "error",
            "message": "Unable to fetch location details"
        }), 500

# Get all campus categories
@app.route("/api/categories", methods=["GET"])
def get_categories():
    try:
        with db.engine.connect() as connection:

            query = text("""
                SELECT
                    category_id,
                    category_name,
                    description
                FROM categories
                ORDER BY category_id
            """)

            result = connection.execute(query)

            categories = [
                dict(row)
                for row in result.mappings().all()
            ]

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

if __name__ == "__main__":
    app.run(debug=True)
ROAD_FILE = Path(__file__).resolve().parent / "data" / "dsu_roads.geojson"

@app.route("/api/route", methods=["GET"])
def get_route():
    if not ROAD_FILE.exists():
        return {"error": "Road file not found"}, 404

    return send_file(
        ROAD_FILE,
        mimetype="application/geo+json"
    )