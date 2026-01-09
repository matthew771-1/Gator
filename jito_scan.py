import asyncio
import json
import csv
import math
import requests
import os
import sys
from datetime import datetime
from solana.rpc.websocket_api import connect
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.rpc.config import RpcTransactionLogsFilterMentions
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
if not HELIUS_API_KEY:
    print("[!] ERROR: HELIUS_API_KEY not found in environment variables")
    print("[!] Create a .env file (UTF-8) or set HELIUS_API_KEY in your shell.")
    sys.exit(1)

RPC_HTTPS_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
RPC_WSS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

JITO_HUBS = {
    "Tokyo (Asia)": (35.6762, 139.6503),
    "New York (US-East)": (40.7128, -74.0060),
    "Amsterdam (EU-West)": (52.3676, 4.9041),
    "Frankfurt (EU-Central)": (50.1109, 8.6821),
    "Salt Lake City (US-West)": (40.7608, -111.8910)
}

# We watch the main Tip Account
TARGET_ACCOUNT = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"

class JitoHunterDebug:
    def __init__(self):
        self.client = Client(RPC_HTTPS_URL)
        self.cluster_map = {} 
        self.geo_cache = {}   
        print("[*] Initializing... Mapping Network Nodes (Please Wait)...")
        self.refresh_cluster_nodes()

    def refresh_cluster_nodes(self):
        try:
            nodes = self.client.get_cluster_nodes()
            count = 0
            for node in nodes.value:
                ip_port = node.tpu if node.tpu else node.gossip
                if ip_port:
                    self.cluster_map[str(node.pubkey)] = ip_port.split(':')[0]
                    count += 1
            print(f"[*] Map Ready: {count} active validators tracked.")
        except Exception as e:
            print(f"[!] Map update failed: {e}")

    def get_geoip(self, ip):
        if ip in self.geo_cache: return self.geo_cache[ip]
        try:
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=lat,lon,city,countryCode", timeout=2)
            if r.status_code == 200:
                data = r.json()
                val = (data.get('city', '?'), data.get('countryCode', '?'), data.get('lat', 0), data.get('lon', 0))
                self.geo_cache[ip] = val
                return val
        except:
            pass
        return ("Unknown", "??", 0, 0)

    def classify_hub(self, lat, lon):
        if lat == 0 and lon == 0: return "Unknown"
        best_hub = "Unknown"
        min_dist = float('inf')
        for hub_name, (h_lat, h_lon) in JITO_HUBS.items():
            dist = math.sqrt((lat - h_lat)**2 + (lon - h_lon)**2)
            if dist < min_dist:
                min_dist = dist
                best_hub = hub_name
        return best_hub

    async def run(self):
        target = Pubkey.from_string(TARGET_ACCOUNT)
        print(f"[*] Connecting to Stream for Account: {TARGET_ACCOUNT[:8]}...")
        
        async with connect(RPC_WSS_URL) as websocket:
            await websocket.logs_subscribe(
                filter_=RpcTransactionLogsFilterMentions(target),
                commitment="confirmed"
            )
            print("[*] Connection Established. Waiting for data...")

            while True:
                # 1. Receive Raw Data
                try:
                    messages = await websocket.recv()
                except Exception as e:
                    print(f"[!] Socket Error: {e}")
                    continue

                # 2. Iterate (Handling the 'list' update from Solders)
                for item in messages:
                    # Print a 'dot' for every raw packet so you know it's alive
                    print(".", end="", flush=True) 
                    
                    try:
                        # Convert to Dict
                        if hasattr(item, 'to_json'):
                            payload = json.loads(item.to_json())
                        else:
                            payload = item
                        
                        # Process
                        if "method" in payload and "result" in payload["params"]:
                             asyncio.create_task(self.process_bundle(payload["params"]["result"]))
                    except Exception as e:
                        print(f"\n[!] Parse Error: {e}")

    async def process_bundle(self, data):
        try:
            # Add delay to let RPC index the block
            await asyncio.sleep(2)

            sig = data["value"]["signature"]
            slot = data["context"]["slot"]
            
            # Print immediately that we found something
            print(f"\n[+] Analyzing Bundle: {sig[:8]}... (Slot {slot})")

            # 1. Get Leader
            try:
                leader_pub = str(self.client.get_slot_leader(slot=slot).value)
            except Exception as e:
                print(f"    [!] Leader Lookup Failed: {e}")
                return

            # 2. Geolocate
            leader_ip = self.cluster_map.get(leader_pub, None)
            if leader_ip:
                city, country, lat, lon = self.get_geoip(leader_ip)
                hub = self.classify_hub(lat, lon)
                print(f"    -> Location: {city}, {country} ({hub})")
            else:
                print(f"    -> Leader IP Not Found in Map")

        except Exception as e:
            print(f"    [!] Processing Error: {e}")

if __name__ == "__main__":
    hunter = JitoHunterDebug()
    try:
        asyncio.run(hunter.run())
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")