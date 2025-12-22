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

ETHERSCAN_API_KEY = "D4BP9GF8BKTTDIAP442ZY2V3N6UN7GC1UM"

# Etherscan API V2 - Unified endpoint for all chains
API_V2_BASE_URL = "https://api.etherscan.io/v2/api"

# Chain ID mapping for V2 API
CHAIN_IDS = {
    "ethereum": 1,
    "base": 8453,
    "arbitrum": 42161,
    "optimism": 10,
    "polygon": 137,
}

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
class ReactionSpeedAnalysis:
    """Analysis of reaction speed for bot detection"""
    bot_confidence: float = 0.0
    avg_reaction_time: float = 0.0
    median_reaction_time: float = 0.0
    fastest_reaction: float = 0.0
    instant_reactions: int = 0  # < 5 seconds
    fast_reactions: int = 0  # 5-30 seconds
    human_reactions: int = 0  # > 30 seconds
    total_reaction_pairs: int = 0


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
    """Make API call using Etherscan API V2 format"""
    # Get chainid for the specified chain (default to Ethereum)
    chainid = CHAIN_IDS.get(chain, 1)
    
    # Use V2 unified endpoint
    api_url = API_V2_BASE_URL
    params["apikey"] = ETHERSCAN_API_KEY
    params["chainid"] = chainid  # Required for V2
    
    try:
        response = requests.get(api_url, params=params, timeout=30)
        data = response.json()
        status = data.get("status")
        result = data.get("result")
        message = data.get("message", "")
        
        if status == "1":
            # Success - return the result
            if isinstance(result, str) and result == "0":
                return []  # Empty list, not None
            return result if result else []
        elif status == "0":
            # Status 0 can mean "no results" (valid) or "error" (invalid)
            if message and "no transactions found" in message.lower():
                return []  # Valid empty result
            elif message and ("not found" in message.lower() or "invalid" in message.lower()):
                print(f"\n[!] API Error: {message}")
                return None
            elif message and "deprecated" in message.lower():
                print(f"\n[!] API Error: {message}")
                return None
            else:
                # Unknown status 0 - treat as no results
                return []
        return None
    except Exception as e:
        print(f"\n[!] Request failed: {str(e)}")
        return None


def fetch_transactions(address: str, chain: str = "ethereum", limit: int = 100):
    params = {
        "module": "account", "action": "txlist", "address": address,
        "startblock": 0, "endblock": 99999999, "page": 1, "offset": limit, "sort": "desc"
    }
    return api_call(chain, params) or []


