#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║     ██████   █████  ████████  ██████  ██████                                  ║
║    ██       ██   ██    ██    ██    ██ ██   ██                                 ║
║    ██   ███ ███████    ██    ██    ██ ██████                                  ║
║    ██    ██ ██   ██    ██    ██    ██ ██   ██                                 ║
║     ██████  ██   ██    ██     ██████  ██   ██                                 ║
║                                                                               ║
║                      EVM OSINT SUITE v1.0                                     ║
║                                                                               ║
║  COMMANDS:                                                                    ║
║    python gator_evm.py profile <address>             - Profile a wallet       ║
║    python gator_evm.py connect <addr1> <addr2> ...   - Find connections       ║
║                                                                               ║
║  CHAINS: ethereum, base, arbitrum, optimism, polygon                          ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import argparse
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION - ADD YOUR API KEY HERE
# ═══════════════════════════════════════════════════════════════════════════════

ETHERSCAN_API_KEY = "YOUR_ETHERSCAN_API_KEY"

EXPLORER_APIS = {
    "ethereum": "https://api.etherscan.io/api",
    "base": "https://api.basescan.org/api",
    "arbitrum": "https://api.arbiscan.io/api",
    "optimism": "https://api-optimistic.etherscan.io/api",
    "polygon": "https://api.polygonscan.com/api",
}

EXPLORER_URLS = {
    "ethereum": "https://etherscan.io",
    "base": "https://basescan.org",
    "arbitrum": "https://arbiscan.io",
    "optimism": "https://optimistic.etherscan.io",
    "polygon": "https://polygonscan.com",
}

KNOWN_LABELS = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap Router",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch V5",
}


@dataclass
class ProfileProbabilities:
    bot: float = 0.0
    eu_trader: float = 0.0
    us_trader: float = 0.0
    asia_trader: float = 0.0
    retail_hobbyist: float = 0.0
    professional: float = 0.0
    whale: float = 0.0
    degen: float = 0.0
    mev_bot: float = 0.0
    privacy_user: float = 0.0
    
    def normalize(self):
        geo_total = self.eu_trader + self.us_trader + self.asia_trader
        if geo_total > 0:
            self.eu_trader = (self.eu_trader / geo_total) * 100
            self.us_trader = (self.us_trader / geo_total) * 100
            self.asia_trader = (self.asia_trader / geo_total) * 100


@dataclass
class SleepWindow:
    start_hour: int
    end_hour: int
    activity_during_sleep: int
    confidence: float


@dataclass
class WalletConnection:
    wallet_a: str
    wallet_b: str
    tx_count: int = 0
    total_value: float = 0.0
    first_interaction: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    tx_hashes: List[str] = field(default_factory=list)


def api_call(chain: str, params: dict):
    api_url = EXPLORER_APIS.get(chain, EXPLORER_APIS["ethereum"])
    params["apikey"] = ETHERSCAN_API_KEY
    try:
        response = requests.get(api_url, params=params, timeout=30)
        data = response.json()
        if data.get("status") == "1":
            return data.get("result")
        return None
    except:
        return None


def fetch_transactions(address: str, chain: str = "ethereum", limit: int = 100):
    params = {
        "module": "account", "action": "txlist", "address": address,
        "startblock": 0, "endblock": 99999999, "page": 1, "offset": limit, "sort": "desc"
    }
    return api_call(chain, params) or []


def get_label(address: str) -> str:
    return KNOWN_LABELS.get(address.lower(), address[:8] + "..." + address[-4:])


def classify_gas(gas: int) -> dict:
    if gas == 21000: return {"type": "ETH Transfer", "complexity": "simple"}
    elif gas <= 65000: return {"type": "ERC20 Transfer", "complexity": "simple"}
    elif gas <= 150000: return {"type": "Swap/Approve", "complexity": "moderate"}
    elif gas <= 300000: return {"type": "DEX Swap", "complexity": "complex"}
    elif gas <= 500000: return {"type": "Multi-hop", "complexity": "complex"}
    else: return {"type": "Complex/Mixer", "complexity": "heavy"}


def get_gas_color(gas: int) -> str:
    if gas <= 65000: return '#22c55e'
    elif gas <= 150000: return '#eab308'
    elif gas <= 300000: return '#f97316'
    else: return '#ef4444'


def get_gas_label(gas: float) -> str:
    if gas <= 65000: return 'Simple'
    elif gas <= 150000: return 'Moderate'
    elif gas <= 300000: return 'Complex'
    else: return 'Heavy'


