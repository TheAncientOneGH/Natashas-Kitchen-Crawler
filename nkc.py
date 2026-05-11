#!/usr/bin/env python3
"""
Natasha's Kitchen Crawler
A Selenium-based web crawler to collect and view recipe data from natashaskitchen.com
Collects: recipe name, ingredients, instructions, category, and an image
Version: 1.0
Author: Doug - TheAncientOne (TheAncientOneGH)
Github: https://github.com/TheAncientOneGH/Natashas-Kitchen-Crawler
Donate: https://www.paypal.com/donate/?hosted_button_id=JJ2KF3GDK9C38
"""

appname = "Natasha's Kitchen Crawler"
verstr = "1.0"
appnameabbr = f"NK Crawler v{verstr}"
domhref = "https://"
domain = "natashaskitchen.com"
dbase = "nk.db"
uagent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

import os
import sys
import subprocess
import threading
import queue
import re
import time
import json
import signal
import argparse
import html
import sqlite3
from datetime import datetime
from urllib.parse import urljoin, urlparse
from pathlib import Path

def inPack(pack):
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                pack,
                "--upgrade",
                "--no-warn-script-location",
            ]
        )
        __import__(pack)
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pack, "--no-warn-script-location"]
        )
    return

inPack("selenium")
inPack("urllib3")
inPack("Pillow")
inPack("webdriver-manager")
inPack("requests")
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuration
BASE_URL = f"{domhref}{domain}"
DATA_DIR = Path("output")
DB_DIR = DATA_DIR / "db"
DB_FILE = DB_DIR / dbase
IMAGES_DIR = DATA_DIR / "images"
THUMBS_DIR = DATA_DIR / "thumbs"
RESUME_DIR = DATA_DIR / "resume"
COLLECTED_DIR = DATA_DIR / "resume/"
RESUME_FILE = RESUME_DIR / "resume.json"
COLLECTED_FILE = COLLECTED_DIR / "collected_recipes.json"
SKIP_DIR = Path("skip")
SKIP_FILE = SKIP_DIR / "skiplist.json"
IGNORE_FILE = SKIP_DIR / "ignore.json"
# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
DB_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)
THUMBS_DIR.mkdir(exist_ok=True)
RESUME_DIR.mkdir(exist_ok=True)
COLLECTED_DIR.mkdir(exist_ok=True)
SKIP_DIR.mkdir(exist_ok=True)
DEBUGEN = False