def fetch_token_transfers(address: str, chain: str = "ethereum", limit: int = 100):
    """Fetch ERC20 token transfers for an address"""
    params = {
        "module": "account", "action": "tokentx", "address": address,
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


def analyze_wallet(address: str, chain: str = "ethereum", limit: int = 100) -> Tuple[pd.DataFrame, List[dict]]:
    """Analyze wallet and return (DataFrame, tx_details_list) for reaction speed analysis"""
    print(f"\n[*] Fetching {limit} transactions on {chain.upper()}...")
    txs = fetch_transactions(address, chain, limit)
    
    # Also fetch token transfers
    print(f"[*] Fetching token transfers...")
    token_txs = fetch_token_transfers(address, chain, limit)
    
    if (not txs or len(txs) == 0) and (not token_txs or len(token_txs) == 0):
        print("[!] No transactions or token transfers found for this address")
        print(f"[!] Check the address on https://etherscan.io/address/{address}")
        return pd.DataFrame(), []
    
    # Merge and sort all transactions by timestamp
    all_txs = []
    if txs:
        for tx in txs:
            tx["_type"] = "regular"
            all_txs.append(tx)
    if token_txs:
        for tx in token_txs:
            tx["_type"] = "token"
            all_txs.append(tx)
    
    # Sort by timestamp (oldest first for analysis)
    all_txs.sort(key=lambda x: int(x.get("timeStamp", 0)))
    
    print(f"[+] Found {len(all_txs)} total transactions ({len(txs) if txs else 0} regular, {len(token_txs) if token_txs else 0} token)\n")
    
    transactions = []
    tx_details_list = []
    
    for idx, tx in enumerate(all_txs):
        bar = '#' * int((idx+1)/len(all_txs)*40) + '.' * (40-int((idx+1)/len(all_txs)*40))
        print(f"\r    [{bar}] {idx+1}/{len(all_txs)}", end="", flush=True)
        
        try:
            timestamp = int(tx.get("timeStamp", 0))
            if not timestamp: continue
            utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            tx_type = tx.get("_type", "regular")
            
            if tx_type == "regular":
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
            else:
                # Token transfer - add to transactions for analysis
                gas_used = 65000  # Typical ERC20 transfer gas
                
                transactions.append({
                    "hash": tx.get("hash", ""),
                    "timestamp": utc_time,
                    "hour": utc_time.hour,
                    "day_of_week": utc_time.weekday(),
                    "gas_used": gas_used,
                    "gas_price_gwei": 0,
                    "tx_fee_eth": 0,
                    "value_eth": 0,
                    "is_outgoing": tx.get("from", "").lower() == address.lower(),
                    "is_contract": True,
                    "success": True,
                    "tx_type": "ERC20 Transfer",
                    "to": tx.get("to", ""),
                    "from": tx.get("from", ""),
                })
            
            # Store raw tx data for reaction speed analysis
            tx_details_list.append({
                "timestamp": timestamp,
                "details": tx
            })
        except: continue
    
    print(f"\n[+] Analyzed {len(transactions)} transactions\n")
    return pd.DataFrame(transactions), tx_details_list


def has_token_receive(tx_details: dict, wallet: str) -> bool:
    """Check if transaction involves receiving ETH/tokens"""
    if not tx_details:
        return False
    
    try:
        wallet_lower = wallet.lower()
        tx_type = tx_details.get("_type", "regular")
        
        if tx_type == "token":
            # Token transfer - check if wallet is the "to" address
            tx_to = tx_details.get("to", "").lower()
            if tx_to == wallet_lower:
                return True
        else:
            # Regular transaction - check for native ETH receive
            tx_to = tx_details.get("to", "").lower()
            value = int(tx_details.get("value", 0))
            
            if tx_to == wallet_lower and value > 0:
                return True
        
    except Exception:
        pass
    
    return False


def has_token_action(tx_details: dict, wallet: str) -> bool:
    """Check if transaction involves sending/swapping tokens (wallet initiated)"""
    if not tx_details:
        return False
    
    try:
        wallet_lower = wallet.lower()
        tx_type = tx_details.get("_type", "regular")
        
        if tx_type == "token":
            # Token transfer - check if wallet is the "from" address (sending tokens)
            tx_from = tx_details.get("from", "").lower()
            if tx_from == wallet_lower:
                return True
        else:
            # Regular transaction - wallet initiated (is the "from" address)
            tx_from = tx_details.get("from", "").lower()
            if tx_from == wallet_lower:
                # Check if it's a contract interaction or sending ETH
                input_data = tx_details.get("input", "0x")
                value = int(tx_details.get("value", 0))
                is_contract_call = input_data != "0x" and len(input_data) > 10
                
                if value > 0 or is_contract_call:
                    return True
        
    except Exception:
        pass
    
    return False


def analyze_reaction_speed(wallet: str, tx_details_list: list) -> ReactionSpeedAnalysis:
    """
    Analyze reaction speed between token receives and subsequent actions.
    Bot Detection Logic: Humans take time to think (>30s), Bots react instantly (<5s)
    """
    print(f"\n[*] Analyzing reaction speed for bot detection...")
    
    if not tx_details_list:
        return ReactionSpeedAnalysis()
    
    # Sort by timestamp (oldest first)
    transactions = sorted(tx_details_list, key=lambda x: x["timestamp"])
    
    reaction_times = []
    instant_count = 0
    fast_count = 0
    human_count = 0
    
    total_transactions = len(transactions)
    
    # Look for receive -> action patterns (not necessarily consecutive)
    # For each receive, find the next action within 1 hour
    for i in range(total_transactions):
        # Show progress
        if i % 20 == 0 or i == total_transactions - 1:
            progress = (i + 1) / total_transactions
            bar_len = 30
            filled = int(bar_len * progress)
            bar = '#' * filled + '.' * (bar_len - filled)
            print(f"\r    [{bar}] {i + 1}/{total_transactions}", end="", flush=True)
        
        current_tx = transactions[i]
        current_has_receive = has_token_receive(current_tx["details"], wallet)
        
        # If this is a receive, look for the next action
        if current_has_receive:
            # Look ahead for the next action within 1 hour (3600 seconds)
            for j in range(i + 1, total_transactions):
                next_tx = transactions[j]
                
                # Calculate time delta in seconds
                time_delta = next_tx["timestamp"] - current_tx["timestamp"]
                
                # Only consider actions within 1 hour for reaction speed analysis
                if time_delta > 3600:
                    break  # Too far apart, stop looking
                
                next_has_action = has_token_action(next_tx["details"], wallet)
                
                if next_has_action:
                    reaction_times.append(time_delta)
                    
                    if time_delta < 5:
                        instant_count += 1
                    elif time_delta < 30:
                        fast_count += 1
                    else:
                        human_count += 1
                    
                    break  # Found an action, move to next receive
    
    print()  # New line after progress bar
    
    # Calculate metrics
    total_reactions = len(reaction_times)
    
    if total_reactions == 0:
        return ReactionSpeedAnalysis()
    
    avg_reaction = sum(reaction_times) / total_reactions
    median_reaction = sorted(reaction_times)[total_reactions // 2] if total_reactions > 0 else 0
    fastest_reaction = min(reaction_times) if reaction_times else 0
    
    # Bot confidence calculation
    instant_ratio = instant_count / total_reactions
    fast_ratio = fast_count / total_reactions
    human_ratio = human_count / total_reactions
    
    # High confidence bot if mostly instant reactions
    if instant_ratio > 0.7:
        bot_confidence = 95.0
    elif instant_ratio > 0.5:
        bot_confidence = 85.0
    elif instant_ratio + fast_ratio > 0.7:
        bot_confidence = 70.0
    elif avg_reaction < 10:
        bot_confidence = 60.0
    elif avg_reaction < 30:
        bot_confidence = 40.0
    else:
        bot_confidence = max(0, 30 - (human_ratio * 40))
    
    print(f"[+] Analyzed {total_reactions} reaction patterns")
    
    return ReactionSpeedAnalysis(
        bot_confidence=bot_confidence,
        avg_reaction_time=avg_reaction,
        median_reaction_time=median_reaction,
        fastest_reaction=fastest_reaction,
        instant_reactions=instant_count,
        fast_reactions=fast_count,
        human_reactions=human_count,
        total_reaction_pairs=total_reactions
    )


def detect_sleep_window(hourly_counts: list) -> SleepWindow:
    min_sum, sleep_start = float('inf'), 0
    total_tx = sum(hourly_counts)
    for i in range(24):
        window_sum = sum(hourly_counts[(i + j) % 24] for j in range(6))
        if window_sum < min_sum:
            min_sum, sleep_start = window_sum, i
    confidence = max(0, min(100, (1 - (min_sum / total_tx if total_tx else 0) * 4) * 100))
    return SleepWindow(sleep_start, (sleep_start + 6) % 24, min_sum, confidence)


def calculate_probabilities(df: pd.DataFrame, hourly_counts: list, daily_counts: list, sleep: SleepWindow, reaction: ReactionSpeedAnalysis) -> ProfileProbabilities:
    probs = ProfileProbabilities()
    total_tx = len(df)
    if total_tx == 0: return probs
    
    outgoing = df[df["is_outgoing"] == True]
    hourly_std = np.std(hourly_counts)
    hourly_range = max(hourly_counts) - min(hourly_counts)
    
    # Bot detection - combine sleep pattern and reaction speed
    sleep_bot_score = 0
    if hourly_range < 3: sleep_bot_score = 90
    elif hourly_range < 5: sleep_bot_score = 65
    elif sleep.activity_during_sleep > total_tx * 0.2: sleep_bot_score = 55
    else: sleep_bot_score = max(0, 25 - sleep.confidence * 0.25)
    
    # Combine sleep pattern and reaction speed bot scores
    probs.bot = max(sleep_bot_score, reaction.bot_confidence)
    
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


def print_report(df, address, chain, probs, sleep, reaction: ReactionSpeedAnalysis):
    outgoing = df[df["is_outgoing"] == True]
    geo = {"EU": probs.eu_trader, "US": probs.us_trader, "Asia": probs.asia_trader}
    top_geo = max(geo, key=geo.get)
    
    print("\n" + "="*70)
    print(" GATOR EVM INTELLIGENCE DOSSIER")
    print("="*70)
    print(f" Target: {address}")
    print(f" Chain:  {chain.upper()}")
    print(f" Txs:    {len(df)} ({len(outgoing)} outgoing)")
    print("-"*70)
    print(f"\n Entity:     {'BOT' if probs.bot > 60 else 'HUMAN'} ({max(probs.bot, 100-probs.bot):.0f}%)")
    print(f" Sleep Pattern: {probs.bot:.1f}% bot confidence")
    print(f" Reaction Speed: {reaction.bot_confidence:.1f}% bot confidence")
    print(f" Location:   {top_geo} ({geo[top_geo]:.0f}%)")
    print(f" Sleep:      {sleep.start_hour}:00-{sleep.end_hour}:00 UTC")
    print(f" Whale:      {probs.whale:.0f}%")
    print(f" Degen:      {probs.degen:.0f}%")
    if len(outgoing) > 0:
        print(f" Avg Gas:    {outgoing['gas_used'].mean():,.0f}")
        print(f" Total ETH:  {outgoing['value_eth'].sum():.4f}")
    
    # Reaction Speed Analysis
    print("\n REACTION SPEED ANALYSIS (Bot Detection)")
    print("-"*70)
    if reaction.total_reaction_pairs == 0:
        print(" No Reaction Patterns Detected")
        print(" (Requires consecutive token receive→action sequences)")
    else:
        print(f" Reaction Pairs:     {reaction.total_reaction_pairs}")
        print(f" Avg Reaction:       {reaction.avg_reaction_time:.2f}s")
        print(f" Median Reaction:    {reaction.median_reaction_time:.2f}s")
        print(f" Fastest Reaction:   {reaction.fastest_reaction:.2f}s")
        print(f" Instant (<5s):      {reaction.instant_reactions} ({reaction.instant_reactions/reaction.total_reaction_pairs*100:.1f}%)")
        print(f" Fast (5-30s):       {reaction.fast_reactions} ({reaction.fast_reactions/reaction.total_reaction_pairs*100:.1f}%)")
        print(f" Human (>30s):       {reaction.human_reactions} ({reaction.human_reactions/reaction.total_reaction_pairs*100:.1f}%)")
        print(f" Bot Confidence:    {reaction.bot_confidence:.1f}%")
        if reaction.bot_confidence > 60:
            print(f" [WARNING] HIGH BOT PROBABILITY: Average reaction {reaction.avg_reaction_time:.1f}s")
        else:
            print(f" [OK] HUMAN-LIKE BEHAVIOR: Average reaction {reaction.avg_reaction_time:.1f}s")
    
    print("="*70 + "\n")


def visualize_profile(df, address, chain, probs, sleep, reaction: ReactionSpeedAnalysis):
    outgoing = df[df["is_outgoing"] == True]
    hourly = [0]*24
    daily = [0]*7
    for _, r in outgoing.iterrows():
        hourly[r["hour"]] += 1
        daily[r["day_of_week"]] += 1
    
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 12))  # Increased size for reaction speed panel
    fig.patch.set_facecolor('#0a0a0a')
    
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
    
    fig.suptitle(f"GATOR PROFILE — {address[:10]}...{address[-4:]} ({chain.upper()})", 
                 color='#22c55e', fontsize=16, fontweight='bold', y=0.98)
    
    # Probabilities
    ax1 = fig.add_subplot(3, 2, 1)
    ax1.set_facecolor(panel_color)
    cats = ['Bot', 'MEV', 'EU', 'US', 'Asia', 'Retail', 'Pro', 'Whale', 'Degen']
    vals = [probs.bot, probs.mev_bot, probs.eu_trader, probs.us_trader, probs.asia_trader, 
            probs.retail_hobbyist, probs.professional, probs.whale, probs.degen]
    bar_colors = [accent_purple, accent_cyan, accent_cyan, accent_cyan, accent_cyan,
                  accent_yellow, accent_yellow, accent_green, accent_red]
    bars = ax1.barh(cats, vals, color=bar_colors, alpha=0.7, edgecolor='white', linewidth=0.5)
    for bar, val in zip(bars, vals):
        ax1.text(val + 1, bar.get_y() + bar.get_height()/2, f'{val:.1f}%',
                 va='center', ha='left', color='white', fontsize=9)
    ax1.set_xlim(0, 110)
    ax1.set_title("PROFILE PROBABILITIES", color=accent_purple, fontsize=12, fontweight='bold', loc='left')
    ax1.set_xlabel("Probability (%)", color=text_color)
    ax1.tick_params(colors=text_color)
    ax1.grid(True, alpha=0.2, color=grid_color, axis='x')
    ax1.invert_yaxis()
    
    # Circadian
    ax2 = fig.add_subplot(3, 2, 2)
    ax2.set_facecolor(panel_color)
    colors = [accent_red if sleep.start_hour <= i < sleep.start_hour+6 else accent_cyan for i in range(24)]
    ax2.bar(range(24), hourly, color=colors, alpha=0.7, edgecolor='white', linewidth=0.3)
    ax2.set_title("CIRCADIAN RHYTHM (UTC)", color=accent_cyan, fontsize=11, fontweight='bold', loc='left')
    ax2.set_xlabel("Hour (UTC)", color=text_color)
    ax2.set_ylabel("Transactions", color=text_color)
    ax2.set_xticks(range(0, 24, 4))
    ax2.tick_params(colors=text_color)
    ax2.grid(True, alpha=0.2, color=grid_color, axis='y')
    
    # Weekly
    ax3 = fig.add_subplot(3, 2, 3)
    ax3.set_facecolor(panel_color)
    ax3.bar(['M','T','W','T','F','S','S'], daily, color=[accent_cyan]*5+[accent_yellow]*2, alpha=0.7, edgecolor='white', linewidth=0.3)
    ax3.set_title("WEEKLY PATTERN", color=accent_yellow, fontsize=11, fontweight='bold', loc='left')
    ax3.set_ylabel("Transactions", color=text_color)
    ax3.tick_params(colors=text_color)
    ax3.grid(True, alpha=0.2, color=grid_color, axis='y')
    
    # Gas scatter
    ax4 = fig.add_subplot(3, 2, 4)
    ax4.set_facecolor(panel_color)
    if len(outgoing) > 0:
        colors_scatter = [get_gas_color(g) for g in outgoing["gas_used"]]
        ax4.scatter(outgoing["hour"], outgoing["gas_used"], c=colors_scatter, alpha=0.7, s=30)
    ax4.set_title("GAS COMPLEXITY", color=accent_orange, fontsize=11, fontweight='bold', loc='left')
    ax4.set_xlabel("Hour (UTC)", color=text_color)
    ax4.set_ylabel("Gas Used", color=text_color)
    ax4.tick_params(colors=text_color)
    ax4.grid(True, alpha=0.2, color=grid_color)
    
    # Reaction Speed Analysis Panel
    ax5 = fig.add_subplot(3, 2, (5, 6))  # Spans bottom row
    ax5.set_facecolor(panel_color)
    
    if reaction.total_reaction_pairs > 0:
        categories = ['Instant (<5s)', 'Fast (5-30s)', 'Human (>30s)']
        counts = [reaction.instant_reactions, reaction.fast_reactions, reaction.human_reactions]
        bar_colors_react = [accent_red, accent_orange, accent_green]
        
        bars = ax5.bar(categories, counts, color=bar_colors_react, alpha=0.7, edgecolor='white', linewidth=1)
        
        # Add counts on bars
        max_count = max(counts) if counts else 1
        for bar, count in zip(bars, counts):
            if count > 0:
                percentage = (count / reaction.total_reaction_pairs) * 100
                text_y = bar.get_height() + max_count * 0.05
                ax5.text(bar.get_x() + bar.get_width()/2, text_y,
                        f'{count}\n({percentage:.1f}%)', ha='center', va='bottom', 
                        color='white', fontsize=10, fontweight='bold')
        
        # Add metrics text box
        metrics_text = f"Bot Confidence: {reaction.bot_confidence:.1f}%\n"
        metrics_text += f"Avg: {reaction.avg_reaction_time:.1f}s\n"
        metrics_text += f"Median: {reaction.median_reaction_time:.1f}s\n"
        metrics_text += f"Fastest: {reaction.fastest_reaction:.1f}s"
        
        # Color code based on bot confidence
        if reaction.bot_confidence > 70:
            box_color = accent_red
            verdict = "[WARNING] HIGH BOT"
        elif reaction.bot_confidence < 30:
            box_color = accent_green
            verdict = "[OK] HUMAN-LIKE"
        else:
            box_color = accent_orange
            verdict = "[MIXED]"
        
        ax5.text(0.98, 0.98, f"{verdict}\n{metrics_text}", transform=ax5.transAxes, 
                ha='right', va='top', color='white', fontsize=9,
                bbox=dict(boxstyle='round', facecolor=panel_color, edgecolor=box_color, 
                         linewidth=2, alpha=0.9, pad=0.5))
        
        ax5.set_title("REACTION SPEED ANALYSIS (Bot Detection)", 
                     color=accent_purple, fontsize=12, fontweight='bold', loc='left', pad=8)
        ax5.set_ylabel("Count", color=text_color, fontsize=10)
        ax5.set_ylim(0, max_count * 1.3 if max_count > 0 else 10)
        ax5.tick_params(colors=text_color, labelsize=9)
        ax5.grid(True, alpha=0.2, color=grid_color, axis='y')
    else:
        # No reaction data
        ax5.text(0.5, 0.5, "No Reaction Patterns Detected\n\n(Requires consecutive token receive→action sequences)", 
                transform=ax5.transAxes, ha='center', va='center', 
                color=text_color, fontsize=11, style='italic')
        ax5.set_title("REACTION SPEED ANALYSIS", color=accent_purple, 
                     fontsize=12, fontweight='bold', loc='left')
        ax5.set_xticks([])
        ax5.set_yticks([])
    
    plt.tight_layout(rect=[0, 0, 1, 0.98], h_pad=1.5, w_pad=1.0)
    return fig


