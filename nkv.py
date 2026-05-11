#!/usr/bin/env python3
"""
Natasha's Kitchen Viewer
A lightweight Python web app to display Natasha's Kitchen collected recipes.
Serves a single-page HTML/JS frontend with live updates and search.
Version: 1.0
Author: Doug - TheAncientOne (TheAncientOneGH)
Github: https://github.com/TheAncientOneGH/Natashas-Kitchen-Crawler
Donate: https://www.paypal.com/donate/?hosted_button_id=JJ2KF3GDK9C38
"""

appname = "Natasha's Kitchen Viewer"
verstr = "1.0"
domhref = "https://"
domain = "natashaskitchen.com"
dbase = "nk.db"

import http.server
import socketserver
import json
import os
import re
import webbrowser
import urllib.parse
from pathlib import Path
import threading
import sqlite3
import logging

logging.basicConfig(filename="error.log", level=logging.DEBUG, format="%(message)s")
# Configuration
# Current directory (contains 'output' subfolder)
DATA_DIR = Path(".")
DB_PATH = DATA_DIR / "output" / "db" / dbase
IP = "localhost"
PORT = 12458

# Cached database connection and recipes for performance
_db_connection = None
_cached_recipes = None

def clear_recipe_cache():
    """Clear the cached recipes and database connection."""
    global _db_connection, _cached_recipes
    if _db_connection is not None:
        _db_connection.close()
        _db_connection = None
    _cached_recipes = None

def get_db_connection():
    """Get or create a cached database connection."""
    global _db_connection
    if _db_connection is None:
        if not DB_PATH.exists():
            print(f"Warning: Database not found at {DB_PATH}")
            return None
        _db_connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db_connection.row_factory = sqlite3.Row
    return _db_connection

def stripClean(text):
    cleaned = text.replace(" (Video Recipe) ", "")
    cleaned = cleaned.replace(" (Video Recipe)", "")
    cleaned = cleaned.replace("(Video Recipe) ", "")
    cleaned = cleaned.replace("(Video Recipe)", "")
    cleaned = cleaned.replace(" VIDEO ", "")
    cleaned = cleaned.replace(" VIDEO", "")
    cleaned = cleaned.replace("VIDEO ", "")
    cleaned = cleaned.replace("VIDEO", "")
    cleaned = cleaned.replace(" ", "_")
    cleaned = cleaned.replace("____", "_")
    cleaned = cleaned.replace("___", "_")
    cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.replace("%", "--PCENT--")
    cleaned = cleaned.replace("&", "--AND--")
    cleaned = re.sub(r"[()]", "", cleaned)
    cleaned = re.sub(r'[“”,!’\'"<>:;/\\|?*]', "", cleaned)
    cleaned = cleaned.strip("_\n")
    cleaned = cleaned.strip("_")
    cleaned = cleaned.strip()
    return cleaned

def load_all_recipes():
    """Load all recipes from the SQLite database."""
    global _cached_recipes

    # Return cached recipes if available
    if _cached_recipes is not None:
        return _cached_recipes

    recipes = []
    conn = get_db_connection()
    if conn is None:
        # Fallback to JSON files if database not available
        json_dir = DATA_DIR / "output"
        if not json_dir.exists():
            print(f"Warning: {json_dir} does not exist")
            return recipes
        for json_file in json_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Ensure image_path is set for JSON fallback
                    if data.get("image"):
                        data["image_path"] = (
                            f"output/images/{stripClean(data.get('name', ''))}.webp"
                        )
                    else:
                        data["image_path"] = f"templates/noimage.jpg"
                    recipes.append(data)
            except Exception as e:
                print(f"Error loading {json_file}: {e}")
        return recipes

    try:
        cursor = conn.cursor()
        # New schema: single 'recipes' table with 'data' JSON column
        cursor.execute("SELECT name, data, added_at FROM recipes")
        rows = cursor.fetchall()

        for row in rows:
            try:
                # Parse the JSON recipe data
                recipe_data = json.loads(row["data"])

                # Restore special characters in name (was sanitized for filename)
                name = recipe_data.get("name", "")
                name = name.replace("--PCENT--", "%")
                name = name.replace("--AND--", "&")
                name = name.replace("_", " ")
                recipe_data["name"] = name

                # Add image_path relative to server
                if recipe_data.get("image"):
                    recipe_data["image_path"] = f"output/images/{stripClean(name)}.webp"
                else:
                    recipe_data["image_path"] = f"templates/noimage.jpg"

                recipes.append(recipe_data)
            except Exception as e:
                print(f"Error loading recipe row: {e}")
                logging.debug(f"Row: {row}")

    except Exception as e:
        print(f"Database error: {e}")

    _cached_recipes = recipes
    return recipes