class RecipeCrawler:
    def __init__(self, full_run=False):
        self.driver = None
        self.visited_urls = set()
        self.collected_recipes = {}
        self.full_run = full_run
        self.running = True
        self.progress = {"last_url": None, "total_collected": 0, "last_update": None}
        self.input_queue = queue.Queue()
        self.input_thread = None
        self.crawl_queue = []
        self.skipped_urls = set()
        self.ignore_patterns = []
        # Seconds
        self.page_load_timeout = 20
        self.max_retries = 2
        # Load saved state
        self.load_ignorelist()
        self.load_progress()
        self.load_collected()
        self.load_skiplist()
        self.init_database()
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        print("\nShutdown signal received. Saving progress...")
        self.save_progress()
        self.running = False
        sys.exit(0)

    def _input_thread_func(self):
        """Thread function to read user input"""
        try:
            while self.running:
                try:
                    user_input = sys.stdin.readline()
                    if not user_input:
                        break
                    user_input = user_input.strip().lower()
                    self.input_queue.put(user_input)
                except (OSError, EOFError):
                    break
        except Exception:
            pass

    def check_user_input(self):
        """Check if user has requested shutdown or added URLs to queue (non-blocking)"""
        should_shutdown = False
        try:
            while True:
                user_input = self.input_queue.get_nowait()
                if user_input == "x":
                    should_shutdown = True
                elif user_input.startswith("get:"):
                    url = user_input[4:].strip()
                    if url:
                        parsed = urlparse(url)
                        if not parsed.scheme:
                            url = "https://" + url
                        if f"{domain}" in urlparse(url).netloc:
                            if (
                                url not in self.crawl_queue
                                and url not in self.visited_urls
                                and url not in self.skipped_urls
                                and not self.should_ignore(url)
                            ):
                                self.crawl_queue.insert(0, url)
                                print(f"\nQueue Size: {len(self.crawl_queue)}")
                                print(f"\nAdded to queue: {url}")
                            elif self.should_ignore(url):
                                print(f"\nIgnored (matches ignore pattern): {url}")
                        else:
                            print(f"\nOnly {domain} URLs are supported: {url}")
        except queue.Empty:
            pass
        return should_shutdown

    def setup_driver(self):
        """Initialize Selenium WebDriver with robust settings"""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins-discovery")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        # Add user agent to appear more like a real browser
        options.add_argument(f"--user-agent={uagent}")
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service

            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        except Exception as e:
            print(f"Warning: webdriver-manager failed ({e}), trying direct Chrome...")
            try:
                self.driver = webdriver.Chrome(options=options)
            except Exception as e2:
                print(f"Error initializing Chrome driver: {e2}")
                print("Please ensure Chrome browser is installed.")
                sys.exit(1)

        # Execute script to hide webdriver detection
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # Set page load timeout
        self.driver.set_page_load_timeout(self.page_load_timeout)
        # Set implicit wait
        self.driver.implicitly_wait(5)

    def stripClean(self, text):
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

    def load_progress(self):
        if not self.full_run and RESUME_FILE.exists():
            try:
                with open(RESUME_FILE, "r") as f:
                    self.progress = json.load(f)
                print(f"Resuming from: {self.progress.get('last_url', 'start')}")
            except Exception as e:
                print(f"Error loading progress: {e}")

    def load_collected(self):
        if COLLECTED_FILE.exists():
            try:
                with open(COLLECTED_FILE, "r") as f:
                    self.collected_recipes = json.load(f)
                print(f"Loaded {self.clean_collected()} previously collected recipes")
            except Exception as e:
                print(f"Error loading collected recipes: {e}")
        else:
            with open(COLLECTED_FILE, "w") as f:
                json.dump({}, f, indent=2)

    def load_ignorelist(self):
        if IGNORE_FILE.exists():
            try:
                with open(IGNORE_FILE, "r") as f:
                    data = json.load(f)
                    self.ignore_patterns = data.get("ignore_links", [])
                if self.ignore_patterns:
                    print(f"Loaded {len(self.ignore_patterns)} ignore patterns")
            except Exception as e:
                print(f"Error loading ignore list: {e}")
                self.ignore_patterns = []
        else:
            self.ignore_patterns = []

    def load_skiplist(self):
        if SKIP_FILE.exists():
            try:
                with open(SKIP_FILE, "r") as f:
                    data = json.load(f)
                    self.skipped_urls = set(data.get("skipped_urls", []))
                if self.skipped_urls:
                    print(f"Loaded {len(self.skipped_urls)} URLs to skip")
            except Exception as e:
                print(f"Error loading skiplist: {e}")
                self.skipped_urls = set()

    def init_database(self):
        """Initialize SQLite database and import existing JSON files"""
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Create recipes table with name as primary key
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipes (
                    name TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    added_at TEXT NOT NULL
                )
            """)

            # Create index on name for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recipes_name ON recipes(name)
            """)

            conn.commit()
            print(f"This can take a long time depending on size of database rebuild.")
            print(f"Please, wait...")
            print(f"Database initialized: {DB_FILE}")

            # Import existing JSON files
            self.import_json_to_database(cursor, conn)

        except sqlite3.Error as e:
            print(f"Database error: {e}")
        finally:
            if conn:
                conn.close()

    def import_json_to_database(self, cursor, conn):
        """Import JSON files from output directory into database"""
        json_files = list(DATA_DIR.glob("*.json"))
        imported_count = 0
        skipped_count = 0

        for json_file in json_files:
            # Skip files in subdirectories (resume, images, thumbs, db)
            if json_file.parent != DATA_DIR:
                continue

            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    recipe_data = json.load(f)

                name = recipe_data.get("name")
                if not name:
                    skipped_count += 1
                    continue

                # Check if name already exists in database
                cursor.execute("SELECT name FROM recipes WHERE name = ?", (name,))
                if cursor.fetchone():
                    skipped_count += 1
                    continue

                # Insert new recipe
                cursor.execute(
                    "INSERT INTO recipes (name, data, added_at) VALUES (?, ?, ?)",
                    (name, json.dumps(recipe_data), datetime.now().isoformat()),
                )
                print(f"Imported: {name}")
                imported_count += 1

            except Exception as e:
                print(f"Error importing {json_file.name}: {e}")

        conn.commit()
        print(
            f"Imported {imported_count} recipes to database ({skipped_count} already existed or skipped)"
        )

    def should_ignore(self, url):
        for pattern in self.ignore_patterns:
            if pattern in url:
                return True
        return False

    def add_to_skiplist(self, url, error_msg=""):
        self.skipped_urls.add(url)
        try:
            data = {"skipped_urls": sorted(list(self.skipped_urls))}
            with open(SKIP_FILE, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Added to skiplist: {url} (error: {error_msg})")
        except Exception as e:
            print(f"Error saving to skiplist: {e}")

    def save_progress(self):
        self.progress["last_update"] = datetime.now().isoformat()
        try:
            with open(RESUME_FILE, "w") as f:
                json.dump(self.progress, f, indent=2)
        except Exception as e:
            print(f"Error saving progress: {e}")

    def save_collected(self):
        try:
            with open(COLLECTED_FILE, "w") as f:
                json.dump(self.collected_recipes, f, indent=2)
        except Exception as e:
            print(f"Error saving collected recipes: {e}")

    def clean_collected(self):
        newlist = {}
        seen = set()
        with open(COLLECTED_FILE, "r") as f:
            data = json.load(f)
            for url, vals in data.items():
                if vals.get("file") and vals["file"] not in seen:
                    newlist[url] = vals
                seen.add(vals.get("file", ""))
        return len(newlist)

    def clean_filename(self, name):
        name = name.strip()
        cleaned = html.unescape(name)
        cleaned = self.stripClean(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:200]

    def _clean_html_entities(self, text):
        if isinstance(text, str):
            return html.unescape(text)
        return text

    def _is_loader_image_url(self, url):
        """Check if an image URL appears to be a loader/placeholder image"""
        if not url:
            return True

        url_lower = url.lower()
        # Common patterns for loader/placeholder images
        loader_patterns = [
            "loader",
            "placeholder",
            "default",
            "blank",
            "transparent",
            "spinner",
            "loading",
            "pixel",
            "data:image",
            "no-image",
            "noimage",
            "missing",
        ]

        # Check for tiny size patterns (common in spacers)
        # Only flag as loader if URL is very short (actual pixel spacer, not a real image with "1x1" in path)
        if ("1x1" in url_lower or "2x2" in url_lower) and len(url) < 60:
            return True

        # Check for loader keywords
        if any(pattern in url_lower for pattern in loader_patterns):
            return True

        # Check if it's a data URI (inline placeholder)
        if url_lower.startswith("data:image"):
            return True

        # Very short URLs are suspect (often just a hash or ID)
        if len(url) < 30:
            return True

        return False

    def extract_image_from_dom(self):
        """Extract the actual recipe image URL from DOM lazy-loading attributes"""
        if self.driver is None:
            return None

        try:
            # Selectors (updated for current site structure)
            selectors = [
                "img[data-src]",
                "img[data-srcset]",
                "img[data-original]",
                "img[data-lazyload]",
                "img[data-image]",
                'img[data-sizes="auto"]',
                "img.rec-image",
                "img.rec-photo",
                "img.photo",
                "img.schema-org-image",
                'img[itemprop="image"]',
                "img.details__image",
                "img.lead-image",
                "img.primary-image",
                "img.kr-image",
                "img.unstyled-image",
                "img.multimedia-image",
                f'img[src*="{domain}"]',
                f'img[src*="images.{domain}"]',
                'img[src*="recipe-images"]',
                "div.rec-photo img",
                "figure.rec-photo img",
                ".image-container img",
                ".hero-image img",
                ".recipe-image img",
            ]
            candidate_urls = []

            for selector in selectors:
                try:
                    images = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for img in images:
                        # Try different attributes in order of preference
                        for attr in [
                            "data-src",
                            "data-srcset",
                            "data-original",
                            "data-lazyload",
                            "data-image",
                            "data-sizes",
                            "src",
                        ]:
                            url = img.get_attribute(attr)
                            if url and isinstance(url, str) and url.strip():
                                url = url.strip()

                                # For srcset, extract first URL
                                if "srcset" in attr:
                                    parts = url.split(",")[0].strip().split(" ")[0]
                                    url = parts

                                # Make absolute URL
                                if url.startswith("//"):
                                    url = "https:" + url
                                elif url.startswith("/"):
                                    url = urljoin(BASE_URL, url)

                                # Only add if it looks like a valid image URL
                                if len(url) > 30 and any(
                                    ext in url.lower()
                                    for ext in [
                                        ".bmp",
                                        ".jpg",
                                        ".jpeg",
                                        ".png",
                                        ".webp",
                                        ".gif",
                                    ]
                                ):
                                    candidate_urls.append(url)
                except Exception:
                    continue

            # Fallback: scan all img tags for plausible images
            if not candidate_urls:
                try:
                    all_imgs = self.driver.find_elements(By.TAG_NAME, "img")
                    for img in all_imgs[:20]:
                        src = img.get_attribute("src")
                        if src and isinstance(src, str) and len(src) > 30:
                            src_lower = src.lower()
                            # Must be same domain and not be an icon/logo
                            if (
                                f"{domain}" in src_lower
                                or f"images.{domain}" in src_lower
                            ):
                                if not any(
                                    skip in src_lower
                                    for skip in [
                                        "icon",
                                        "logo",
                                        "button",
                                        "badge",
                                        "sprite",
                                        "svg",
                                        "pixel",
                                    ]
                                ):
                                    candidate_urls.append(src)
                except Exception:
                    pass

            # Return first non-loader URL
            for url in candidate_urls:
                if not self._is_loader_image_url(url):
                    print(f"  Found image URL from DOM: {url[:80]}...")
                    return url

            # If all candidates are loaders, nothing good found
            if candidate_urls:
                print(
                    f"  All {len(candidate_urls)} candidate images were loader/placeholder images"
                )

        except Exception as e:
            if DEBUGEN:
                print(f"  Debug: Error extracting image from DOM: {e}")
            else:
                pass

        return None

    def extract_jsonld_data(self):
        """Extract recipe data from JSON-LD script tags with multiple fallbacks"""
        recipes = []
        if self.driver is None:
            return recipes

        try:
            # First try: standard JSON-LD
            scripts = self.driver.find_elements(
                By.XPATH, '//script[@type="application/ld+json"]'
            )

            # If no JSON-LD found, also check for other script tags that might contain recipe data
            if not scripts:
                scripts = self.driver.find_elements(
                    By.XPATH, '//script[contains(text(), "recipeIngredient")]'
                )
        except Exception as e:
            if DEBUGEN:
                print(f"  Debug: Error finding script tags: {e}")
            else:
                pass
            return recipes

        for idx, script in enumerate(scripts):
            try:
                # Try multiple methods to get script text (different browsers may need different approaches)
                json_text = None

                # Method 1: innerHTML attribute
                try:
                    json_text = script.get_attribute("innerHTML")
                except:
                    pass

                # Method 2: textContent attribute
                if not json_text:
                    try:
                        json_text = script.get_attribute("textContent")
                    except:
                        pass

                # Method 3: script.text property
                if not json_text:
                    try:
                        json_text = script.text
                    except:
                        pass

                # Method 4: Execute JavaScript to get textContent
                if not json_text:
                    try:
                        json_text = self.driver.execute_script(
                            "return arguments[0].textContent;", script
                        )
                    except:
                        pass

                if not json_text or not isinstance(json_text, str):
                    continue

                # Clean up the JSON text
                json_text = json_text.strip()
                json_text = re.sub(r"<!--.*?-->", "", json_text, flags=re.DOTALL)
                json_text = re.sub(
                    r"<!\[CDATA\[(.*?)\]\]>", r"\1", json_text, flags=re.DOTALL
                )

                try:
                    data = json.loads(json_text)
                except json.JSONDecodeError as e:
                    if DEBUGEN:
                        print(f"  Debug: JSON parse error in script {idx}: {e}")
                    continue

                # Handle @graph format (Yoast SEO uses this format)
                if isinstance(data, dict) and "@graph" in data:
                    items = data["@graph"]
                elif isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = [data]
                else:
                    continue

                for item in items:
                    if isinstance(item, dict):
                        item_type = item.get("@type", "")
                        if isinstance(item_type, list):
                            is_recipe = "Recipe" in item_type or "recipe" in item_type
                        else:
                            is_recipe = item_type in ["Recipe", "recipe", "HowTo"]

                        # Additional check for WP Recipe Maker format which may not have @type
                        if not is_recipe and "recipeIngredient" in item:
                            is_recipe = True

                        # Check for WP Recipe Maker format with nested recipe data
                        if not is_recipe:
                            wprm_data = item.get("recipe", {})
                            if (
                                isinstance(wprm_data, dict)
                                and "recipeIngredient" in wprm_data
                            ):
                                is_recipe = True
                                item = wprm_data

                        if is_recipe:
                            recipes.append(item)
            except Exception as e:
                if DEBUGEN:
                    print(f"  Debug: Error processing script {idx}: {e}")
                continue

        return recipes

    def extract_wprm_from_dom(self):
        """Extract recipe data from WP Recipe Maker DOM elements as fallback"""
        recipes = []
        if self.driver is None:
            return recipes

        try:
            # Check for WP Recipe Maker container
            wprm_containers = self.driver.find_elements(
                By.CSS_SELECTOR, ".wprm-recipe-container"
            )

            for container in wprm_containers:
                try:
                    recipe = {
                        "name": "",
                        "recipeIngredient": [],
                        "recipeInstructions": [],
                        "recipeCategory": None,
                        "recipeCuisine": None,
                    }

                    # Get recipe name
                    name_elem = container.find_elements(
                        By.CSS_SELECTOR, ".wprm-recipe-name"
                    )
                    if name_elem:
                        recipe["name"] = name_elem[0].text.strip()

                    # Get ingredients
                    ingredient_elems = container.find_elements(
                        By.CSS_SELECTOR, ".wprm-recipe-ingredient"
                    )
                    for elem in ingredient_elems:
                        text = elem.text.strip()
                        if text:
                            recipe["recipeIngredient"].append(text)

                    # Get instructions
                    instruction_elems = container.find_elements(
                        By.CSS_SELECTOR, ".wprm-recipe-instruction"
                    )
                    for elem in instruction_elems:
                        text = elem.text.strip()
                        if text:
                            recipe["recipeInstructions"].append({"text": text})

                    # Get categories
                    cat_elems = container.find_elements(
                        By.CSS_SELECTOR, ".wprm-recipe-category"
                    )
                    if cat_elems:
                        recipe["recipeCategory"] = [
                            e.text.strip() for e in cat_elems if e.text.strip()
                        ]

                    # Get cuisine
                    cuisine_elems = container.find_elements(
                        By.CSS_SELECTOR, ".wprm-recipe-cuisine"
                    )
                    if cuisine_elems:
                        recipe["recipeCuisine"] = [
                            e.text.strip() for e in cuisine_elems if e.text.strip()
                        ]

                    if recipe["name"] and recipe["recipeIngredient"]:
                        recipes.append(recipe)
                        if DEBUGEN:
                            print(
                                f"  Debug: Extracted WPRM recipe from DOM: {recipe['name']}"
                            )
                except Exception as e:
                    if DEBUGEN:
                        print(f"  Debug: Error extracting WPRM from DOM: {e}")
                    continue
        except Exception as e:
            if DEBUGEN:
                print(f"  Debug: Error finding WPRM containers: {e}")

        return recipes

    def download_image(self, image_url, filename):
        """Download and save recipe image (only if 250x250 or larger)"""
        try:
            if not image_url or not isinstance(image_url, str):
                return None

            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif image_url.startswith("/"):
                image_url = urljoin(BASE_URL, image_url)

            session = requests.Session()
            retry_strategy = Retry(
                total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            headers = {"User-Agent": f"{uagent}"}
            response = session.get(image_url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()

            try:
                from PIL import Image as PILImage
            except ImportError:
                PILImage = None

            if PILImage:
                from io import BytesIO

                img_data = BytesIO()
                for chunk in response.iter_content(chunk_size=8192):
                    img_data.write(chunk)
                img_data.seek(0)

                img = PILImage.open(img_data)
                width, height = img.size

                if width < 250 or height < 250:
                    print(f"Skipping image - too small: {width}x{height}")
                    return None

                # Convert to webp and resize to 785x301 for main image
                img = img.convert("RGB")  # Ensure RGB mode for webp
                # Use LANCZOS resampling (best quality for downscaling)
                resample = (
                    PILImage.Resampling.LANCZOS
                    if hasattr(PILImage, "Resampling")
                    else 1
                )
                img_resized = img.resize((785, 301), resample)
                # Generate webp filename
                safe_name = os.path.splitext(filename)[0]
                safe_name = self.stripClean(safe_name)
                webp_filename = f"{safe_name}.webp"
                image_path = IMAGES_DIR / webp_filename

                # Save resized webp image
                img_resized.save(image_path, format="WEBP", quality=85)
                print(f"Saved webp image to: {image_path}")
                thumb = img.resize((267, 200), resample)

                thumb_filename = f"{safe_name}.webp"
                thumb_path = THUMBS_DIR / thumb_filename
                thumb.save(thumb_path, format="WEBP", quality=85)
                print(f"Saved thumbnail to: {thumb_path}")

                return str(image_path)
            else:
                print("Warning: PIL not installed, skipping conversion")
                image_path = IMAGES_DIR / filename
                with open(image_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return str(image_path)

        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")
            return None

    def extract_recipe_info(self, recipe_data, page_url):
        """Extract structured recipe information from JSON-LD data"""
        name = recipe_data.get("name")
        if name is None:
            name = ""

        category = recipe_data.get("recipeCategory") or recipe_data.get("recipeCuisine")
        if category is None:
            category = []
        elif isinstance(category, str):
            category = [category]

        name = self._clean_html_entities(name)
        name = self.stripClean(name)

        recipe = {
            "name": name,
            "origin": [],
            "category": category,
            "ingredients": [],
            "instructions": [],
            "href": f"{domhref}",
            "site": f"{domain}",
            "url": page_url,
            "image": True,
            "v": f"{verstr}",
            "extracted_at": datetime.now().isoformat(),
        }

        # Extract image URL - try JSON-LD first, then fall back to DOM extraction
        image_url_from_json = None
        image_data = recipe_data.get("image")
        if image_data is None:
            image_data = ""
        if isinstance(image_data, list) and len(image_data) > 0:
            image_data = image_data[0]

        if isinstance(image_data, dict):
            image_url_from_json = image_data.get("url", "")
        else:
            image_url_from_json = str(image_data) if image_data else ""

        # Clean up the URL
        if image_url_from_json:
            image_url_from_json = image_url_from_json.strip()
            if image_url_from_json.startswith("//"):
                image_url_from_json = "https:" + image_url_from_json
            elif image_url_from_json.startswith("/"):
                image_url_from_json = urljoin(BASE_URL, image_url_from_json)

        global _tempimage
        _tempimage = image_url_from_json

        # If JSON-LD image looks like a loader/placeholder, try DOM extraction
        if not image_url_from_json or self._is_loader_image_url(image_url_from_json):
            dom_image_url = self.extract_image_from_dom()
            if dom_image_url:
                _tempimage = dom_image_url
                # recipe["image_url"] = dom_image_url
                print(
                    f"  Using image URL from DOM (JSON-LD image was loader/missing): {dom_image_url[:80]}..."
                )

        ingredients = recipe_data.get("recipeIngredient")
        if ingredients is None:
            ingredients = []
        if isinstance(ingredients, list):
            for ingredient in ingredients:
                if ingredient:
                    recipe["ingredients"].append(self._clean_html_entities(ingredient))

        instructions = recipe_data.get("recipeInstructions")
        if instructions is None:
            instructions = []
        if isinstance(instructions, list):
            for inst in instructions:
                if isinstance(inst, dict):
                    text = inst.get("text", "")
                    if text:
                        recipe["instructions"].append(self._clean_html_entities(text))
                elif isinstance(inst, str):
                    recipe["instructions"].append(self._clean_html_entities(inst))

        return recipe

    def add_recipe_to_database(self, recipe_data):
        """Add a single recipe to the SQLite database"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            name = recipe_data.get("name")
            if not name:
                return False

            # Check if recipe already exists
            cursor.execute("SELECT name FROM recipes WHERE name = ?", (name,))
            if cursor.fetchone():
                print(f"  Recipe already in database: {name}")
                conn.close()
                return False

            # Insert recipe
            cursor.execute(
                "INSERT INTO recipes (name, data, added_at) VALUES (?, ?, ?)",
                (name, json.dumps(recipe_data), datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            print(f"  Added to database: {name}")
            return True

        except sqlite3.Error as e:
            print(f"  Database error adding recipe: {e}")
            return False

    def save_recipe(self, recipe_data, page_url):
        """Save recipe to JSON file"""
        recipe_name = recipe_data.get("name")
        recipe_name = self._clean_html_entities(recipe_name)
        recipe_name = self.stripClean(recipe_name)

        if not recipe_name:
            print("Warning: Recipe has no name, skipping")
            return False

        display_name = self._clean_html_entities(recipe_name)

        if page_url in self.collected_recipes:
            print(f"Skipping already collected: {display_name}")
            return False

        safe_name = self.clean_filename(recipe_name)
        safe_name = self.stripClean(safe_name)

        if not safe_name:
            safe_name = f"recipe_{int(time.time())}"

        json_filename = f"{safe_name}.json"
        json_path = DATA_DIR / json_filename
        recipe_info = self.extract_recipe_info(recipe_data, page_url)

        global _tempimage

        if _tempimage:
            image_filename = f"{safe_name}.webp"
            recipe_info["origin"] = recipe_data.get("recipeCuisine")
            print(f"Downloading image: {_tempimage}")
            saved_path = self.download_image(_tempimage, image_filename)

            if saved_path:
                print(f"Saved image to: {saved_path}")

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(recipe_info, f, indent=2, ensure_ascii=False)

            self.collected_recipes[page_url] = {
                "name": display_name,
                "file": json_filename,
                "collected_at": datetime.now().isoformat(),
            }
            self.save_collected()
            print(f"Saved recipe: {display_name} -> {json_filename}")
            print(f"Total Recipes: {self.clean_collected()}")

            # Add to database immediately after saving
            self.add_recipe_to_database(recipe_info)

        except Exception as e:
            print(f"Error saving recipe {display_name}: {e}")
            return False

        return True

    def is_valid_url(self, url):
        if not url or not isinstance(url, str):
            return False
        parsed = urlparse(url)
        if not parsed.netloc:
            return False
        return f"{domain}" in parsed.netloc

    def find_links(self):
        """Find all internal links on current page"""
        links = []
        if self.driver is None:
            return links

        try:
            all_links = self.driver.find_elements(By.TAG_NAME, "a")
            if DEBUGEN:
                print(f"  Debug: Found {len(all_links)} total links on page")
            for link in all_links:
                try:
                    href = link.get_attribute("href")
                    if href and isinstance(href, str):
                        href = href.strip()
                        if self.is_valid_url(href):
                            links.append(href)
                except Exception:
                    continue
        except Exception as e:
            print(f"  Debug: Error finding links: {e}")

        unique_links = list(set(links))
        if DEBUGEN:
            print(f"  Debug: Found {len(unique_links)} unique valid {domain} links")
        return unique_links

    def wait_for_page_load(self, url):
        """Wait for page to be fully loaded with multiple strategies"""
        if self.driver is None:
            return False

        try:
            # Use explicit wait for document ready state
            WebDriverWait(self.driver, self.page_load_timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Also wait for body to be present
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Give extra time for JavaScript to render
            time.sleep(2)
            return True

        except TimeoutException:
            print(f"  Warning: Page load timeout for {url}")
            return False
        except Exception as e:
            print(f"  Warning: Error waiting for page load: {e}")
            return False

    def updateCrawl(self):
        print("=" * 60)
        print(f"{appname} v{verstr}")
        print("=" * 60)
        if self.full_run:
            print("Mode: Full Run")
        else:
            print("Mode: Resume Run")
        print(f"Starting URL: {BASE_URL}")
        print("Press 'x' + Enter to stop crawling")
        print("Or type 'get:<url>' to add a specific URL to the queue")
        print(f"Currently collected: {self.clean_collected()} recipes")
        print("=" * 60)
        return

    def crawl_page(self, url):
        """Crawl a single page with robust error handling"""
        if not self.running:
            return []

        if url in self.visited_urls:
            return []

        if url in self.skipped_urls:
            print(f"Skipping URL (in skiplist): {url}")
            return []

        if self.driver is None:
            print("Error: WebDriver not initialized")
            return []

        print(f"\nCrawling: {url}")
        self.visited_urls.add(url)

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    print(f"  Retry attempt {attempt}/{self.max_retries}")

                # Navigate to URL with timeout handling
                try:
                    self.driver.get(url)
                except Exception as e:
                    if attempt < self.max_retries:
                        print(f"  Page load failed: {e}, retrying...")
                        time.sleep(3)
                        continue
                    else:
                        print(
                            f"  Page load failed after {self.max_retries} retries: {e}"
                        )
                        self.add_to_skiplist(url, str(e))
                        return []

                # Wait for page to load properly
                if not self.wait_for_page_load(url):
                    if attempt < self.max_retries:
                        continue

                # Debug: Print page title
                try:
                    title = self.driver.title
                    if DEBUGEN:
                        print(f"  Page title: {title}")
                except:
                    pass

                # Extract recipe data from JSON-LD
                recipe_data_list = self.extract_jsonld_data()
                if DEBUGEN:
                    print(f"  Debug: Found {len(recipe_data_list)} recipe objects")
                    if len(recipe_data_list) == 0:
                        # Try to find any script tags for debugging
                        try:
                            all_scripts = self.driver.find_elements(
                                By.TAG_NAME, "script"
                            )
                            print(
                                f"  Debug: Total script tags on page: {len(all_scripts)}"
                            )
                            for i, s in enumerate(all_scripts[:5]):
                                s_type = s.get_attribute("type") or "text/javascript"
                                s_class = s.get_attribute("class") or ""
                                print(
                                    f"  Debug: Script {i}: type={s_type}, class={s_class}"
                                )
                        except:
                            pass

                # If no recipes found via JSON-LD, try WPRM DOM extraction
                if not recipe_data_list:
                    wprm_recipes = self.extract_wprm_from_dom()
                    if wprm_recipes:
                        recipe_data_list = wprm_recipes
                        if DEBUGEN:
                            print(
                                f"  Debug: Found {len(wprm_recipes)} recipes via WPRM DOM"
                            )

                new_recipes_found = 0
                for recipe_data in recipe_data_list:
                    if self.save_recipe(recipe_data, url):
                        new_recipes_found += 1

                if new_recipes_found > 0:
                    print(f"Found {new_recipes_found} recipe(s) on this page")
                else:
                    print(f"  No recipes found on this page")

                # Save progress
                self.progress["last_url"] = url
                self.progress["total_collected"] = len(self.collected_recipes)
                self.save_progress()

                # Return all links found on page for further crawling
                return self.find_links()

            except WebDriverException as e:
                error_msg = str(e)
                print(f"WebDriver error: {error_msg}")
                if (
                    "ERR_NAME_NOT_RESOLVED" in error_msg
                    or "ERR_CONNECTION" in error_msg
                ):
                    self.add_to_skiplist(url, error_msg)
                    return []
                if attempt >= self.max_retries:
                    return []
                time.sleep(3)
            except Exception as e:
                print(f"Unexpected error crawling {url}: {e}")
                if attempt >= self.max_retries:
                    return []
                time.sleep(3)

        return []

    def start_crawl(self):
        os.system("cls" if os.name == "nt" else "clear")
        print("=" * 60)
        print(f"{appname} v{verstr}")
        print("=" * 60)
        if self.full_run:
            print("Mode: Full Run")
        else:
            print("Mode: Resume Run")
        print(f"Starting URL: {BASE_URL}")
        print("Press 'x' + Enter to stop crawling")
        print("Or type 'get:<url>' to add a specific URL to the queue")
        print(f"Currently collected: {self.clean_collected()} recipes")
        print("=" * 60)

        self.input_thread = threading.Thread(
            target=self._input_thread_func, daemon=True
        )
        self.input_thread.start()

        try:
            self.setup_driver()
        except Exception as e:
            print(f"Failed to initialize driver: {e}")
            return

        if self.full_run:
            self.crawl_queue = [BASE_URL]
        else:
            resume_url = self.progress.get("last_url")
            self.crawl_queue = [resume_url] if resume_url else [BASE_URL]

        self.crawl_queue = [
            url
            for url in self.crawl_queue
            if url not in self.skipped_urls and not self.should_ignore(url)
        ]

        if not self.crawl_queue:
            print("Warning: Resume URL was skipped/ignored. Starting from BASE_URL.")
            self.crawl_queue = [BASE_URL]

        visited_this_session = set()
        pages_crawled = 0

        try:
            while self.crawl_queue and self.running:
                current_url = self.crawl_queue.pop(0)

                if self.check_user_input():
                    print("User requested shutdown. Saving progress...")
                    self.save_progress()
                    break

                if (
                    current_url in visited_this_session
                    or current_url in self.visited_urls
                ):
                    continue

                visited_this_session.add(current_url)
                pages_crawled += 1
                self.updateCrawl()
                print(f"\n--- Page {pages_crawled} ---")
                new_links = self.crawl_page(current_url)

                for link in new_links:
                    if (
                        link not in visited_this_session
                        and link not in self.visited_urls
                        and link not in self.crawl_queue
                        and link not in self.skipped_urls
                        and not self.should_ignore(link)
                    ):
                        self.crawl_queue.append(link)

                print(
                    f"Queue size: {len(self.crawl_queue)} | Visited: {len(self.visited_urls)} | Collected: {self.clean_collected()}"
                )
                time.sleep(1)

        except KeyboardInterrupt:
            print("\nShutdown requested. Saving progress...")
        finally:
            self.save_progress()
            self.shutdown()

        print(
            f"\nCrawl complete. Visited {len(self.visited_urls)} pages, collected {self.clean_collected()} recipes total."
        )

    def shutdown(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        self.save_progress()
        print("Crawler stopped.")

def main():
    parser = argparse.ArgumentParser(description="Crawl for recipes")
    parser.add_argument(
        "--fullrun",
        action="store_true",
        help="Start from beginning instead of resuming",
    )
    args = parser.parse_args()
    checkResume = Path("output/resume/resume.json")

    if not args.fullrun and not checkResume.is_file():
        args.fullrun = True

    crawler = RecipeCrawler(full_run=args.fullrun)

    try:
        crawler.start_crawl()
    except Exception as e:
        print(f"Crawler error: {e}")
        import traceback

        traceback.print_exc()
        crawler.shutdown()

if __name__ == "__main__":
    main()