def analyze_wallet(address: str, chain: str = "ethereum", limit: int = 100) -> pd.DataFrame:
    print(f"\n[*] Fetching {limit} transactions on {chain.upper()}...")
    txs = fetch_transactions(address, chain, limit)
    if not txs:
        return pd.DataFrame()
    
    print(f"[+] Found {len(txs)} transactions\n")
    transactions = []
    
    for idx, tx in enumerate(txs):
        bar = '█' * int((idx+1)/len(txs)*40) + '░' * (40-int((idx+1)/len(txs)*40))
        print(f"\r    [{bar}] {idx+1}/{len(txs)}", end="", flush=True)
        
        try:
            timestamp = int(tx.get("timeStamp", 0))
            if not timestamp: continue
            utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            gas_used = int(tx.get("gasUsed", 0))
            gas_price = int(tx.get("gasPrice", 0))
            value = int(tx.get("value", 0))
            
            transactions.append({
                "hash": tx.get("hash", ""),
                "timestamp": utc_time,
                "hour": utc_time.hour,
                "day_of_week": utc_time.weekday(),
                "gas_used": gas_used,
                "gas_price_gwei": gas_price / 1e9,
                "tx_fee_eth": (gas_used * gas_price) / 1e18,
                "value_eth": value / 1e18,
                "is_outgoing": tx.get("from", "").lower() == address.lower(),
                "is_contract": tx.get("input", "0x") != "0x",
                "success": tx.get("isError", "0") == "0",
                "tx_type": classify_gas(gas_used)["type"],
                "to": tx.get("to", ""),
                "from": tx.get("from", ""),
            })
        except: continue
    
    print(f"\n[+] Analyzed {len(transactions)} transactions\n")
    return pd.DataFrame(transactions)


def detect_sleep_window(hourly_counts: list) -> SleepWindow:
    min_sum, sleep_start = float('inf'), 0
    total_tx = sum(hourly_counts)
    for i in range(24):
        window_sum = sum(hourly_counts[(i + j) % 24] for j in range(6))
        if window_sum < min_sum:
            min_sum, sleep_start = window_sum, i
    confidence = max(0, min(100, (1 - (min_sum / total_tx if total_tx else 0) * 4) * 100))
    return SleepWindow(sleep_start, (sleep_start + 6) % 24, min_sum, confidence)


def calculate_probabilities(df: pd.DataFrame, hourly_counts: list, daily_counts: list, sleep: SleepWindow) -> ProfileProbabilities:
    probs = ProfileProbabilities()
    total_tx = len(df)
    if total_tx == 0: return probs
    
    outgoing = df[df["is_outgoing"] == True]
    hourly_std = np.std(hourly_counts)
    hourly_range = max(hourly_counts) - min(hourly_counts)
    
    # Bot detection
    if hourly_range < 3: probs.bot = 90
    elif hourly_range < 5: probs.bot = 65
    elif sleep.activity_during_sleep > total_tx * 0.2: probs.bot = 55
    else: probs.bot = max(0, 25 - sleep.confidence * 0.25)
    
    # MEV/Privacy
    if len(outgoing) > 0:
        high_gas = (outgoing["gas_used"] > 300000).sum() / len(outgoing)
        if probs.bot > 60 and high_gas > 0.5: probs.mev_bot = 80
        mixer = (outgoing["gas_used"] > 1000000).sum() / len(outgoing)
        if mixer > 0.2: probs.privacy_user = 70
    
    # Geographic
    s = sleep.start_hour
    if 20 <= s or s <= 2: probs.eu_trader = 85
    elif 3 <= s <= 8: probs.us_trader = 85
    elif 12 <= s <= 18: probs.asia_trader = 85
    else: probs.eu_trader = probs.us_trader = probs.asia_trader = 33
    
    # Occupation
    weekend = daily_counts[5] + daily_counts[6]
    weekday = sum(daily_counts[:5])
    ratio = (weekend/2) / (weekday/5) if weekday > 0 else 1
    if ratio > 1.5: probs.retail_hobbyist, probs.professional = 80, 20
    elif ratio < 0.5: probs.retail_hobbyist, probs.professional = 20, 80
    else: probs.retail_hobbyist = probs.professional = 50
    
    # Whale/Degen
    if len(outgoing) > 0:
        if outgoing["value_eth"].max() > 10: probs.whale = 85
        elif outgoing["value_eth"].mean() > 1: probs.whale = 60
        fail_rate = (~outgoing["success"]).sum() / len(outgoing)
        if fail_rate > 0.2: probs.degen = 80
    
    probs.normalize()
    return probs


