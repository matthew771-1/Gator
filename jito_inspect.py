import csv
import time
import requests
import math
import sys
from datetime import datetime
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.signature import Signature

# --- CONFIGURATION ---
RPC_HTTPS_URL = "https://mainnet.helius-rpc.com/?api-key=307e88f2-33c4-467c-968a-69f194fac6d8"

# FINGERPRINTS
KNOWN_PROGRAMS = {
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium V4",
    "CPMMoo8L3F4NbTneafuM5du9F8q1y5W5iL7p8qj9t3s": "Raydium CPMM",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter Agg",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "FybK4D4uxv721JjG9sr8zN6Q326qM1q3s5x1g5W3x7k": "Pump.fun",
    "MetaHGoeikm8MShfW381qZTk1V1YxQY2r5u2q5u2q5u": "Metaplex",
    "ComputeBudget111111111111111111111111111111": "Compute Budget",
    "11111111111111111111111111111111": "System Program",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcQb": "Memo Program",
    "E2uCGJ4TtYyKPGaK57UMfbs9sgaumwDEZF1aAY6fF3mS": "MEV Bot Proxy (E2uC)",
}

JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvTsszeoPhtUYj9rdag4djXeFQiDmJzTMX",
    "Cw8CFyM9FkoPhlTnrKMhTHqXheqJZNs4Fl31iWBP6UBu",
    "ADuUkR4ykG49feZ5bwhvq0A25pl1QMrBSnXRKKkeoX8q",
    "DttWaMuVvTiduZRNgLcGW9t66tePvm6znsc5tqQZFQk6",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnIzKZ6jJ",
    "DoPtqvycNsD9nuNSqMZ5J1GzV91qfQ4t7x1qF4aPiPce",
    "Ma1aHg66C61q1pF9n2c8bJqQ5tV4r4m1wW6d2t1p1X2"
]

JITO_HUBS = {
    "Tokyo": (35.6762, 139.6503),
    "NY": (40.7128, -74.0060),
    "Amsterdam": (52.3676, 4.9041),
    "Frankfurt": (50.1109, 8.6821),
    "SLC": (40.7608, -111.8910)
}

OUTPUT_FILE = "target_lock_v11.csv"

