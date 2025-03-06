import asyncio
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.lines import Line2D
import networkx as nx
import numpy as np
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from urllib.parse import quote_plus
import os
from dotenv import load_dotenv
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.patches import FancyArrowPatch
import matplotlib as mpl
from PIL import Image
import io
import base64
import time
import math
import random
import cairo
import matplotlib
matplotlib.use("Agg")

# Load environment variables and MongoDB credentials
load_dotenv()
MONGO_USERNAME = os.getenv("MONGO_USERNAME")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST")
DATABASE_NAME = os.getenv("DATABASE_NAME") or "test_database"

encoded_username = quote_plus(MONGO_USERNAME) if MONGO_USERNAME else ""
encoded_password = quote_plus(MONGO_PASSWORD) if MONGO_PASSWORD else ""
MONGO_URI = f"mongodb+srv://{encoded_username}:{encoded_password}@{MONGO_HOST}/?retryWrites=true&w=majority" if MONGO_HOST else "mongodb://localhost:27017"

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
    """Convert SVG string to matplotlib image"""
    # Create a simple colored square as a fallback
    img = np.ones((20, 20, 4))
    img[:, :, 0] = 0.2  # Red channel
    img[:, :, 1] = 0.4  # Green channel
    img[:, :, 2] = 0.6  # Blue channel
    
    try:
        # Try using cairosvg if available
        try:
            import cairosvg
            png_data = cairosvg.svg2png(bytestring=svg_str.encode())
            img = plt.imread(io.BytesIO(png_data))
        except ImportError:
            pass
    except Exception as e:
        print(f"Error converting SVG to image: {e}")
    
    return OffsetImage(img, zoom=size)

# Custom animated arrow for transfers
class AnimatedArrow(FancyArrowPatch):
    def __init__(self, path, *args, **kwargs):
        self.path = path
        self.current_position = 0
        self.speed = kwargs.pop('speed', 0.05)  # Animation speed
        self.product = kwargs.pop('product', '')
        self.quantity = kwargs.pop('quantity', '')
        super().__init__((0, 0), (0, 0), *args, **kwargs)
        
    def draw(self, renderer):
        # Calculate current position along the path
        path_length = len(self.path)
        if path_length > 1:
            idx = int(self.current_position * (path_length - 1))
            idx = min(idx, path_length - 2)  # Ensure we don't exceed path bounds
            
            # Set arrow start and end points
            start_point = self.path[idx]
            end_point = self.path[idx + 1]
            self.set_positions(start_point, end_point)
            
            # Update position for next frame
            self.current_position += self.speed
            if self.current_position > 1:
                self.current_position = 0  # Reset position for continuous animation
        
        super().draw(renderer)

# Set up a dark theme for visualization
plt.style.use('dark_background')
mpl.rcParams['figure.facecolor'] = '#121212'
mpl.rcParams['axes.facecolor'] = '#121212'
mpl.rcParams['text.color'] = 'white'
mpl.rcParams['axes.labelcolor'] = 'white'
mpl.rcParams['xtick.color'] = 'white'
mpl.rcParams['ytick.color'] = 'white'