def search_recipes(recipes, query_name="", query_ingredients="", query_category="", query_origin=""):
    """Filter recipes by name, ingredients, category, and/or origin (case-insensitive)."""
    name_lower = query_name.lower().strip()
    ing_lower = query_ingredients.lower().strip()
    cat_lower = query_category.lower().strip()
    orig_lower = query_origin.lower().strip()
    results = []
    for recipe in recipes:
        name_match = not name_lower or name_lower in recipe.get("name", "").lower()
        ing_match = not ing_lower or any(
            ing_lower in ingredient.lower()
            for ingredient in recipe.get("ingredients", [])
        )
        # Category field can be a string or list of strings
        cat_field = recipe.get("category", [])
        if cat_field is None:
            cat_field = []
        elif isinstance(cat_field, str):
            cat_field = [cat_field]
        cat_match = not cat_lower or any(cat_lower in cat.lower() for cat in cat_field)

        # Origin field can be a string or list of strings
        orig_field = recipe.get("origin", [])
        if orig_field is None:
            orig_field = []
        elif isinstance(orig_field, str):
            orig_field = [orig_field]
        orig_match = not orig_lower or any(
            orig_lower in orig.lower() for orig in orig_field
        )

        if name_match and ing_match and cat_match and orig_match:
            results.append(recipe)

    return results

class RecipeHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP request handler for the Recipe Viewer app."""

    def send_json_response(self, data, status=200):
        """Send JSON response with CORS headers."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_html_response(self, html, status=200):
        """Send HTML response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def send_static_file(self, filepath, content_type):
        """Serve a static file."""
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            # Cache static assets for 1 day (86400 seconds)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, f"File not found: {filepath}")

    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        # API endpoint: /api/recipes
        if path == "/api/recipes":
            query_name = urllib.parse.parse_qs(parsed_path.query).get("name", [""])[0]
            query_category = urllib.parse.parse_qs(parsed_path.query).get("category", [""])[0]
            query_ingredients = urllib.parse.parse_qs(parsed_path.query).get("ingredients", [""])[0]
            # Pagination parameters
            query_offset = urllib.parse.parse_qs(parsed_path.query).get("offset", ["0"])[0]
            query_limit = urllib.parse.parse_qs(parsed_path.query).get("limit", ["50"])[0]

            try:
                offset = int(query_offset)
                limit = int(query_limit)
            except ValueError:
                offset = 0
                limit = 50

            # Cap limit to prevent excessive requests
            limit = min(limit, 100)
            recipes = load_all_recipes()
            query_origin = urllib.parse.parse_qs(parsed_path.query).get("origin", [""])[0]
            filtered = search_recipes(recipes, query_name, query_ingredients, query_category, query_origin)
            total_count = len(filtered)
            # Apply pagination
            paginated = filtered[offset : offset + limit]
            self.send_json_response(
                {
                    "count": total_count,
                    "offset": offset,
                    "limit": limit,
                    "recipes": paginated,
                }
            )
            return

        # Serve index.html for root
        if path == "/" or path == "/index.html":
            self.serve_index()
            return

        if path.startswith("/templates/"):
            # Remove leading '/'
            static_file = Path(path[1:])
            # Determine extension
            ext = static_file.suffix.lower()

            if ext == ".png":
                content_types = {".png": "image/png"}
                content_type = content_types.get(ext, "image/png")
            elif ext == ".jpg":
                content_types = {".jpg": "image/jpeg"}
                content_type = content_types.get(ext, "image/jpeg")
            else:
                content_types = {".css": "text/css", ".js": "application/javascript"}
                content_type = content_types.get(ext, "text/plain")

            self.send_static_file(static_file, content_type)
            return

        # Static files: /output/thumbs/*
        if path.startswith("/output/thumbs/"):
            filename = urllib.parse.unquote(Path(path).name)
            actual_path = DATA_DIR / "output" / "thumbs" / f"{filename}"
            self.send_static_file(actual_path, "image/webp")
            return

        # Static files: /output/images/*
        if path.startswith("/output/images/"):
            filename = urllib.parse.unquote(Path(path).name)
            actual_path = DATA_DIR / "output" / "images" / f"{filename}"
            self.send_static_file(actual_path, "image/webp")
            return

        self.send_error(404, "Not found")

    def serve_index(self):
        """Generate and serve the index.html page."""
        try:
            with open("templates/index.html", "r", encoding="utf-8") as f:
                html = f.read()
            self.send_html_response(html)
        except FileNotFoundError:
            self.send_error(500, "index.html not found")

    def do_HEAD(self):
        """Handle HEAD requests."""
        self.send_response(200)
        self.end_headers()

def wait_for_exit(httpd):
    """Wait for user input: 'x' to exit, 'reload' to refresh recipes."""
    import time

    try:
        while True:
            if os.name == "nt":  # Windows
                import msvcrt

                # Check if there's input available (non-blocking)
                if msvcrt.kbhit():
                    user_input = input().strip()
                    if user_input == "x":
                        print("'x' entered. Shutting down server...")
                        httpd.shutdown()
                        break
                    elif user_input == "reload":
                        print("Reloading recipes...")
                        clear_recipe_cache()
                        load_all_recipes()
                        print("Recipes reloaded.")
            else:  # Unix-like
                import sys, tty, termios
                import select

                # Check if there's input available (non-blocking poll)
                if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                    fd = sys.stdin.fileno()
                    old = termios.tcgetattr(fd)
                    try:
                        tty.setraw(fd)
                        ch = sys.stdin.read(1)
                        if ch == "x":
                            print("\n'x' pressed. Shutting down server...")
                            httpd.shutdown()
                            break
                        elif ch == "r":
                            # Check for 'reload' command
                            buf = "r"
                            while True:
                                ch2 = sys.stdin.read(1)
                                if ch2 == "\n" or ch2 == "\r":
                                    break
                                buf += ch2
                            if buf.strip() == "reload":
                                print("\nReloading Recipes")
                                clear_recipe_cache()
                                load_all_recipes()
                                print("Recipes Reloaded.")
                    finally:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
            # Small sleep to prevent high CPU usage
            time.sleep(0.1)
    except Exception as e:
        print(f"Error in exit listener: {e}")

def main():
    """Start the HTTP server."""
    print(f"Starting Recipe Viewer Server at http://{IP}:{PORT}")
    print(f"Serving data from: {DATA_DIR.absolute()}")
    print("Enter 'x' to stop, 'reload' to refresh recipes from database.")
    with socketserver.TCPServer((IP, PORT), RecipeHandler) as httpd:
        # Start listener thread for 'x' key
        exit_thread = threading.Thread(target=wait_for_exit, args=(httpd,), daemon=True)
        exit_thread.start()
        try:
            webbrowser.open(f"http://{IP}:{PORT}")
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == "__main__":
    main()