class JitoTargetLockV11:
    def __init__(self):
        self.client = Client(RPC_HTTPS_URL)
        self.cluster_map = {} 
        self.geo_cache = {}   
        self.processed_sigs = set()
        
        self.csv_file = open(OUTPUT_FILE, mode='a', newline='', encoding='utf-8')
        self.writer = csv.writer(self.csv_file)
        if self.csv_file.tell() == 0:
            self.writer.writerow(["Timestamp", "Target", "Programs", "Method_ID", "Full_Log", "Tip", "Hub", "Sig"])
            self.csv_file.flush()

        print("[*] TargetLock V11 (Profiler) Initialized. Mapping Network...")
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
            print(f"[*] Map Ready: {count} active validators.")
        except Exception as e:
            print(f"[!] Map update failed: {e}")

    def get_geoip(self, ip):
        if ip in self.geo_cache: return self.geo_cache[ip]
        try:
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=city,countryCode,lat,lon", timeout=3)
            if r.status_code == 200:
                data = r.json()
                val = (data.get('city', '?'), data.get('countryCode', '?'), data.get('lat', 0), data.get('lon', 0))
                self.geo_cache[ip] = val
                return val
        except:
            pass
        return ("Unknown", "??", 0, 0)

    def classify_hub(self, lat, lon):
        if lat == 0: return "Unknown"
        min_dist = float('inf')
        best_hub = "Unknown"
        for hub_name, (h_lat, h_lon) in JITO_HUBS.items():
            dist = math.sqrt((lat - h_lat)**2 + (lon - h_lon)**2)
            if dist < min_dist:
                min_dist = dist
                best_hub = hub_name
        return best_hub

    def detect_jito_tip(self, tx_value):
        try:
            meta = tx_value.transaction.meta
            static_keys = tx_value.transaction.transaction.message.account_keys
            
            loaded_keys = []
            if hasattr(meta, "loaded_addresses") and meta.loaded_addresses:
                loaded_keys = meta.loaded_addresses.writable + meta.loaded_addresses.readonly
            
            all_keys = list(static_keys) + loaded_keys
            
            pre_balances = meta.pre_balances
            post_balances = meta.post_balances
            
            for i, key in enumerate(all_keys):
                if i < len(pre_balances) and str(key) in JITO_TIP_ACCOUNTS:
                    tip = (post_balances[i] - pre_balances[i]) / 1000000000.0
                    return True, tip
            return False, 0.0
        except Exception as e:
            return False, 0.0

    def deep_decode(self, tx_value):
        invoked_programs = set()
        method_id = "N/A"
        
        try:
            msg = tx_value.transaction.transaction.message
            meta = tx_value.transaction.meta
            
            static_keys = msg.account_keys
            loaded_keys = []
            if hasattr(meta, "loaded_addresses") and meta.loaded_addresses:
                loaded_keys = meta.loaded_addresses.writable + meta.loaded_addresses.readonly
            
            all_keys = list(static_keys) + loaded_keys
            instructions = msg.instructions

            for i, ix in enumerate(instructions):
                prog_index = ix.program_id_index
                
                if prog_index < len(all_keys):
                    prog_id = str(all_keys[prog_index])
                    name = KNOWN_PROGRAMS.get(prog_id, f"Unknown ({prog_id[:4]}...)")
                    invoked_programs.add(name)
                    
                    if "Compute" not in name and "System" not in name and method_id == "N/A":
                        # ROBUST BYTES CONVERSION
                        try:
                            if isinstance(ix.data, bytes):
                                raw_data = ix.data
                            elif isinstance(ix.data, str):
                                raw_data = ix.data.encode('utf-8', errors='ignore')
                            else:
                                raw_data = bytes(ix.data)
                                
                            if len(raw_data) >= 8:
                                method_id = raw_data[:8].hex()
                            elif len(raw_data) >= 4:
                                method_id = raw_data[:4].hex()
                        except Exception:
                            method_id = "ParseErr"
                else:
                    invoked_programs.add(f"IndexError ({prog_index})")

        except Exception as e:
            return [f"Decode Error: {e}"], "Error"
        
        return list(invoked_programs), method_id

    # --- MODE 3: PROFILER LOGIC ---
    def run_profiler(self, wallet_str):
        print(f"\n[*] PROFILING BOT: {wallet_str}")
        print("[*] Scanning last 50 transactions to determine strategy...")
        
        target = Pubkey.from_string(wallet_str)
        stats = {"Total": 0, "Check/Bail": 0, "Trade/Success": 0, "Failures": 0}
        
        try:
            response = self.client.get_signatures_for_address(target, limit=50)
            
            print(f"\n{'SIG (Last 8)':<12} | {'METHOD / STRATEGY':<30} | {'CU':<8} | {'RESULT'}")
            print("-" * 75)

            for item in response.value:
                stats["Total"] += 1
                sig = str(item.signature)
                
                # Fetch TX
                tx = self.client.get_transaction(item.signature, max_supported_transaction_version=0)
                if not tx.value: continue

                # Extract Data
                cu = 0
                if tx.value.transaction.meta and tx.value.transaction.meta.compute_units_consumed:
                    cu = tx.value.transaction.meta.compute_units_consumed
                
                _, method_id = self.deep_decode(tx.value)
                
                # Classify
                strategy = "Unknown"
                if cu < 5000:
                    strategy = "Check & Bail (Spam)"
                    stats["Check/Bail"] += 1
                    status = "ABORT"
                elif item.err:
                    strategy = "Failed Trade"
                    stats["Failures"] += 1
                    status = "FAIL"
                else:
                    strategy = "Successful Swap"
                    stats["Trade/Success"] += 1
                    status = "PROFIT"

                print(f"{sig[:8]}...   | {strategy:<30} | {cu:<8} | {status} (Method: {method_id})")
                time.sleep(0.1)

            print("\n--- INTELLIGENCE REPORT ---")
            print(f"Target: {wallet_str}")
            print(f"Total Scanned: {stats['Total']}")
            print(f"Spam Rate (Checks): {(stats['Check/Bail']/stats['Total'])*100:.1f}%")
            print(f"Success Rate (Trades): {(stats['Trade/Success']/stats['Total'])*100:.1f}%")
            
        except Exception as e:
            print(f"[!] Profiler Error: {e}")

    def analyze_single_tx(self, sig_str):
        print(f"\n[*] Analyzing Transaction: {sig_str}")
        try:
            sig = Signature.from_string(sig_str)
            tx = self.client.get_transaction(sig, max_supported_transaction_version=0)
            if not tx.value:
                print("[!] Transaction too old or not found.")
                return

            self.print_analysis(tx.value, sig_str)
        except Exception as e:
            print(f"[!] Error: {e}")

    def run_wallet_monitor(self, wallet_str):
        print(f"\n[*] LOCKING ON WALLET: {wallet_str}")
        print("[*] Waiting for movement...")
        target = Pubkey.from_string(wallet_str)
        while True:
            try:
                response = self.client.get_signatures_for_address(target, limit=5)
                new_items = []
                for item in response.value:
                    if str(item.signature) not in self.processed_sigs:
                        self.processed_sigs.add(str(item.signature))
                        new_items.append(item)
                if len(self.processed_sigs) > 1000: self.processed_sigs.clear()
                for item in reversed(new_items):
                    tx = self.client.get_transaction(item.signature, max_supported_transaction_version=0)
                    if tx.value:
                        self.print_analysis(tx.value, str(item.signature))
                    time.sleep(1) 
                time.sleep(2) 
            except KeyboardInterrupt:
                return
            except Exception as e:
                time.sleep(2)

    def print_analysis(self, tx_value, sig_str):
        programs, method_id = self.deep_decode(tx_value)
        prog_str = ", ".join(programs)
        is_jito, tip_amount = self.detect_jito_tip(tx_value)
        jito_str = f"{tip_amount:.5f} SOL" if is_jito else "NO"

        logs = tx_value.transaction.meta.log_messages
        full_log = "No Logs"
        if logs:
            relevant = [l.replace("Program log: ", "").strip() for l in logs if "Program log:" in l or "Error" in l or "consumed" in l]
            if relevant: full_log = " | ".join(relevant[-2:])
            else: full_log = logs[-1] if logs else "Empty"

        slot = tx_value.slot
        hub_str = "Unknown"
        try:
            leader_list = self.client.get_slot_leaders(slot, 1).value
            if leader_list:
                leader_pub = str(leader_list[0])
                leader_ip = self.cluster_map.get(leader_pub, None)
                if leader_ip:
                    city, country, lat, lon = self.get_geoip(leader_ip)
                    hub_str = f"{self.classify_hub(lat, lon)} ({country})"
                else:
                    hub_str = "Unmapped Node"
        except:
            pass

        print("-" * 60)
        print(f"Signature: {sig_str}")
        print(f"EXECUTION: {prog_str}")
        print(f"METHOD ID: {method_id}")
        print(f"FULL LOG:  {full_log}")
        print(f"JITO TIP:  {jito_str}")
        print(f"VALIDATOR: {hub_str}")
        print("-" * 60)
        self.writer.writerow([datetime.now().strftime("%H:%M:%S"), "Target", prog_str, method_id, full_log, jito_str, hub_str, sig_str])
        self.csv_file.flush()

if __name__ == "__main__":
    lock = JitoTargetLockV11()
    
    print("\n--- JITO TARGET LOCK V11 (PROFILER) ---")
    print("1. Monitor a Wallet (Real-Time)")
    print("2. Analyze a Transaction Signature")
    print("3. Profile a Bot (History Scan)")
    choice = input("Select Mode (1, 2, or 3): ")

    if choice == "1":
        target = input("Enter Wallet Address: ").strip()
        if target: lock.run_wallet_monitor(target)
    elif choice == "2":
        target = input("Enter Transaction Signature: ").strip()
        if target: lock.analyze_single_tx(target)
    elif choice == "3":
        target = input("Enter Wallet Address: ").strip()
        if target: lock.run_profiler(target)