def print_report(df, address, chain, probs, sleep):
    outgoing = df[df["is_outgoing"] == True]
    geo = {"EU": probs.eu_trader, "US": probs.us_trader, "Asia": probs.asia_trader}
    top_geo = max(geo, key=geo.get)
    
    print("\n" + "═"*70)
    print(" 🐊 GATOR EVM INTELLIGENCE DOSSIER")
    print("═"*70)
    print(f" Target: {address}")
    print(f" Chain:  {chain.upper()}")
    print(f" Txs:    {len(df)} ({len(outgoing)} outgoing)")
    print("─"*70)
    print(f"\n Entity:     {'BOT' if probs.bot > 60 else 'HUMAN'} ({max(probs.bot, 100-probs.bot):.0f}%)")
    print(f" Location:   {top_geo} ({geo[top_geo]:.0f}%)")
    print(f" Sleep:      {sleep.start_hour}:00-{sleep.end_hour}:00 UTC")
    print(f" Whale:      {probs.whale:.0f}%")
    print(f" Degen:      {probs.degen:.0f}%")
    if len(outgoing) > 0:
        print(f" Avg Gas:    {outgoing['gas_used'].mean():,.0f}")
        print(f" Total ETH:  {outgoing['value_eth'].sum():.4f}")
    print("═"*70 + "\n")


def visualize_profile(df, address, chain, probs, sleep):
    outgoing = df[df["is_outgoing"] == True]
    hourly = [0]*24
    daily = [0]*7
    for _, r in outgoing.iterrows():
        hourly[r["hour"]] += 1
        daily[r["day_of_week"]] += 1
    
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(14, 10))
    fig.patch.set_facecolor('#0a0a0a')
    fig.suptitle(f"🐊 GATOR — {address[:10]}...{address[-4:]} ({chain.upper()})", color='#22c55e', fontsize=14, fontweight='bold')
    
    # Probabilities
    ax1 = fig.add_subplot(2, 2, 1)
    ax1.set_facecolor('#111111')
    cats = ['Bot', 'MEV', 'EU', 'US', 'Asia', 'Retail', 'Pro', 'Whale', 'Degen']
    vals = [probs.bot, probs.mev_bot, probs.eu_trader, probs.us_trader, probs.asia_trader, 
            probs.retail_hobbyist, probs.professional, probs.whale, probs.degen]
    ax1.barh(cats, vals, color='#06b6d4', alpha=0.7)
    ax1.set_xlim(0, 100)
    ax1.set_title("Profile Probabilities", color='#06b6d4')
    ax1.invert_yaxis()
    
    # Circadian
    ax2 = fig.add_subplot(2, 2, 2)
    ax2.set_facecolor('#111111')
    colors = ['#ef4444' if sleep.start_hour <= i < sleep.start_hour+6 else '#06b6d4' for i in range(24)]
    ax2.bar(range(24), hourly, color=colors, alpha=0.7)
    ax2.set_title("Circadian Rhythm (UTC)", color='#06b6d4')
    ax2.set_xticks(range(0, 24, 4))
    
    # Weekly
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.set_facecolor('#111111')
    ax3.bar(['M','T','W','T','F','S','S'], daily, color=['#06b6d4']*5+['#eab308']*2, alpha=0.7)
    ax3.set_title("Weekly Pattern", color='#eab308')
    
    # Gas scatter
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.set_facecolor('#111111')
    if len(outgoing) > 0:
        colors = [get_gas_color(g) for g in outgoing["gas_used"]]
        ax4.scatter(outgoing["hour"], outgoing["gas_used"], c=colors, alpha=0.7, s=30)
    ax4.set_title("Gas Complexity", color='#f97316')
    ax4.set_xlabel("Hour (UTC)")
    
    plt.tight_layout()
    return fig


def find_connections(addresses, chain, limit):
    print(f"\n[*] Analyzing {len(addresses)} wallets...")
    wallet_txs = {}
    for addr in addresses:
        print(f"[-] Fetching {get_label(addr)}...")
        wallet_txs[addr] = analyze_wallet(addr, chain, limit)
    
    connections = {}
    for i, a in enumerate(addresses):
        for b in addresses[i+1:]:
            conn = WalletConnection(a, b)
            df_a, df_b = wallet_txs[a], wallet_txs[b]
            
            if len(df_a) > 0:
                matches = df_a[(df_a["to"].str.lower() == b.lower()) | (df_a["from"].str.lower() == b.lower())]
                for _, tx in matches.iterrows():
                    conn.tx_count += 1
                    conn.total_value += tx["value_eth"]
                    conn.tx_hashes.append(tx["hash"])
            
            if len(df_b) > 0:
                matches = df_b[(df_b["to"].str.lower() == a.lower()) | (df_b["from"].str.lower() == a.lower())]
                for _, tx in matches.iterrows():
                    if tx["hash"] not in conn.tx_hashes:
                        conn.tx_count += 1
                        conn.total_value += tx["value_eth"]
                        conn.tx_hashes.append(tx["hash"])
            
            if conn.tx_count > 0:
                connections[(a, b)] = conn
    
    return connections