def find_connections(addresses, chain, limit):
    print(f"\n[*] Analyzing {len(addresses)} wallets...")
    wallet_txs = {}
    for addr in addresses:
        print(f"[-] Fetching {get_label(addr)}...")
        df, _ = analyze_wallet(addr, chain, limit)  # Unpack tuple, ignore tx_details_list
        wallet_txs[addr] = df
    
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
    print("\n" + "="*70)
    print(" GATOR CONNECTION ANALYSIS")
    print("="*70)
    print(f" Chain: {chain.upper()} | Wallets: {len(addresses)} | Connections: {len(connections)}")
    
    if not connections:
        print("\n ❌ No direct connections found")
    else:
        for (a, b), c in sorted(connections.items(), key=lambda x: x[1].tx_count, reverse=True):
            print(f"\n {get_label(a)} ↔ {get_label(b)}")
            print(f"   {c.tx_count} txs | {c.total_value:.4f} ETH")
    print("="*70 + "\n")


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
    
    print("\n    GATOR - EVM OSINT SUITE v1.0\n")
    
    if args.cmd == "profile":
        df, tx_details_list = analyze_wallet(args.address, args.chain, args.limit)
        if df.empty:
            print("[!] No data"); sys.exit(1)
        
        out = df[df["is_outgoing"]==True]
        hourly, daily = [0]*24, [0]*7
        for _, r in out.iterrows():
            hourly[r["hour"]] += 1
            daily[r["day_of_week"]] += 1
        
        sleep = detect_sleep_window(hourly)
        reaction = analyze_reaction_speed(args.address, tx_details_list)
        probs = calculate_probabilities(df, hourly, daily, sleep, reaction)
        print_report(df, args.address, args.chain, probs, sleep, reaction)
        
        df.to_csv(f"gator_{args.address[:10]}.csv", index=False)
        
        if not args.no_plot:
            fig = visualize_profile(df, args.address, args.chain, probs, sleep, reaction)
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
