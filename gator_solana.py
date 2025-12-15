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
║                    SOLANA OSINT SUITE v1.0                                    ║
║                                                                               ║
║  Behavioral profiling, connection mapping, and side-channel analysis         ║
║  for Solana wallets using only PUBLIC blockchain data.                        ║
║                                                                               ║
║  COMMANDS:                                                                    ║
║    python gator_solana.py profile <address>      - Profile a single wallet   ║
║    python gator_solana.py connect <addr1> <addr2> ... - Find connections     ║
║    python gator_solana.py scan <address> --depth N   - Map wallet network    ║
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
from typing import Optional, List, Dict, Set, Tuple
from collections import defaultdict
import json

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

RPC_URL = "https://mainnet.helius-rpc.com/?api-key=307e88f2-33c4-467c-968a-69f194fac6d8"
DEFAULT_LIMIT = 100

# Known labels for common addresses
KNOWN_LABELS = {
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium LP V4",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter V6",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "Pump.fun",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin": "Serum DEX V3",
    "So11111111111111111111111111111111111111112": "Wrapped SOL",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token Program",
    "11111111111111111111111111111111": "System Program",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProfileProbabilities:
    """Probability estimates for different wallet profiles"""
    bot: float = 0.0
    eu_trader: float = 0.0
    us_trader: float = 0.0
    asia_trader: float = 0.0
    retail_hobbyist: float = 0.0
    professional: float = 0.0
    whale: float = 0.0
    degen: float = 0.0
    
    def normalize(self):
        geo_total = self.eu_trader + self.us_trader + self.asia_trader
        if geo_total > 0:
            self.eu_trader = (self.eu_trader / geo_total) * 100
            self.us_trader = (self.us_trader / geo_total) * 100
            self.asia_trader = (self.asia_trader / geo_total) * 100
        
        occ_total = self.retail_hobbyist + self.professional
        if occ_total > 0:
            self.retail_hobbyist = (self.retail_hobbyist / occ_total) * 100
            self.professional = (self.professional / occ_total) * 100


@dataclass
class SleepWindow:
    start_hour: int
    end_hour: int
    activity_during_sleep: int
    confidence: float


@dataclass
class WalletConnection:
    """Represents a connection between two wallets"""
    wallet_a: str
    wallet_b: str
    tx_count: int = 0
    total_volume: float = 0.0
    first_interaction: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    signatures: List[str] = field(default_factory=list)
    direction: str = "bidirectional"  # "a_to_b", "b_to_a", "bidirectional"


# ═══════════════════════════════════════════════════════════════════════════════
# RPC FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def rpc_call(method: str, params: list) -> Optional[dict]:
    """Make an RPC call to Solana"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    
    try:
        response = requests.post(RPC_URL, json=payload, timeout=30)
        data = response.json()
        
        if "error" in data:
            return None
        
        return data.get("result")
    except:
        return None


def fetch_signatures(wallet: str, limit: int = 100) -> list:
    """Fetch transaction signatures for a wallet"""
    result = rpc_call("getSignaturesForAddress", [wallet, {"limit": limit}])
    return result if result else []


def fetch_transaction(signature: str) -> Optional[dict]:
    """Fetch full transaction details"""
    return rpc_call("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])


def get_label(address: str) -> str:
    """Get human-readable label for an address"""
    return KNOWN_LABELS.get(address, address[:8] + "..." + address[-4:])


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILE COMMAND - Single Wallet Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_wallet(wallet: str, limit: int = 100) -> pd.DataFrame:
    """Fetch and analyze wallet transactions"""
    print(f"\n[*] Fetching last {limit} transactions...")
    
    signatures = fetch_signatures(wallet, limit)
    
    if not signatures:
        return pd.DataFrame()
    
    print(f"[+] Found {len(signatures)} transactions")
    print(f"[-] Analyzing details...\n")
    
    transactions = []
    
    for idx, sig_info in enumerate(signatures):
        progress = (idx + 1) / len(signatures)
        bar_len = 40
        filled = int(bar_len * progress)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"\r    [{bar}] {idx + 1}/{len(signatures)}", end="", flush=True)
        
        signature = sig_info["signature"]
        block_time = sig_info.get("blockTime")
        
        if not block_time:
            continue
        
        tx_details = fetch_transaction(signature)
        
        compute_units = 0
        fee = 0
        instructions = 0
        
        if tx_details and tx_details.get("meta"):
            compute_units = tx_details["meta"].get("computeUnitsConsumed", 0) or 0
            fee = tx_details["meta"].get("fee", 0) or 0
            
            msg = tx_details.get("transaction", {}).get("message", {})
            if msg.get("instructions"):
                instructions = len(msg["instructions"])
        
        utc_time = datetime.fromtimestamp(block_time, tz=timezone.utc)
        
        transactions.append({
            "signature": signature,
            "timestamp": utc_time,
            "hour": utc_time.hour,
            "day_of_week": utc_time.weekday(),
            "day_name": utc_time.strftime("%A"),
            "compute_units": compute_units,
            "fee_lamports": fee,
            "fee_sol": fee / 1e9,
            "instructions": instructions,
            "success": sig_info.get("err") is None,
            "slot": sig_info.get("slot", 0)
        })
    
    print(f"\n[+] Analyzed {len(transactions)} transactions\n")
    
    return pd.DataFrame(transactions)


def detect_sleep_window(hourly_counts: list) -> SleepWindow:
    min_sum = float('inf')
    sleep_start = 0
    total_tx = sum(hourly_counts)
    
    for i in range(24):
        window_sum = sum(hourly_counts[(i + j) % 24] for j in range(6))
        if window_sum < min_sum:
            min_sum = window_sum
            sleep_start = i
    
    sleep_ratio = min_sum / total_tx if total_tx > 0 else 0
    confidence = max(0, min(100, (1 - sleep_ratio * 4) * 100))
    
    return SleepWindow(
        start_hour=sleep_start,
        end_hour=(sleep_start + 6) % 24,
        activity_during_sleep=min_sum,
        confidence=confidence
    )


def calculate_probabilities(df: pd.DataFrame, hourly_counts: list, daily_counts: list, sleep: SleepWindow) -> ProfileProbabilities:
    probs = ProfileProbabilities()
    total_tx = len(df)
    
    if total_tx == 0:
        return probs
    
    # Bot detection
    hourly_std = np.std(hourly_counts)
    hourly_range = max(hourly_counts) - min(hourly_counts)
    
    if hourly_range < 3 or hourly_std < 1.5:
        probs.bot = 95.0
    elif hourly_range < 5:
        probs.bot = 70.0
    elif sleep.activity_during_sleep > total_tx * 0.2:
        probs.bot = 60.0
    elif sleep.confidence < 50:
        probs.bot = 40.0
    else:
        probs.bot = max(0, 30 - sleep.confidence * 0.3)
    
    # Geographic inference
    s = sleep.start_hour
    
    if 20 <= s or s <= 2:
        probs.eu_trader = 80 + (10 if s in [22, 23, 0] else 0)
    elif 18 <= s <= 19 or 3 <= s <= 4:
        probs.eu_trader = 40
    else:
        probs.eu_trader = 10
    
    if 3 <= s <= 8:
        probs.us_trader = 80 + (10 if s in [5, 6, 7] else 0)
    elif 9 <= s <= 10 or 1 <= s <= 2:
        probs.us_trader = 40
    else:
        probs.us_trader = 10
    
    if 12 <= s <= 18:
        probs.asia_trader = 80 + (10 if s in [14, 15, 16] else 0)
    elif 10 <= s <= 11 or 19 <= s <= 20:
        probs.asia_trader = 40
    else:
        probs.asia_trader = 10
    
    # Occupation inference
    weekend_tx = daily_counts[5] + daily_counts[6]
    weekday_tx = sum(daily_counts[:5])
    
    if weekday_tx > 0:
        weekend_ratio = (weekend_tx / 2) / (weekday_tx / 5)
    else:
        weekend_ratio = 2.0 if weekend_tx > 0 else 1.0
    
    if weekend_ratio > 2.0:
        probs.retail_hobbyist = 90
        probs.professional = 10
    elif weekend_ratio > 1.3:
        probs.retail_hobbyist = 70
        probs.professional = 30
    elif weekend_ratio < 0.3:
        probs.retail_hobbyist = 10
        probs.professional = 90
    elif weekend_ratio < 0.6:
        probs.retail_hobbyist = 30
        probs.professional = 70
    else:
        probs.retail_hobbyist = 50
        probs.professional = 50
    
    # Whale detection
    avg_cu = df["compute_units"].mean()
    avg_fee = df["fee_sol"].mean()
    
    if avg_cu > 300000 or avg_fee > 0.01:
        probs.whale = 85
    elif avg_cu > 200000 or avg_fee > 0.005:
        probs.whale = 60
    elif avg_cu > 100000:
        probs.whale = 30
    else:
        probs.whale = 10
    
    # Degen detection
    fail_rate = (~df["success"]).sum() / total_tx
    high_cu_ratio = (df["compute_units"] > 200000).sum() / total_tx
    
    if fail_rate > 0.3 or high_cu_ratio > 0.5:
        probs.degen = 85
    elif fail_rate > 0.15 or high_cu_ratio > 0.3:
        probs.degen = 60
    elif fail_rate > 0.08:
        probs.degen = 40
    else:
        probs.degen = 15
    
    probs.normalize()
    return probs


def get_complexity_color(cu: int) -> str:
    if cu < 50000:
        return '#22c55e'
    elif cu < 150000:
        return '#eab308'
    elif cu < 300000:
        return '#f97316'
    else:
        return '#ef4444'


def get_complexity_label(cu: float) -> str:
    if cu < 50000:
        return 'Simple'
    elif cu < 150000:
        return 'Moderate'
    elif cu < 300000:
        return 'Complex'
    else:
        return 'Heavy'


def visualize_profile(df: pd.DataFrame, wallet: str, probs: ProfileProbabilities, sleep: SleepWindow):
    """Generate profile visualization"""
    
    hourly_counts = [0] * 24
    daily_counts = [0] * 7
    
    for _, row in df.iterrows():
        hourly_counts[row["hour"]] += 1
        daily_counts[row["day_of_week"]] += 1
    
    peak_hour = hourly_counts.index(max(hourly_counts))
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    weekend_tx = daily_counts[5] + daily_counts[6]
    weekday_tx = sum(daily_counts[:5])
    weekend_ratio = (weekend_tx / 2) / (weekday_tx / 5) if weekday_tx > 0 else 0
    
    panic_count = 0
    for _, row in df.iterrows():
        in_sleep = (sleep.start_hour <= row["hour"] < sleep.start_hour + 6) or \
                   (sleep.start_hour + 6 > 24 and row["hour"] < (sleep.start_hour + 6) % 24)
        if in_sleep and row["compute_units"] > 200000:
            panic_count += 1
    
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 14))
    
    bg_color = '#0a0a0a'
    panel_color = '#111111'
    grid_color = '#1f2937'
    text_color = '#9ca3af'
    accent_cyan = '#06b6d4'
    accent_yellow = '#eab308'
    accent_orange = '#f97316'
    accent_green = '#22c55e'
    accent_red = '#ef4444'
    accent_purple = '#a855f7'
    
    fig.patch.set_facecolor(bg_color)
    fig.suptitle(f"🐊 GATOR PROFILE — {wallet[:12]}...{wallet[-6:]}", 
                 fontsize=16, color=accent_green, fontweight='bold', y=0.98)
    
    # Panel 1: Profile probabilities
    ax0 = fig.add_subplot(4, 2, (1, 2))
    ax0.set_facecolor(panel_color)
    
    categories = ['Bot (Automated)', 'Europe/Africa', 'Americas', 'Asia/Pacific',
                  'Retail/Hobbyist', 'Professional', 'Whale', 'Degen/High-Risk']
    values = [probs.bot, probs.eu_trader, probs.us_trader, probs.asia_trader,
              probs.retail_hobbyist, probs.professional, probs.whale, probs.degen]
    colors = [accent_purple, accent_cyan, accent_cyan, accent_cyan,
              accent_yellow, accent_yellow, accent_green, accent_red]
    
    bars = ax0.barh(categories, values, color=colors, alpha=0.7, edgecolor='white', linewidth=0.5)
    
    for bar, val in zip(bars, values):
        ax0.text(val + 1, bar.get_y() + bar.get_height()/2, f'{val:.1f}%',
                 va='center', ha='left', color='white', fontsize=9)
    
    ax0.set_xlim(0, 110)
    ax0.set_title("PROFILE PROBABILITY ANALYSIS", color=accent_purple, fontsize=12, fontweight='bold', loc='left')
    ax0.set_xlabel("Probability (%)", color=text_color)
    ax0.tick_params(colors=text_color)
    ax0.grid(True, alpha=0.2, color=grid_color, axis='x')
    ax0.invert_yaxis()
    
    # Panel 2: Circadian rhythm
    ax1 = fig.add_subplot(4, 2, 3)
    ax1.set_facecolor(panel_color)
    
    bar_colors = []
    for i in range(24):
        in_sleep = (sleep.start_hour <= i < sleep.start_hour + 6) or \
                   (sleep.start_hour + 6 > 24 and i < (sleep.start_hour + 6) % 24)
        if i == peak_hour:
            bar_colors.append(accent_green)
        elif in_sleep:
            bar_colors.append(accent_red)
        else:
            bar_colors.append(accent_cyan)
    
    ax1.bar(range(24), hourly_counts, color=bar_colors, alpha=0.7, edgecolor='white', linewidth=0.3)
    
    if sleep.start_hour + 6 <= 24:
        ax1.axvspan(sleep.start_hour - 0.5, sleep.start_hour + 5.5, alpha=0.15, color='red')
    else:
        ax1.axvspan(sleep.start_hour - 0.5, 23.5, alpha=0.15, color='red')
        ax1.axvspan(-0.5, (sleep.start_hour + 6) % 24 - 0.5, alpha=0.15, color='red')
    
    ax1.set_title("CIRCADIAN RHYTHM", color=accent_cyan, fontsize=11, fontweight='bold', loc='left')
    ax1.set_xlabel("Hour (UTC)", color=text_color)
    ax1.set_ylabel("Transactions", color=text_color)
    ax1.set_xticks(range(0, 24, 2))
    ax1.tick_params(colors=text_color)
    ax1.grid(True, alpha=0.2, color=grid_color, axis='y')
    
    sleep_patch = mpatches.Patch(color=accent_red, alpha=0.5, label=f'Sleep ({sleep.start_hour}:00-{sleep.end_hour}:00 UTC)')
    peak_patch = mpatches.Patch(color=accent_green, label=f'Peak ({peak_hour}:00 UTC)')
    ax1.legend(handles=[sleep_patch, peak_patch], loc='upper right', facecolor=panel_color,
               edgecolor=grid_color, fontsize=8)
    
    # Panel 3: Geographic pie
    ax2 = fig.add_subplot(4, 2, 4)
    ax2.set_facecolor(panel_color)
    
    geo_labels = ['Europe/Africa', 'Americas', 'Asia/Pacific']
    geo_values = [probs.eu_trader, probs.us_trader, probs.asia_trader]
    geo_colors = ['#3b82f6', '#ef4444', '#22c55e']
    
    ax2.pie(geo_values, labels=geo_labels, autopct='%1.1f%%', colors=geo_colors, startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 1}, textprops={'color': 'white', 'fontsize': 9})
    ax2.set_title("GEOGRAPHIC PROBABILITY", color=accent_cyan, fontsize=11, fontweight='bold')
    
    # Panel 4: Weekly routine
    ax3 = fig.add_subplot(4, 2, 5)
    ax3.set_facecolor(panel_color)
    
    day_colors = [accent_cyan if i < 5 else accent_yellow for i in range(7)]
    ax3.bar(days, daily_counts, color=day_colors, alpha=0.7, edgecolor='white', linewidth=0.5)
    
    ax3.set_title("WEEKLY ROUTINE", color=accent_yellow, fontsize=11, fontweight='bold', loc='left')
    ax3.set_xlabel("Day of Week", color=text_color)
    ax3.set_ylabel("Transactions", color=text_color)
    ax3.tick_params(colors=text_color)
    ax3.grid(True, alpha=0.2, color=grid_color, axis='y')
    
    occ_text = f"Weekend Ratio: {weekend_ratio:.2f}x\n"
    occ_text += f"→ {probs.retail_hobbyist:.0f}% Retail" if probs.retail_hobbyist > probs.professional else f"→ {probs.professional:.0f}% Professional"
    ax3.text(0.98, 0.95, occ_text, transform=ax3.transAxes, ha='right', va='top', color=accent_yellow, fontsize=9,
             bbox=dict(boxstyle='round', facecolor=panel_color, edgecolor=accent_yellow, alpha=0.8))
    
    # Panel 5: Occupation pie
    ax4 = fig.add_subplot(4, 2, 6)
    ax4.set_facecolor(panel_color)
    
    ax4.pie([probs.retail_hobbyist, probs.professional], labels=['Retail/Hobbyist', 'Professional'],
            autopct='%1.1f%%', colors=[accent_yellow, accent_cyan], startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 1}, textprops={'color': 'white', 'fontsize': 10})
    ax4.set_title("OCCUPATION PROBABILITY", color=accent_yellow, fontsize=11, fontweight='bold')
    
    # Panel 6: Complexity scatter
    ax5 = fig.add_subplot(4, 2, 7)
    ax5.set_facecolor(panel_color)
    
    colors = [get_complexity_color(cu) for cu in df["compute_units"]]
    sizes = []
    for _, row in df.iterrows():
        in_sleep = (sleep.start_hour <= row["hour"] < sleep.start_hour + 6) or \
                   (sleep.start_hour + 6 > 24 and row["hour"] < (sleep.start_hour + 6) % 24)
        sizes.append(120 if in_sleep and row["compute_units"] > 200000 else 40)
    
    ax5.scatter(df["hour"] + np.random.uniform(-0.3, 0.3, len(df)), df["compute_units"],
                c=colors, s=sizes, alpha=0.7, edgecolors='white', linewidths=0.3)
    
    if sleep.start_hour + 6 <= 24:
        ax5.axvspan(sleep.start_hour - 0.5, sleep.start_hour + 5.5, alpha=0.1, color='red')
    else:
        ax5.axvspan(sleep.start_hour - 0.5, 23.5, alpha=0.1, color='red')
        ax5.axvspan(-0.5, (sleep.start_hour + 6) % 24 - 0.5, alpha=0.1, color='red')
    
    ax5.set_title("BEHAVIORAL COMPLEXITY", color=accent_orange, fontsize=11, fontweight='bold', loc='left')
    ax5.set_xlabel("Hour (UTC)", color=text_color)
    ax5.set_ylabel("Compute Units", color=text_color)
    ax5.set_xticks(range(0, 24, 2))
    ax5.set_xlim(-0.5, 23.5)
    ax5.tick_params(colors=text_color)
    ax5.grid(True, alpha=0.2, color=grid_color)
    
    legend_elements = [
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#22c55e', markersize=8, label='Simple (<50K)', linestyle='None'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#eab308', markersize=8, label='Moderate', linestyle='None'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#f97316', markersize=8, label='Complex', linestyle='None'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#ef4444', markersize=8, label='Heavy (>300K)', linestyle='None'),
    ]
    ax5.legend(handles=legend_elements, loc='upper right', facecolor=panel_color, edgecolor=grid_color, fontsize=7, ncol=2)
    
    # Panel 7: Risk profile
    ax6 = fig.add_subplot(4, 2, 8)
    ax6.set_facecolor(panel_color)
    
    risk_labels = ['Whale\n(High Value)', 'Degen\n(High Risk)', 'Bot\n(Automated)']
    risk_values = [probs.whale, probs.degen, probs.bot]
    risk_colors = [accent_green, accent_red, accent_purple]
    
    bars = ax6.bar(risk_labels, risk_values, color=risk_colors, alpha=0.7, edgecolor='white', linewidth=0.5)
    
    for bar, val in zip(bars, risk_values):
        ax6.text(bar.get_x() + bar.get_width()/2, val + 2, f'{val:.1f}%',
                 ha='center', va='bottom', color='white', fontsize=10, fontweight='bold')
    
    ax6.set_title("RISK PROFILE", color=accent_red, fontsize=11, fontweight='bold', loc='left')
    ax6.set_ylabel("Probability (%)", color=text_color)
    ax6.set_ylim(0, 110)
    ax6.tick_params(colors=text_color)
    ax6.grid(True, alpha=0.2, color=grid_color, axis='y')
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.94)
    
    return fig


def print_profile_report(df: pd.DataFrame, wallet: str, probs: ProfileProbabilities, sleep: SleepWindow):
    """Print profile intelligence report"""
    
    total_tx = len(df)
    avg_cu = df["compute_units"].mean()
    fail_rate = (~df["success"]).sum() / total_tx * 100
    
    daily_counts = [0] * 7
    for _, row in df.iterrows():
        daily_counts[row["day_of_week"]] += 1
    weekend_tx = daily_counts[5] + daily_counts[6]
    weekday_tx = sum(daily_counts[:5])
    weekend_ratio = (weekend_tx / 2) / (weekday_tx / 5) if weekday_tx > 0 else 0
    
    geo = {"Europe/Africa": probs.eu_trader, "Americas": probs.us_trader, "Asia/Pacific": probs.asia_trader}
    top_geo = max(geo, key=geo.get)
    
    cities = {
        "Europe/Africa": "London, Frankfurt, Zurich, Dubai",
        "Americas": "New York, Chicago, Miami, Los Angeles, São Paulo",
        "Asia/Pacific": "Singapore, Hong Kong, Tokyo, Sydney, Mumbai"
    }
    
    print("\n" + "═" * 70)
    print(" 🐊 GATOR INTELLIGENCE DOSSIER")
    print("═" * 70)
    print(f" Target:            {wallet}")
    print(f" Transactions:      {total_tx}")
    print(f" Period:            {df['timestamp'].min().strftime('%Y-%m-%d %H:%M')} → {df['timestamp'].max().strftime('%Y-%m-%d %H:%M')} UTC")
    print("─" * 70)
    
    print("\n 🤖 ENTITY CLASSIFICATION")
    print("─" * 70)
    if probs.bot > 60:
        print(f" ├─ Type:           BOT / AUTOMATED ({probs.bot:.1f}%)")
        print(f" └─ Note:           No human sleep pattern detected")
    else:
        print(f" ├─ Type:           HUMAN ({100 - probs.bot:.1f}%)")
        print(f" ├─ Sleep Window:   {sleep.start_hour}:00 → {sleep.end_hour}:00 UTC")
        print(f" └─ Confidence:     {sleep.confidence:.1f}%")
    
    print("\n 🌍 GEOGRAPHIC INFERENCE")
    print("─" * 70)
    print(f" ├─ Primary:        {top_geo} ({geo[top_geo]:.1f}%)")
    print(f" ├─ Likely Cities:  {cities[top_geo]}")
    print(f" ├─ Europe/Africa:  {probs.eu_trader:.1f}%")
    print(f" ├─ Americas:       {probs.us_trader:.1f}%")
    print(f" └─ Asia/Pacific:   {probs.asia_trader:.1f}%")
    
    print("\n 💼 OCCUPATION INFERENCE")
    print("─" * 70)
    print(f" ├─ Weekend Ratio:  {weekend_ratio:.2f}x")
    if probs.retail_hobbyist > probs.professional:
        print(f" ├─ Type:           RETAIL / HOBBYIST ({probs.retail_hobbyist:.1f}%)")
        print(f" └─ Note:           Likely has day job")
    else:
        print(f" ├─ Type:           PROFESSIONAL ({probs.professional:.1f}%)")
        print(f" └─ Note:           Trading is primary activity")
    
    print("\n 📊 BEHAVIORAL PROFILE")
    print("─" * 70)
    print(f" ├─ Avg Complexity: {avg_cu:,.0f} CU ({get_complexity_label(avg_cu)})")
    print(f" ├─ Fail Rate:      {fail_rate:.1f}%")
    print(f" ├─ Whale Prob.:    {probs.whale:.1f}%")
    print(f" └─ Degen Prob.:    {probs.degen:.1f}%")
    
    print("\n" + "═" * 70)
    print(" ⚠️  ALL DATA FROM PUBLIC BLOCKCHAIN — NO ENCRYPTION BROKEN")
    print("═" * 70 + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CONNECT COMMAND - Find Connections Between Wallets
# ═══════════════════════════════════════════════════════════════════════════════

def extract_accounts_from_tx(tx_details: dict) -> Set[str]:
    """Extract all account addresses involved in a transaction"""
    accounts = set()
    
    if not tx_details:
        return accounts
    
    try:
        # Get account keys from message
        msg = tx_details.get("transaction", {}).get("message", {})
        account_keys = msg.get("accountKeys", [])
        
        for key in account_keys:
            if isinstance(key, dict):
                accounts.add(key.get("pubkey", ""))
            else:
                accounts.add(str(key))
        
        # Also check instructions for program IDs
        for ix in msg.get("instructions", []):
            if isinstance(ix, dict):
                if "programId" in ix:
                    accounts.add(ix["programId"])
                if "accounts" in ix:
                    accounts.update(ix["accounts"])
    except:
        pass
    
    # Remove empty strings and system programs
    accounts.discard("")
    accounts.discard("11111111111111111111111111111111")
    accounts.discard("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    
    return accounts


def find_connections(wallets: List[str], limit: int = 100) -> Dict[Tuple[str, str], WalletConnection]:
    """Find connections between multiple wallets"""
    
    print(f"\n[*] Analyzing connections between {len(wallets)} wallets...")
    
    # Collect all transactions for each wallet
    wallet_txs: Dict[str, List[dict]] = {}
    wallet_accounts: Dict[str, Dict[str, Set[str]]] = {}  # wallet -> {signature -> accounts}
    
    for wallet in wallets:
        print(f"\n[-] Fetching transactions for {get_label(wallet)}...")
        signatures = fetch_signatures(wallet, limit)
        
        wallet_txs[wallet] = []
        wallet_accounts[wallet] = {}
        
        for idx, sig_info in enumerate(signatures):
            progress = (idx + 1) / len(signatures)
            bar_len = 30
            filled = int(bar_len * progress)
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"\r    [{bar}] {idx + 1}/{len(signatures)}", end="", flush=True)
            
            signature = sig_info["signature"]
            tx_details = fetch_transaction(signature)
            
            if tx_details:
                wallet_txs[wallet].append({
                    "signature": signature,
                    "block_time": sig_info.get("blockTime"),
                    "details": tx_details
                })
                wallet_accounts[wallet][signature] = extract_accounts_from_tx(tx_details)
        
        print()
    
    # Find connections
    connections: Dict[Tuple[str, str], WalletConnection] = {}
    
    print("\n[*] Analyzing connections...")
    
    for i, wallet_a in enumerate(wallets):
        for wallet_b in wallets[i+1:]:
            # Check for direct transactions
            conn = WalletConnection(wallet_a=wallet_a, wallet_b=wallet_b)
            
            # Check if wallet_b appears in wallet_a's transactions
            for tx in wallet_txs[wallet_a]:
                accounts = wallet_accounts[wallet_a].get(tx["signature"], set())
                if wallet_b in accounts:
                    conn.tx_count += 1
                    conn.signatures.append(tx["signature"])
                    
                    if tx["block_time"]:
                        tx_time = datetime.fromtimestamp(tx["block_time"], tz=timezone.utc)
                        if conn.first_interaction is None or tx_time < conn.first_interaction:
                            conn.first_interaction = tx_time
                        if conn.last_interaction is None or tx_time > conn.last_interaction:
                            conn.last_interaction = tx_time
            
            # Check if wallet_a appears in wallet_b's transactions
            for tx in wallet_txs[wallet_b]:
                accounts = wallet_accounts[wallet_b].get(tx["signature"], set())
                if wallet_a in accounts:
                    if tx["signature"] not in conn.signatures:  # Avoid duplicates
                        conn.tx_count += 1
                        conn.signatures.append(tx["signature"])
                        
                        if tx["block_time"]:
                            tx_time = datetime.fromtimestamp(tx["block_time"], tz=timezone.utc)
                            if conn.first_interaction is None or tx_time < conn.first_interaction:
                                conn.first_interaction = tx_time
                            if conn.last_interaction is None or tx_time > conn.last_interaction:
                                conn.last_interaction = tx_time
            
            if conn.tx_count > 0:
                connections[(wallet_a, wallet_b)] = conn
    
    return connections


def print_connection_report(connections: Dict[Tuple[str, str], WalletConnection], wallets: List[str]):
    """Print connection analysis report"""
    
    print("\n" + "═" * 70)
    print(" 🐊 GATOR CONNECTION ANALYSIS")
    print("═" * 70)
    print(f" Wallets Analyzed: {len(wallets)}")
    print(f" Connections Found: {len(connections)}")
    print("─" * 70)
    
    if not connections:
        print("\n ❌ NO DIRECT CONNECTIONS FOUND")
        print("    The wallets have not interacted directly within the analyzed range.")
        print("═" * 70 + "\n")
        return
    
    # Sort by transaction count
    sorted_conns = sorted(connections.values(), key=lambda x: x.tx_count, reverse=True)
    
    print("\n 🔗 DIRECT CONNECTIONS")
    print("─" * 70)
    
    for conn in sorted_conns:
        label_a = get_label(conn.wallet_a)
        label_b = get_label(conn.wallet_b)
        
        print(f"\n ┌─ {label_a}")
        print(f" │  ↕ {conn.tx_count} transactions")
        print(f" └─ {label_b}")
        
        if conn.first_interaction:
            print(f"    First: {conn.first_interaction.strftime('%Y-%m-%d %H:%M')} UTC")
        if conn.last_interaction:
            print(f"    Last:  {conn.last_interaction.strftime('%Y-%m-%d %H:%M')} UTC")
        
        if conn.signatures:
            print(f"    Sample: {conn.signatures[0][:20]}...")
    
    print("\n" + "═" * 70)
    print(" ⚠️  ALL DATA FROM PUBLIC BLOCKCHAIN — NO ENCRYPTION BROKEN")
    print("═" * 70 + "\n")


def visualize_connections(connections: Dict[Tuple[str, str], WalletConnection], wallets: List[str]):
    """Visualize wallet connections as a network graph"""
    
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 10))
    
    bg_color = '#0a0a0a'
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # Position wallets in a circle
    n = len(wallets)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    radius = 3
    
    positions = {}
    for i, wallet in enumerate(wallets):
        positions[wallet] = (radius * np.cos(angles[i]), radius * np.sin(angles[i]))
    
    # Draw connections
    max_tx = max([c.tx_count for c in connections.values()]) if connections else 1
    
    for (wallet_a, wallet_b), conn in connections.items():
        x1, y1 = positions[wallet_a]
        x2, y2 = positions[wallet_b]
        
        # Line width based on transaction count
        width = 1 + (conn.tx_count / max_tx) * 5
        alpha = 0.3 + (conn.tx_count / max_tx) * 0.5
        
        ax.plot([x1, x2], [y1, y2], color='#06b6d4', linewidth=width, alpha=alpha)
        
        # Label the connection
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mid_x, mid_y, f"{conn.tx_count}", fontsize=8, color='white',
                ha='center', va='center', bbox=dict(boxstyle='round', facecolor='#111111', alpha=0.8))
    
    # Draw wallet nodes
    for wallet, (x, y) in positions.items():
        circle = plt.Circle((x, y), 0.4, color='#22c55e', alpha=0.8)
        ax.add_patch(circle)
        
        label = get_label(wallet)
        ax.text(x, y - 0.7, label, fontsize=9, color='white', ha='center', va='top')
    
    ax.set_xlim(-5, 5)
    ax.set_ylim(-5, 5)
    ax.set_aspect('equal')
    ax.axis('off')
    
    ax.set_title("🐊 GATOR - Wallet Connection Map", fontsize=14, color='#22c55e', fontweight='bold')
    
    plt.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# SCAN COMMAND - Map Wallet Network (Future Feature)
# ═══════════════════════════════════════════════════════════════════════════════

def scan_network(wallet: str, depth: int = 1, limit: int = 50):
    """Scan and map a wallet's network connections"""
    
    print(f"\n[*] Scanning network for {get_label(wallet)} (depth={depth})...")
    
    discovered: Set[str] = {wallet}
    connections: Dict[Tuple[str, str], WalletConnection] = {}
    current_level = {wallet}
    
    for level in range(depth):
        print(f"\n[-] Level {level + 1}...")
        next_level = set()
        
        for w in current_level:
            print(f"    Analyzing {get_label(w)}...")
            signatures = fetch_signatures(w, limit)
            
            for sig_info in signatures[:limit]:
                tx_details = fetch_transaction(sig_info["signature"])
                accounts = extract_accounts_from_tx(tx_details)
                
                # Find new wallets (filter out programs)
                for acc in accounts:
                    if acc not in discovered and len(acc) > 40:  # Likely a wallet
                        # Quick check: has this account made transactions?
                        test_sigs = fetch_signatures(acc, 1)
                        if test_sigs:
                            next_level.add(acc)
                            discovered.add(acc)
                            
                            # Record connection
                            if (w, acc) not in connections and (acc, w) not in connections:
                                connections[(w, acc)] = WalletConnection(
                                    wallet_a=w, wallet_b=acc, tx_count=1,
                                    signatures=[sig_info["signature"]]
                                )
        
        current_level = next_level
        print(f"    Discovered {len(next_level)} new wallets")
    
    return discovered, connections


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def print_banner():
    print("""
    ╔═══════════════════════════════════════════════════════════════════╗
    ║                                                                   ║
    ║      ██████   █████  ████████  ██████  ██████                     ║
    ║     ██       ██   ██    ██    ██    ██ ██   ██                    ║
    ║     ██   ███ ███████    ██    ██    ██ ██████                     ║
    ║     ██    ██ ██   ██    ██    ██    ██ ██   ██                    ║
    ║      ██████  ██   ██    ██     ██████  ██   ██                    ║
    ║                                                                   ║
    ║                  SOLANA OSINT SUITE v1.0                          ║
    ║                                                                   ║
    ╚═══════════════════════════════════════════════════════════════════╝
    """)


def main():
    parser = argparse.ArgumentParser(
        description="🐊 Gator - Solana OSINT Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  profile   Analyze a single wallet's behavioral patterns
  connect   Find connections between multiple wallets
  scan      Map a wallet's network (experimental)

Examples:
  python gator_solana.py profile 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8
  python gator_solana.py connect wallet1 wallet2 wallet3
  python gator_solana.py scan wallet1 --depth 2
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Profile command
    profile_parser = subparsers.add_parser("profile", help="Profile a single wallet")
    profile_parser.add_argument("address", help="Wallet address to profile")
    profile_parser.add_argument("--limit", "-l", type=int, default=100, help="Transaction limit")
    profile_parser.add_argument("--no-plot", action="store_true", help="Skip visualization")
    profile_parser.add_argument("--save", "-s", type=str, help="Save plot to file")
    
    # Connect command
    connect_parser = subparsers.add_parser("connect", help="Find connections between wallets")
    connect_parser.add_argument("addresses", nargs="+", help="Wallet addresses to analyze")
    connect_parser.add_argument("--limit", "-l", type=int, default=50, help="Transactions per wallet")
    connect_parser.add_argument("--no-plot", action="store_true", help="Skip visualization")
    connect_parser.add_argument("--save", "-s", type=str, help="Save plot to file")
    
    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Map wallet network")
    scan_parser.add_argument("address", help="Starting wallet address")
    scan_parser.add_argument("--depth", "-d", type=int, default=1, help="Network depth")
    scan_parser.add_argument("--limit", "-l", type=int, default=30, help="Transactions per wallet")
    
    args = parser.parse_args()
    
    print_banner()
    
    if args.command == "profile":
        df = analyze_wallet(args.address, args.limit)
        
        if df.empty:
            print("[!] No data. Exiting.")
            sys.exit(1)
        
        hourly_counts = [0] * 24
        daily_counts = [0] * 7
        for _, row in df.iterrows():
            hourly_counts[row["hour"]] += 1
            daily_counts[row["day_of_week"]] += 1
        
        sleep = detect_sleep_window(hourly_counts)
        probs = calculate_probabilities(df, hourly_counts, daily_counts, sleep)
        
        print_profile_report(df, args.address, probs, sleep)
        
        csv_path = f"gator_profile_{args.address[:8]}.csv"
        df.to_csv(csv_path, index=False)
        print(f"[+] Data saved: {csv_path}")
        
        if not args.no_plot:
            fig = visualize_profile(df, args.address, probs, sleep)
            if args.save:
                fig.savefig(args.save, dpi=150, facecolor='#0a0a0a', bbox_inches='tight')
                print(f"[+] Plot saved: {args.save}")
            plt.show()
    
    elif args.command == "connect":
        if len(args.addresses) < 2:
            print("[!] Need at least 2 addresses to find connections")
            sys.exit(1)
        
        connections = find_connections(args.addresses, args.limit)
        print_connection_report(connections, args.addresses)
        
        if not args.no_plot and connections:
            fig = visualize_connections(connections, args.addresses)
            if args.save:
                fig.savefig(args.save, dpi=150, facecolor='#0a0a0a', bbox_inches='tight')
                print(f"[+] Plot saved: {args.save}")
            plt.show()
    
    elif args.command == "scan":
        discovered, connections = scan_network(args.address, args.depth, args.limit)
        
        print(f"\n[+] Discovered {len(discovered)} wallets")
        print(f"[+] Found {len(connections)} connections")
        
        for wallet in discovered:
            print(f"    - {get_label(wallet)}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