def print_connections(connections, addresses, chain):
    print("\n" + "═"*70)
    print(" 🐊 GATOR CONNECTION ANALYSIS")
    print("═"*70)
    print(f" Chain: {chain.upper()} | Wallets: {len(addresses)} | Connections: {len(connections)}")
    
    if not connections:
        print("\n ❌ No direct connections found")
    else:
        for (a, b), c in sorted(connections.items(), key=lambda x: x[1].tx_count, reverse=True):
            print(f"\n {get_label(a)} ↔ {get_label(b)}")
            print(f"   {c.tx_count} txs | {c.total_value:.4f} ETH")
    print("═"*70 + "\n")


def visualize_connections(connections, addresses):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor('#0a0a0a')
    ax.set_facecolor('#0a0a0a')
    
    n = len(addresses)
    angles = np.linspace(0, 2*np.pi, n, endpoint=False)
    pos = {a: (3*np.cos(angles[i]), 3*np.sin(angles[i])) for i, a in enumerate(addresses)}
    
    max_tx = max([c.tx_count for c in connections.values()]) if connections else 1
    for (a, b), c in connections.items():
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        width = 1 + (c.tx_count / max_tx) * 4
        ax.plot([x1, x2], [y1, y2], color='#06b6d4', linewidth=width, alpha=0.6)
        ax.text((x1+x2)/2, (y1+y2)/2, str(c.tx_count), color='white', fontsize=8, ha='center')
    
    for a, (x, y) in pos.items():
        ax.add_patch(plt.Circle((x, y), 0.3, color='#22c55e'))
        ax.text(x, y-0.6, get_label(a), color='white', fontsize=8, ha='center')
    
    ax.set_xlim(-5, 5)
    ax.set_ylim(-5, 5)
    ax.axis('off')
    ax.set_title("🐊 GATOR Connection Map", color='#22c55e', fontsize=14)
    plt.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description="🐊 Gator EVM OSINT Suite")
    sub = parser.add_subparsers(dest="cmd")
    
    p = sub.add_parser("profile")
    p.add_argument("address")
    p.add_argument("--chain", "-c", default="ethereum", choices=list(EXPLORER_APIS.keys()))
    p.add_argument("--limit", "-l", type=int, default=100)
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--save", "-s")
    
    c = sub.add_parser("connect")
    c.add_argument("addresses", nargs="+")
    c.add_argument("--chain", "-c", default="ethereum", choices=list(EXPLORER_APIS.keys()))
    c.add_argument("--limit", "-l", type=int, default=100)
    c.add_argument("--no-plot", action="store_true")
    c.add_argument("--save", "-s")
    
    args = parser.parse_args()
    
    print("\n    🐊 GATOR - EVM OSINT SUITE v1.0\n")
    
    if args.cmd == "profile":
        df = analyze_wallet(args.address, args.chain, args.limit)
        if df.empty:
            print("[!] No data"); sys.exit(1)
        
        out = df[df["is_outgoing"]==True]
        hourly, daily = [0]*24, [0]*7
        for _, r in out.iterrows():
            hourly[r["hour"]] += 1
            daily[r["day_of_week"]] += 1
        
        sleep = detect_sleep_window(hourly)
        probs = calculate_probabilities(df, hourly, daily, sleep)
        print_report(df, args.address, args.chain, probs, sleep)
        
        df.to_csv(f"gator_{args.address[:10]}.csv", index=False)
        
        if not args.no_plot:
            fig = visualize_profile(df, args.address, args.chain, probs, sleep)
            if args.save: fig.savefig(args.save, dpi=150, facecolor='#0a0a0a')
            plt.show()
    
    elif args.cmd == "connect":
        conns = find_connections(args.addresses, args.chain, args.limit)
        print_connections(conns, args.addresses, args.chain)
        
        if not args.no_plot and conns:
            fig = visualize_connections(conns, args.addresses)
            if args.save: fig.savefig(args.save, dpi=150, facecolor='#0a0a0a')
            plt.show()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