# Define a class for the animated visualization
class TransferVisualizer:
    def __init__(self):
        # Initialize MongoDB client
        try:
            self.client = AsyncIOMotorClient(MONGO_URI)
            self.db = self.client[DATABASE_NAME]
            print(f"Connected to MongoDB database: {DATABASE_NAME}")
        except Exception as e:
            print(f"Error connecting to MongoDB: {e}")
            self.client = None
            self.db = None
            
        self.fig, self.ax = plt.subplots(figsize=(16, 10), facecolor='#121212')
        self.G = nx.DiGraph()
        self.pos = None
        self.arrows = []
        self.node_colors = {}
        self.last_check_time = datetime.now() - timedelta(minutes=10)  # Start by fetching data from 10 minutes ago
        self.animation = None
        self.transfers_in_progress = []
        self.update_lock = asyncio.Lock()  # Add lock to prevent concurrent updates
        
        # Event types to colors mapping
        self.event_colors = {
            "transfer_initiated": "#3498DB",  # Blue
            "transfer_in_progress": "#F39C12",  # Orange
            "transfer_completed": "#2ECC71",  # Green
            "transfer_failed": "#E74C3C",  # Red
            "default": "#9B59B6"  # Purple for unknown events
        }
        
        # Product types to icons mapping (you can expand this)
        self.product_icons = {
            "default": create_warehouse_icon("#2C3E50")
        }
    
    async def get_recent_events(self):
        """Fetches trace events since the last check time"""
        if self.db is None:
            print("Database connection not available")
            return []
            
        try:
            query = {"timestamp": {"$gt": self.last_check_time}}
            # Print the query for debugging
            print(f"Fetching events with query: {query}")
            
            # List collection names for debugging
            collections = await self.db.list_collection_names()
            print(f"Available collections: {collections}")
            
            if 'transfer_trace' not in collections:
                print("Warning: transfer_trace collection does not exist")
                # Try to create a test document if collection doesn't exist
                try:
                    await self.db.transfer_trace.insert_one({
                        "from": "test_source",
                        "to": "test_destination",
                        "event": "transfer_initiated",
                        "product_field": "test_product",
                        "quantity": "10",
                        "timestamp": datetime.now()
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
        """Fetches all transfer trace events for initial setup"""
        if self.db is None:
            print("Database connection not available")
            return []
            
        try:
            # List collection names for debugging
            collections = await self.db.list_collection_names()
            print(f"Available collections: {collections}")
            
            if 'transfer_trace' not in collections:
                print("Warning: transfer_trace collection does not exist")
                # Try to create a test document for visualization
                try:
                    # Insert some test documents if no data exists
                    test_data = [
                        {
                            "from": "Warehouse A",
                            "to": "Store 1",
                            "event": "transfer_completed",
                            "product_field": "Product X",
                            "quantity": "100",
                            "timestamp": datetime.now() - timedelta(hours=2)
                        },
                        {
                            "from": "Warehouse B",
                            "to": "Store 2",
                            "event": "transfer_in_progress",
                            "product_field": "Product Y",
                            "quantity": "50",
                            "timestamp": datetime.now() - timedelta(hours=1)
                        },
                        {
                            "from": "Warehouse A",
                            "to": "Store 3",
                            "event": "transfer_initiated",
                            "product_field": "Product Z",
                            "quantity": "75",
                            "timestamp": datetime.now() - timedelta(minutes=30)
                        }
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
        """Updates the graph with new events"""
        for event in events:
            source = event.get("from")
            destination = event.get("to")
            event_type = event.get("event", "default")
            product_field = event.get("product_field", "unknown")
            quantity = event.get("quantity", "0")
            
            # Add nodes if they don't exist
            if source and source not in self.G:
                self.G.add_node(source)
                self.node_colors[source] = self.random_pastel_color()
            
            if destination and destination not in self.G:
                self.G.add_node(destination)
                self.node_colors[destination] = self.random_pastel_color()
            
            # Add the edge if both nodes are present
            if source and destination:
                self.G.add_edge(source, destination, 
                               event_type=event_type, 
                               product=product_field, 
                               quantity=quantity,
                               timestamp=event.get("timestamp"))
                
                # Add to active transfers if it's a new or in-progress transfer
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
        """Create a curved path between nodes for smooth animation"""
        if not self.pos or source not in self.pos or destination not in self.pos:
            return [(0, 0), (0, 0)]
            
        start = self.pos[source]
        end = self.pos[destination]
        
        # Create a curved path with several points
        num_points = 50
        path = []
        
        # Calculate control point for the curve (perpendicular to the line)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.sqrt(dx*dx + dy*dy)
        
        if length < 1e-6:  # Handle case when points are too close
            return [start, end]
            
        # Make the curve proportional to the distance
        curve_height = length * 0.2
        
        # Control point perpendicular to the line
        control_x = (start[0] + end[0]) / 2 - dy * curve_height / length
        control_y = (start[1] + end[1]) / 2 + dx * curve_height / length
        
        # Create Bezier curve points
        for i in range(num_points):
            t = i / (num_points - 1)
            # Quadratic Bezier formula
            x = (1-t)**2 * start[0] + 2*(1-t)*t * control_x + t**2 * end[0]
            y = (1-t)**2 * start[1] + 2*(1-t)*t * control_y + t**2 * end[1]
            path.append((x, y))
            
        return path
    
    def random_pastel_color(self):
        """Generate a random pastel color for nodes"""
        h = random.random()  # Hue value between 0 and 1
        s = 0.5  # Saturation - not too gray, not too vivid
        l = 0.7  # Lightness - pastel colors are lighter
        r, g, b = [int(x * 255) for x in self.hsl_to_rgb(h, s, l)]
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def hsl_to_rgb(self, h, s, l):
        """Convert HSL color to RGB"""
        if s == 0:
            r = g = b = l
        else:
            def hue_to_rgb(p, q, t):
                if t < 0: t += 1
                if t > 1: t -= 1
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1/3)
        
        return r, g, b
    
    def clear_visualization(self):
        """Clears the current visualization for redrawing"""
        self.ax.clear()
        self.arrows = []
    
    def draw_static_elements(self):
        """Draws the static elements of the graph - nodes and edges"""
        if not self.G.nodes():
            self.ax.text(0.5, 0.5, "No transfer events found in the database", 
                        ha='center', va='center', fontsize=14)
            return
            
        # Calculate layout if needed
        if not self.pos or len(self.pos) != len(self.G.nodes()):
            try:
                self.pos = nx.spring_layout(self.G, k=0.5, iterations=100)
            except Exception as e:
                print(f"Error calculating layout: {e}")
                return
        
        # Draw edges with gradient colors
        try:
            for u, v, data in self.G.edges(data=True):
                edge_color = self.event_colors.get(data.get("event_type", "default"), self.event_colors["default"])
                nx.draw_networkx_edges(self.G, self.pos, edgelist=[(u, v)], 
                                      width=1.5, alpha=0.4, edge_color=edge_color, 
                                      connectionstyle="arc3,rad=0.2")
        except Exception as e:
            print(f"Error drawing edges: {e}")
        
        # Draw nodes with custom icons
        try:
            for node in self.G.nodes():
                color = self.node_colors.get(node, "#3498DB")
                
                # Create an icon with glow effect
                icon = svg_to_image(create_warehouse_icon(color), size=0.15)
                if node in self.pos:  # Check if node position exists
                    ab = AnnotationBbox(icon, self.pos[node], frameon=False)
                    self.ax.add_artist(ab)
                    
                    # Add node labels with a modern look
                    self.ax.text(self.pos[node][0], self.pos[node][1] - 0.1, str(node),
                                fontsize=10, ha='center', color="white",
                                bbox=dict(boxstyle="round,pad=0.3", facecolor='black', alpha=0.7,
                                          edgecolor=color, linewidth=2))
        except Exception as e:
            print(f"Error drawing nodes: {e}")
        
        # Add title with timestamp
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ax.set_title(f"Real-Time Database Transfer Visualization\n{now}", fontsize=16)
        self.ax.set_axis_off()
        
        # Add legend for event types
        try:
            legend_elements = [Line2D([0], [0], color=color, lw=4, label=event_type.replace('_', ' ').title())
                             for event_type, color in self.event_colors.items()]
            self.ax.legend(handles=legend_elements, loc='upper right', frameon=True, 
                          facecolor='black', edgecolor='gray', framealpha=0.7)
        except Exception as e:
            print(f"Error creating legend: {e}")
    
    def update_animations(self):
        """Updates and draws the animated elements"""
        # Remove completed transfers
        current_time = time.time()
        active_transfers = []
        
        try:
            for transfer in self.transfers_in_progress:
                # Transfers last about 5 seconds in the visualization
                if current_time - transfer["start_time"] < 5:
                    active_transfers.append(transfer)
                    
                    # Create or update the animated arrow
                    color = self.event_colors.get(transfer["event_type"], self.event_colors["default"])
                    
                    # Create dynamic particles along the path
                    path = transfer["path"]
                    if path and len(path) > 1:
                        # Calculate positions for multiple particles
                        num_particles = 3
                        for i in range(num_particles):
                            # Stagger the particles
                            position = (current_time - transfer["start_time"]) / 5 + i / num_particles
                            position = position % 1.0
                            
                            if position < 1.0:
                                idx = int(position * (len(path) - 1))
                                idx = min(idx, len(path) - 2)
                                
                                # Draw a circular marker at the calculated position
                                if 0 <= idx < len(path):  # Guard against index errors
                                    x = path[idx][0]
                                    y = path[idx][1]
                                    circle = plt.Circle((x, y), 0.02, color=color, alpha=0.8)
                                    self.ax.add_patch(circle)
                    
                    # Add transfer info as a moving label
                    if path and len(path) > 1:
                        position = ((current_time - transfer["start_time"]) / 5) % 1.0
                        idx = int(position * (len(path) - 1))
                        idx = min(idx, len(path) - 2)
                        
                        if 0 <= idx < len(path):  # Guard against index errors
                            x, y = path[idx]
                            label = f"{transfer['product']}: {transfer['quantity']}"
                            self.ax.text(x, y+0.05, label, fontsize=8, ha='center',
                                        bbox=dict(boxstyle="round,pad=0.1", facecolor='black', alpha=0.7,
                                                 edgecolor=color, linewidth=1))
        except Exception as e:
            print(f"Error updating animations: {e}")
        
        # Update the active transfers list
        self.transfers_in_progress = active_transfers
    
    # Fixed update method that's compatible with matplotlib animation
    def update_frame(self, frame):
        """Non-async update method for FuncAnimation"""
        # Return a static set of artists initially
        if not hasattr(self, 'artists_cache'):
            self.artists_cache = []
            
        return self.artists_cache
        
    async def async_update(self):
        """Background task to update data from MongoDB"""
        while True:
            try:
                async with self.update_lock:
                    # Get recent events from database
                    events = await self.get_recent_events()
                    
                    if events:
                        print(f"Retrieved {len(events)} new events")
                        self.update_graph(events)
                
                # Schedule a redraw
                self.schedule_redraw()
                
                # Wait before next update
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"Error in async_update: {e}")
                await asyncio.sleep(5)  # Wait longer after an error
    
    def schedule_redraw(self):
        """Schedule a redraw on the main thread"""
        # This is called from the asyncio thread, so we need to use the main thread to redraw
        self.fig.canvas.draw_idle()
    
    def redraw(self):
        """Redraw the visualization (called by the animation)"""
        try:
            self.clear_visualization()
            self.draw_static_elements()
            self.update_animations()
            
            # Cache all artists for the animation
            self.artists_cache = self.ax.artists + self.ax.lines + self.ax.patches + self.ax.texts
            return self.artists_cache
        except Exception as e:
            print(f"Error in redraw: {e}")
            return []
    
    async def initialize(self):
        """Initialize the visualization with all existing data"""
        try:
            # Add additional debug information
            print("Starting initialization...")
            print(f"MongoDB URI: {MONGO_URI}")
            print(f"Database name: {DATABASE_NAME}")
            
            # Check database connection
            if self.db is None:
                print("Database connection not available")
                self.ax.text(0.5, 0.5, "Database connection not available", 
                           ha='center', va='center', fontsize=14)
                return
                
            # Try to access database info for diagnostic purposes
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
                           ha='center', va='center', fontsize=14)
                
                # Create mock data for visualization testing if needed
                print("Creating mock data for visualization testing...")
                mock_events = [
                    {
                        "from": "Warehouse A",
                        "to": "Store 1",
                        "event": "transfer_completed",
                        "product_field": "Product X",
                        "quantity": "100",
                        "timestamp": datetime.now() - timedelta(hours=2)
                    },
                    {
                        "from": "Warehouse B",
                        "to": "Store 2",
                        "event": "transfer_in_progress",
                        "product_field": "Product Y",
                        "quantity": "50",
                        "timestamp": datetime.now() - timedelta(hours=1)
                    }
                ]
                self.update_graph(mock_events)
                self.draw_static_elements()
                
        except Exception as e:
            print(f"Error initializing: {e}")
            self.ax.text(0.5, 0.5, f"Error initializing visualization: {e}", 
                        ha='center', va='center', fontsize=14)
    
    async def start_animation(self):
        """Start the animation loop"""
        # Initialize the visualization
        await self.initialize()
        
        # Create a better animation system that works with asyncio
        def animation_step(frame):
            # This function runs in the main thread
            return self.redraw()
        
        # Start the asyncio background task for data updates
        asyncio.create_task(self.async_update())
        
        # Create animation with standard update function
        self.animation = animation.FuncAnimation(
            self.fig, 
            animation_step,  # This is a normal function, not a coroutine
            interval=200,    # Update every 200ms
            blit=True,
            save_count=50    # How many frames to keep
        )
        
        plt.tight_layout()
        plt.show()

async def main():
    visualizer = TransferVisualizer()
    await visualizer.start_animation()

if __name__ == "__main__":
    try:
        # Use the appropriate event loop based on platform
        if os.name == 'nt':  # Windows
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Animation stopped by user")
    except Exception as e:
        print(f"Error running visualization: {e}")
