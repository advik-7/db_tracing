import asyncio
import threading
import io
import os
import time
import math
import random
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.lines import Line2D
import networkx as nx
import numpy as np
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.patches import FancyArrowPatch
import matplotlib as mpl
from PIL import Image
import cairosvg  # For SVG conversion

from flask import Flask, send_file

# Load environment variables and MongoDB credentials
load_dotenv()
MONGO_USERNAME = os.getenv("MONGO_USERNAME")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST")
DATABASE_NAME = os.getenv("DATABASE_NAME") or "test_database"

encoded_username = quote_plus(MONGO_USERNAME) if MONGO_USERNAME else ""
encoded_password = quote_plus(MONGO_PASSWORD) if MONGO_PASSWORD else ""
MONGO_URI = (
    f"mongodb+srv://{encoded_username}:{encoded_password}@{MONGO_HOST}/?retryWrites=true&w=majority"
    if MONGO_HOST
    else "mongodb://localhost:27017"
)

# Create SVG warehouse icon
def create_warehouse_icon(color="#2C3E50"):
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
        <rect x="15" y="40" width="70" height="50" fill="{color}" />
        <polygon points="15,40 50,10 85,40" fill="{color}" />
        <rect x="40" y="60" width="20" height="30" fill="#D0D3D4" />
        <rect x="20" y="45" width="15" height="15" fill="#D0D3D4" />
        <rect x="65" y="45" width="15" height="15" fill="#D0D3D4" />
    </svg>
    """
    return svg

def svg_to_image(svg_str, size=0.1):
    """Convert SVG string to a matplotlib image."""
    # Fallback: a simple colored square
    img = np.ones((20, 20, 4))
    img[:, :, 0] = 0.2
    img[:, :, 1] = 0.4
    img[:, :, 2] = 0.6
    try:
        png_data = cairosvg.svg2png(bytestring=svg_str.encode())
        img = plt.imread(io.BytesIO(png_data))
    except Exception as e:
        print(f"Error converting SVG: {e}")
    return OffsetImage(img, zoom=size)

# (Optional) Custom animated arrow class is kept for completeness.
class AnimatedArrow(FancyArrowPatch):
    def __init__(self, path, *args, **kwargs):
        self.path = path
        self.current_position = 0
        self.speed = kwargs.pop("speed", 0.05)
        self.product = kwargs.pop("product", "")
        self.quantity = kwargs.pop("quantity", "")
        super().__init__((0, 0), (0, 0), *args, **kwargs)

    def draw(self, renderer):
        path_length = len(self.path)
        if path_length > 1:
            idx = int(self.current_position * (path_length - 1))
            idx = min(idx, path_length - 2)
            start_point = self.path[idx]
            end_point = self.path[idx + 1]
            self.set_positions(start_point, end_point)
            self.current_position += self.speed
            if self.current_position > 1:
                self.current_position = 0
        super().draw(renderer)

# Set up a dark theme for visualization
plt.style.use("dark_background")
mpl.rcParams["figure.facecolor"] = "#121212"
mpl.rcParams["axes.facecolor"] = "#121212"
mpl.rcParams["text.color"] = "white"
mpl.rcParams["axes.labelcolor"] = "white"
mpl.rcParams["xtick.color"] = "white"
mpl.rcParams["ytick.color"] = "white"

class TransferVisualizer:
    def __init__(self):
        try:
            self.client = AsyncIOMotorClient(MONGO_URI)
            self.db = self.client[DATABASE_NAME]
            print(f"Connected to MongoDB database: {DATABASE_NAME}")
        except Exception as e:
            print(f"Error connecting to MongoDB: {e}")
            self.client = None
            self.db = None

        self.fig, self.ax = plt.subplots(figsize=(16, 10), facecolor="#121212")
        self.G = nx.DiGraph()
        self.pos = None
        self.node_colors = {}
        self.last_check_time = datetime.now() - timedelta(minutes=10)
        self.transfers_in_progress = []
        self.update_lock = asyncio.Lock()

        self.event_colors = {
            "transfer_initiated": "#3498DB",
            "transfer_in_progress": "#F39C12",
            "transfer_completed": "#2ECC71",
            "transfer_failed": "#E74C3C",
            "default": "#9B59B6",
        }
        self.product_icons = {
            "default": create_warehouse_icon("#2C3E50")
        }

    async def get_recent_events(self):
        if self.db is None:
            print("Database connection not available")
            return []
        try:
            query = {"timestamp": {"$gt": self.last_check_time}}
            print(f"Fetching events with query: {query}")
            collections = await self.db.list_collection_names()
            print(f"Available collections: {collections}")
            if "transfer_trace" not in collections:
                print("Warning: transfer_trace collection does not exist")
                try:
                    await self.db.transfer_trace.insert_one({
                        "from": "test_source",
                        "to": "test_destination",
                        "event": "transfer_initiated",
                        "product_field": "test_product",
                        "quantity": "10",
                        "timestamp": datetime.now(),
                    })
                    print("Created test document in transfer_trace collection")
                except Exception as e:
                    print(f"Error creating test document: {e}")
            events = await self.db.transfer_trace.find(query).sort("timestamp", 1).to_list(length=None)
            print(f"Found {len(events)} recent events")
            if events:
                self.last_check_time = events[-1]["timestamp"]
            return events
        except Exception as e:
            print(f"Error fetching recent events: {e}")
            return []

    async def get_all_events(self):
        if self.db is None:
            print("Database connection not available")
            return []
        try:
            collections = await self.db.list_collection_names()
            print(f"Available collections: {collections}")
            if "transfer_trace" not in collections:
                print("Warning: transfer_trace collection does not exist")
                try:
                    test_data = [
                        {
                            "from": "Warehouse A",
                            "to": "Store 1",
                            "event": "transfer_completed",
                            "product_field": "Product X",
                            "quantity": "100",
                            "timestamp": datetime.now() - timedelta(hours=2),
                        },
                        {
                            "from": "Warehouse B",
                            "to": "Store 2",
                            "event": "transfer_in_progress",
                            "product_field": "Product Y",
                            "quantity": "50",
                            "timestamp": datetime.now() - timedelta(hours=1),
                        },
                        {
                            "from": "Warehouse A",
                            "to": "Store 3",
                            "event": "transfer_initiated",
                            "product_field": "Product Z",
                            "quantity": "75",
                            "timestamp": datetime.now() - timedelta(minutes=30),
                        },
                    ]
                    await self.db.transfer_trace.insert_many(test_data)
                    print("Created test documents in transfer_trace collection")
                except Exception as e:
                    print(f"Error creating test documents: {e}")
            events = await self.db.transfer_trace.find().sort("timestamp", 1).to_list(length=None)
            print(f"Found {len(events)} total events")
            if events:
                self.last_check_time = events[-1]["timestamp"]
            return events
        except Exception as e:
            print(f"Error fetching all events: {e}")
            return []

    def update_graph(self, events):
        for event in events:
            source = event.get("from")
            destination = event.get("to")
            event_type = event.get("event", "default")
            product_field = event.get("product_field", "unknown")
            quantity = event.get("quantity", "0")
            if source and source not in self.G:
                self.G.add_node(source)
                self.node_colors[source] = self.random_pastel_color()
            if destination and destination not in self.G:
                self.G.add_node(destination)
                self.node_colors[destination] = self.random_pastel_color()
            if source and destination:
                self.G.add_edge(source, destination,
                                event_type=event_type,
                                product=product_field,
                                quantity=quantity,
                                timestamp=event.get("timestamp"))
                if event_type in ["transfer_initiated", "transfer_in_progress"]:
                    self.transfers_in_progress.append({
                        "source": source,
                        "destination": destination,
                        "product": product_field,
                        "quantity": quantity,
                        "event_type": event_type,
                        "start_time": time.time(),
                        "path": self.get_edge_path(source, destination)
                    })

    def get_edge_path(self, source, destination):
        if not self.pos or source not in self.pos or destination not in self.pos:
            return [(0, 0), (0, 0)]
        start = self.pos[source]
        end = self.pos[destination]
        num_points = 50
        path = []
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-6:
            return [start, end]
        curve_height = length * 0.2
        control_x = (start[0] + end[0]) / 2 - dy * curve_height / length
        control_y = (start[1] + end[1]) / 2 + dx * curve_height / length
        for i in range(num_points):
            t = i / (num_points - 1)
            x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control_x + t ** 2 * end[0]
            y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control_y + t ** 2 * end[1]
            path.append((x, y))
        return path

    def random_pastel_color(self):
        h = random.random()
        s = 0.5
        l = 0.7
        r, g, b = [int(x * 255) for x in self.hsl_to_rgb(h, s, l)]
        return f"#{r:02x}{g:02x}{b:02x}"

    def hsl_to_rgb(self, h, s, l):
        if s == 0:
            r = g = b = l
        else:
            def hue_to_rgb(p, q, t):
                if t < 0:
                    t += 1
                if t > 1:
                    t -= 1
                if t < 1/6:
                    return p + (q - p) * 6 * t
                if t < 1/2:
                    return q
                if t < 2/3:
                    return p + (q - p) * (2/3 - t) * 6
                return p
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1/3)
        return r, g, b

    def clear_visualization(self):
        self.ax.clear()
        self.G.clear()  # Optionally reset the graph
        self.transfers_in_progress = []

    def draw_static_elements(self):
        if not self.G.nodes():
            self.ax.text(0.5, 0.5, "No transfer events found in the database",
                         ha="center", va="center", fontsize=14)
            return
        if not self.pos or len(self.pos) != len(self.G.nodes()):
            try:
                self.pos = nx.spring_layout(self.G, k=0.5, iterations=100)
            except Exception as e:
                print(f"Error calculating layout: {e}")
                return
        try:
            for u, v, data in self.G.edges(data=True):
                edge_color = self.event_colors.get(data.get("event_type", "default"), self.event_colors["default"])
                nx.draw_networkx_edges(self.G, self.pos, edgelist=[(u, v)],
                                       width=1.5, alpha=0.4, edge_color=edge_color,
                                       connectionstyle="arc3,rad=0.2")
        except Exception as e:
            print(f"Error drawing edges: {e}")
        try:
            for node in self.G.nodes():
                color = self.node_colors.get(node, "#3498DB")
                icon = svg_to_image(create_warehouse_icon(color), size=0.15)
                if node in self.pos:
                    ab = AnnotationBbox(icon, self.pos[node], frameon=False)
                    self.ax.add_artist(ab)
                    self.ax.text(self.pos[node][0], self.pos[node][1] - 0.1, str(node),
                                 fontsize=10, ha="center", color="white",
                                 bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.7,
                                           edgecolor=color, linewidth=2))
        except Exception as e:
            print(f"Error drawing nodes: {e}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ax.set_title(f"Real-Time Database Transfer Visualization\n{now}", fontsize=16)
        self.ax.set_axis_off()
        try:
            legend_elements = [
                Line2D([0], [0], color=color, lw=4, label=event_type.replace('_', ' ').title())
                for event_type, color in self.event_colors.items()
            ]
            self.ax.legend(handles=legend_elements, loc="upper right", frameon=True,
                           facecolor="black", edgecolor="gray", framealpha=0.7)
        except Exception as e:
            print(f"Error creating legend: {e}")

    def update_animations(self):
        current_time = time.time()
        active_transfers = []
        try:
            for transfer in self.transfers_in_progress:
                if current_time - transfer["start_time"] < 5:
                    active_transfers.append(transfer)
                    color = self.event_colors.get(transfer["event_type"], self.event_colors["default"])
                    path = transfer["path"]
                    if path and len(path) > 1:
                        num_particles = 3
                        for i in range(num_particles):
                            position = (current_time - transfer["start_time"]) / 5 + i / num_particles
                            position %= 1.0
                            if position < 1.0:
                                idx = int(position * (len(path) - 1))
                                idx = min(idx, len(path) - 2)
                                if 0 <= idx < len(path):
                                    x = path[idx][0]
                                    y = path[idx][1]
                                    circle = plt.Circle((x, y), 0.02, color=color, alpha=0.8)
                                    self.ax.add_patch(circle)
                        if path and len(path) > 1:
                            position = ((current_time - transfer["start_time"]) / 5) % 1.0
                            idx = int(position * (len(path) - 1))
                            idx = min(idx, len(path) - 2)
                            if 0 <= idx < len(path):
                                x, y = path[idx]
                                label = f"{transfer['product']}: {transfer['quantity']}"
                                self.ax.text(x, y + 0.05, label, fontsize=8, ha="center",
                                             bbox=dict(boxstyle="round,pad=0.1", facecolor="black", alpha=0.7,
                                                       edgecolor=color, linewidth=1))
        except Exception as e:
            print(f"Error updating animations: {e}")
        self.transfers_in_progress = active_transfers

    def redraw(self):
        try:
            self.clear_visualization()
            self.draw_static_elements()
            self.update_animations()
            return self.ax.artists + self.ax.lines + self.ax.patches + self.ax.texts
        except Exception as e:
            print(f"Error in redraw: {e}")
            return []

    async def async_update(self):
        while True:
            try:
                async with self.update_lock:
                    events = await self.get_recent_events()
                    if events:
                        print(f"Retrieved {len(events)} new events")
                        self.update_graph(events)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error in async_update: {e}")
                await asyncio.sleep(5)

    async def initialize(self):
        try:
            print("Starting initialization...")
            print(f"MongoDB URI: {MONGO_URI}")
            print(f"Database name: {DATABASE_NAME}")
            if self.db is None:
                print("Database connection not available")
                self.ax.text(0.5, 0.5, "Database connection not available",
                             ha="center", va="center", fontsize=14)
                return
            try:
                server_info = await self.client.server_info()
                print(f"Connected to MongoDB version: {server_info.get('version', 'unknown')}")
            except Exception as e:
                print(f"Could not get server info: {e}")
            events = await self.get_all_events()
            if events:
                print(f"Retrieved {len(events)} initial events")
                self.update_graph(events)
                self.draw_static_elements()
            else:
                print("No events found in the database, or collection is empty")
                self.ax.text(0.5, 0.5, "No transfer events found in the database",
                             ha="center", va="center", fontsize=14)
                print("Creating mock data for visualization testing...")
                mock_events = [
                    {
                        "from": "Warehouse A",
                        "to": "Store 1",
                        "event": "transfer_completed",
                        "product_field": "Product X",
                        "quantity": "100",
                        "timestamp": datetime.now() - timedelta(hours=2),
                    },
                    {
                        "from": "Warehouse B",
                        "to": "Store 2",
                        "event": "transfer_in_progress",
                        "product_field": "Product Y",
                        "quantity": "50",
                        "timestamp": datetime.now() - timedelta(hours=1),
                    },
                ]
                self.update_graph(mock_events)
                self.draw_static_elements()
        except Exception as e:
            print(f"Error initializing: {e}")
            self.ax.text(0.5, 0.5, f"Error initializing visualization: {e}",
                         ha="center", va="center", fontsize=14)

# ----- Flask Web Service -----

app = Flask(__name__)

# Create a global instance of TransferVisualizer
visualizer = TransferVisualizer()

@app.route("/")
def index():
    # A simple HTML page that refreshes every 5 seconds to update the image.
    html = """
    <html>
      <head>
        <title>Real-Time Database Transfer Visualization</title>
        <meta http-equiv="refresh" content="5">
      </head>
      <body>
        <h1>Real-Time Database Transfer Visualization</h1>
        <img src="/image" alt="Visualization">
      </body>
    </html>
    """
    return html

@app.route("/image")
def image():
    # Redraw the current visualization and return it as a PNG image.
    visualizer.redraw()
    buf = io.BytesIO()
    visualizer.fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# ----- Start Background Async Loop -----
def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

background_loop = asyncio.new_event_loop()
t = threading.Thread(target=start_background_loop, args=(background_loop,), daemon=True)
t.start()

# Schedule initialization and the async_update task on the background loop.
asyncio.run_coroutine_threadsafe(visualizer.initialize(), background_loop)
asyncio.run_coroutine_threadsafe(visualizer.async_update(), background_loop)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
