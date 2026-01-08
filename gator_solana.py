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
import os
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Load API key from environment variable
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
if not HELIUS_API_KEY:
    print("[!] ERROR: HELIUS_API_KEY not found in environment variables")
    print("[!] Please create a .env file with your API key (see .env.example)")
    sys.exit(1)

RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
DEFAULT_LIMIT = 100

# Configure stdout encoding for Windows compatibility
import sys
import io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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
    "ComputeBudget111111111111111111111111111111": "Compute Budget Program",
}

# Jito tip accounts for private execution detection
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvTsszeoPhtUYj9rdag4djXeFQiDmJzTMX",
    "Cw8CFyM9FkoPhlTnrKMhTHqXheqJZNs4Fl31iWBP6UBu",
    "ADuUkR4ykG49feZ5bwhvq0A25pl1QMrBSnXRKKkeoX8q",
    "DttWaMuVvTiduZRNgLcGW9t66tePvm6znsc5tqQZFQk6",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnIzKZ6jJ",
    "DoPtqvycNsD9nuNSqMZ5J1GzV91qfQ4t7x1qF4aPiPce",
]


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


def fetch_transaction_worker(sig: str) -> tuple:
    """Worker function to fetch a single transaction (for parallel execution)"""
    try:
        time.sleep(0.05)  # Small delay to avoid overwhelming the API
        result = fetch_transaction(sig)
        return (sig, result)
    except Exception as e:
        return (sig, None)


def fetch_transactions_parallel(signatures: List[str], max_workers: int = 10) -> Dict[str, Optional[dict]]:
    """
    Fetch multiple transactions in parallel using ThreadPoolExecutor.
    More reliable than batch RPC calls for rate-limited endpoints.
    Returns dict mapping signature -> transaction data
    """
    results = {}
    total_fetched = 0
    
    # Use ThreadPoolExecutor for parallel fetching with controlled concurrency
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_sig = {executor.submit(fetch_transaction_worker, sig): sig for sig in signatures}
        
        # Process completed tasks
        completed = 0
        for future in as_completed(future_to_sig):
            sig, result = future.result()
            results[sig] = result
            if result is not None:
                total_fetched += 1
            
            completed += 1
            if completed % 20 == 0:  # Progress update every 20 transactions
                print(f"\r    [{completed}/{len(signatures)}] fetched...", end="", flush=True)
    
    print(f"\r    [+] Successfully fetched {total_fetched}/{len(signatures)} transactions")
    return results


def get_label(address: str) -> str:
    """Get human-readable label for an address"""
    return KNOWN_LABELS.get(address, address[:8] + "..." + address[-4:])


# ═══════════════════════════════════════════════════════════════════════════════
# MEMPOOL FORENSICS - Priority Fee & Execution Style Detection
# ═══════════════════════════════════════════════════════════════════════════════

def parse_compute_budget_instruction(instruction_data: bytes) -> dict:
    """
    Parse Compute Budget instruction to extract priority fee and compute unit limit.
    Returns dict with 'priority_fee_microlamports' and 'compute_unit_limit' or None.
    """
    if not instruction_data or len(instruction_data) < 1:
        return None
    
    # Compute Budget instruction discriminator (first byte)
    # 2 = SetComputeUnitLimit, 3 = SetComputeUnitPrice (priority fee)
    try:
        if len(instruction_data) >= 5:
            discriminator = instruction_data[0]
            
            if discriminator == 2:  # SetComputeUnitLimit
                # Next 4 bytes are u32 compute unit limit
                if len(instruction_data) >= 5:
                    cu_limit = int.from_bytes(instruction_data[1:5], byteorder='little')
                    return {"compute_unit_limit": cu_limit}
            
            elif discriminator == 3:  # SetComputeUnitPrice (priority fee)
                # Next 8 bytes are u64 priority fee in microlamports
                if len(instruction_data) >= 9:
                    priority_fee = int.from_bytes(instruction_data[1:9], byteorder='little')
                    return {"priority_fee_microlamports": priority_fee}
    except:
        pass
    
    return None


def detect_jito_tip(tx_details: dict) -> Tuple[bool, float]:
    """
    Detect if transaction includes Jito tip (private execution indicator).
    Returns (has_jito_tip, tip_amount_sol).
    """
    if not tx_details or not tx_details.get("meta"):
        return False, 0.0
    
    try:
        meta = tx_details["meta"]
        msg = tx_details.get("transaction", {}).get("message", {})
        
        # Get all account keys
        account_keys = msg.get("accountKeys", [])
        if isinstance(account_keys, list) and len(account_keys) > 0:
            # Handle both string and dict formats
            accounts = []
            for key in account_keys:
                if isinstance(key, dict):
                    accounts.append(key.get("pubkey", ""))
                else:
                    accounts.append(str(key))
        else:
            accounts = []
        
        # Check pre/post balances for Jito tip accounts
        pre_balances = meta.get("preBalances", [])
        post_balances = meta.get("postBalances", [])
        
        for i, account in enumerate(accounts):
            if i < len(pre_balances) and i < len(post_balances):
                if account in JITO_TIP_ACCOUNTS:
                    tip_lamports = post_balances[i] - pre_balances[i]
                    if tip_lamports > 0:
                        return True, tip_lamports / 1e9  # Convert to SOL
    except:
        pass
    
    return False, 0.0


def analyze_execution_profile(tx_details: dict) -> dict:
    """
    Analyze transaction for execution profile classification.
    Returns dict with execution_profile, priority_fee, compute_unit_limit, jito_tip, etc.
    """
    result = {
        "execution_profile": "RETAIL",
        "priority_fee_microlamports": 0,
        "compute_unit_limit": None,
        "has_jito_tip": False,
        "jito_tip_sol": 0.0,
        "indicators": []
    }
    
    if not tx_details:
        return result
    
    try:
        msg = tx_details.get("transaction", {}).get("message", {})
        instructions = msg.get("instructions", [])
        account_keys = msg.get("accountKeys", [])
        
        # Normalize account keys format
        accounts = []
        for key in account_keys:
            if isinstance(key, dict):
                accounts.append(key.get("pubkey", ""))
            else:
                accounts.append(str(key))
        
        # Parse instructions for Compute Budget
        compute_budget_program = "ComputeBudget111111111111111111111111111111"
        max_priority_fee = 0
        max_cu_limit = None
        
        for ix in instructions:
            if isinstance(ix, dict):
                # Handle both parsed and unparsed instruction formats
                program_id_index = ix.get("programIdIndex")
                program_id_str = ix.get("programId")
                
                # Determine program ID
                if program_id_str:
                    program_id = program_id_str
                elif program_id_index is not None and program_id_index < len(accounts):
                    program_id = accounts[program_id_index]
                else:
                    continue
                
                if program_id == compute_budget_program:
                    # Parse instruction data
                    ix_data = ix.get("data")
                    parsed_data = ix.get("parsed")
                    
                    # Try parsed format first (jsonParsed encoding)
                    if parsed_data:
                        parsed_type = parsed_data.get("type")
                        if parsed_type == "setComputeUnitPrice":
                            # Priority fee in microlamports
                            fee = int(parsed_data.get("args", {}).get("microLamports", 0))
                            if fee > 0:
                                max_priority_fee = max(max_priority_fee, fee)
                                result["priority_fee_microlamports"] = max_priority_fee
                        elif parsed_type == "setComputeUnitLimit":
                            # Compute unit limit
                            cu_limit = int(parsed_data.get("args", {}).get("units", 0))
                            if cu_limit > 0:
                                if max_cu_limit is None or cu_limit > max_cu_limit:
                                    max_cu_limit = cu_limit
                                    result["compute_unit_limit"] = max_cu_limit
                    
                    # Fallback to raw data parsing
                    elif ix_data:
                        data_bytes = None
                        # Handle base58 or hex encoded data
                        if isinstance(ix_data, str):
                            try:
                                # Try to decode as base58 (Solana standard)
                                try:
                                    import base58
                                    data_bytes = base58.b58decode(ix_data)
                                except ImportError:
                                    # Fallback: try hex if base58 not available
                                    data_bytes = bytes.fromhex(ix_data.replace("0x", ""))
                            except:
                                try:
                                    # Try hex
                                    data_bytes = bytes.fromhex(ix_data.replace("0x", ""))
                                except:
                                    continue
                        elif isinstance(ix_data, list):
                            data_bytes = bytes(ix_data)
                        
                        if data_bytes:
                            budget_data = parse_compute_budget_instruction(data_bytes)
                            if budget_data:
                                if "priority_fee_microlamports" in budget_data:
                                    fee = budget_data["priority_fee_microlamports"]
                                    max_priority_fee = max(max_priority_fee, fee)
                                    result["priority_fee_microlamports"] = max_priority_fee
                                
                                if "compute_unit_limit" in budget_data:
                                    cu_limit = budget_data["compute_unit_limit"]
                                    if max_cu_limit is None or cu_limit > max_cu_limit:
                                        max_cu_limit = cu_limit
                                        result["compute_unit_limit"] = max_cu_limit
        
        # Check for Jito tip
        has_jito, jito_tip = detect_jito_tip(tx_details)
        result["has_jito_tip"] = has_jito
        result["jito_tip_sol"] = jito_tip
        
        # Classify execution profile
        if has_jito and jito_tip > 0:
            result["execution_profile"] = "MEV_STYLE"
            result["indicators"].append(f"Jito tip: {jito_tip:.6f} SOL")
        elif max_priority_fee > 1000000 or (max_cu_limit and max_cu_limit > 1400000):
            # High priority fee (>1M microlamports) or very high CU limit indicates urgent/pro trader
            if max_priority_fee > 1000000:
                result["execution_profile"] = "URGENT_USER"
                result["indicators"].append(f"High priority fee: {max_priority_fee/1e6:.2f}M microlamports")
            if max_cu_limit and max_cu_limit > 1400000:
                result["execution_profile"] = "PRO_TRADER"
                result["indicators"].append(f"High CU limit: {max_cu_limit:,}")
        elif max_priority_fee > 100000 or (max_cu_limit and max_cu_limit > 200000):
            # Moderate priority indicates urgent user
            result["execution_profile"] = "URGENT_USER"
            if max_priority_fee > 100000:
                result["indicators"].append(f"Moderate priority fee: {max_priority_fee/1e6:.2f}M microlamports")
        else:
            result["execution_profile"] = "RETAIL"
            if max_priority_fee > 0:
                result["indicators"].append(f"Low priority fee: {max_priority_fee/1e6:.3f}M microlamports")
            else:
                result["indicators"].append("No priority fee set")
    
    except Exception as e:
        result["indicators"].append(f"Analysis error: {str(e)}")
    
    return result


def analyze_wallet_execution_profiles(wallet: str, limit: int = 100) -> dict:
    """
    Analyze wallet's execution profiles across multiple transactions.
    Returns JSON-serializable dict with aggregated execution profile statistics.
    """
    signatures = fetch_signatures(wallet, limit)
    
    if not signatures:
        return {
            "wallet": wallet,
            "total_transactions": 0,
            "profiles": {},
            "aggregate_profile": "UNKNOWN"
        }
    
    profile_counts = {"RETAIL": 0, "URGENT_USER": 0, "PRO_TRADER": 0, "MEV_STYLE": 0}
    total_priority_fee = 0
    total_jito_tips = 0.0
    jito_tip_count = 0
    
    # Fetch all transactions in parallel
    sig_strings = [sig_info["signature"] for sig_info in signatures]
    tx_details_map = fetch_transactions_parallel(sig_strings, max_workers=10)
    
    for sig_info in signatures:
        signature = sig_info["signature"]
        tx_details = tx_details_map.get(signature)
        
        if tx_details:
            profile_data = analyze_execution_profile(tx_details)
            profile = profile_data["execution_profile"]
            profile_counts[profile] = profile_counts.get(profile, 0) + 1
            
            if profile_data["priority_fee_microlamports"] > 0:
                total_priority_fee += profile_data["priority_fee_microlamports"]
            
            if profile_data["has_jito_tip"]:
                total_jito_tips += profile_data["jito_tip_sol"]
                jito_tip_count += 1
    
    total_tx = len(signatures)
    
    # Determine aggregate profile
    if profile_counts["MEV_STYLE"] > total_tx * 0.3:
        aggregate = "MEV_STYLE"
    elif profile_counts["PRO_TRADER"] > total_tx * 0.3:
        aggregate = "PRO_TRADER"
    elif profile_counts["URGENT_USER"] > total_tx * 0.3:
        aggregate = "URGENT_USER"
    else:
        aggregate = "RETAIL"
    
    return {
        "wallet": wallet,
        "total_transactions": total_tx,
        "profiles": {
            "RETAIL": profile_counts["RETAIL"],
            "URGENT_USER": profile_counts["URGENT_USER"],
            "PRO_TRADER": profile_counts["PRO_TRADER"],
            "MEV_STYLE": profile_counts["MEV_STYLE"]
        },
        "profile_percentages": {
            "RETAIL": round((profile_counts["RETAIL"] / total_tx * 100) if total_tx > 0 else 0, 2),
            "URGENT_USER": round((profile_counts["URGENT_USER"] / total_tx * 100) if total_tx > 0 else 0, 2),
            "PRO_TRADER": round((profile_counts["PRO_TRADER"] / total_tx * 100) if total_tx > 0 else 0, 2),
            "MEV_STYLE": round((profile_counts["MEV_STYLE"] / total_tx * 100) if total_tx > 0 else 0, 2)
        },
        "aggregate_profile": aggregate,
        "statistics": {
            "avg_priority_fee_microlamports": round(total_priority_fee / total_tx if total_tx > 0 else 0, 2),
            "total_jito_tips_sol": round(total_jito_tips, 6),
            "jito_tip_count": jito_tip_count,
            "jito_tip_percentage": round((jito_tip_count / total_tx * 100) if total_tx > 0 else 0, 2)
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILE COMMAND - Single Wallet Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_wallet(wallet: str, limit: int = 100) -> tuple:
    """Fetch and analyze wallet transactions - returns (DataFrame, tx_details_list)"""
    print(f"\n[*] Fetching last {limit} transactions...")
    
    signatures = fetch_signatures(wallet, limit)
    
    if not signatures:
        return pd.DataFrame(), []
    
    print(f"[+] Found {len(signatures)} transactions")
    print(f"[-] Analyzing details...\n")
    
    # Extract signature strings for batch fetching
    sig_strings = [sig_info["signature"] for sig_info in signatures]
    
    # Fetch transactions in parallel (faster and more reliable)
    print(f"    [*] Fetching {len(sig_strings)} transactions in parallel...")
    tx_details_map = fetch_transactions_parallel(sig_strings, max_workers=10)
    
    # Check if batch fetch worked - if too many failures, warn user
    valid_results = sum(1 for v in tx_details_map.values() if v is not None)
    if valid_results < len(sig_strings) * 0.5:
        print(f"    [!] Warning: Only {valid_results}/{len(sig_strings)} transactions fetched successfully")
        print(f"    [!] Some data may be incomplete (RPC connection issues)")
    
    print()
    
    transactions = []
    tx_details_list = []
    
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
        
        tx_details = tx_details_map.get(signature)
        
        # Skip if transaction details couldn't be fetched
        if not tx_details:
            continue
        
        compute_units = 0
        fee = 0
        instructions = 0
        
        if tx_details.get("meta"):
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
            "slot": sig_info.get("slot", 0),
            "block_time": block_time
        })
        
        # Store tx details for reaction speed analysis (only if valid)
        tx_details_list.append({
            "timestamp": block_time,
            "details": tx_details
        })
    
    print(f"\n[+] Analyzed {len(transactions)} transactions\n")
    
    return pd.DataFrame(transactions), tx_details_list


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
    
    total_pairs = len(transactions) - 1
    
    # Analyze consecutive transactions for reaction patterns
    for i in range(total_pairs):
        # Show progress
        if i % 10 == 0 or i == total_pairs - 1:
            progress = (i + 1) / total_pairs
            bar_len = 30
            filled = int(bar_len * progress)
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"\r    [{bar}] {i + 1}/{total_pairs} pairs", end="", flush=True)
        
        current_tx = transactions[i]
        next_tx = transactions[i + 1]
        
        # Calculate time delta in seconds
        time_delta = next_tx["timestamp"] - current_tx["timestamp"]
        
        # Check if current transaction involves receiving tokens
        # and next transaction involves sending/swapping
        current_has_receive = has_token_receive(current_tx["details"], wallet)
        next_has_action = has_token_action(next_tx["details"], wallet)
        
        # If pattern detected: receive -> action
        if current_has_receive and next_has_action and time_delta <= 300:  # Within 5 minutes
            reaction_times.append(time_delta)
            
            if time_delta < 5:
                instant_count += 1
            elif time_delta < 30:
                fast_count += 1
            else:
                human_count += 1
    
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


def has_token_receive(tx_details: dict, wallet: str) -> bool:
    """Check if transaction involves receiving tokens"""
    if not tx_details or not tx_details.get("meta"):
        return False
    
    try:
        # Check post token balances - if balance increased, tokens were received
        post_balances = tx_details["meta"].get("postTokenBalances", [])
        pre_balances = tx_details["meta"].get("preTokenBalances", [])
        
        # Create a map of pre-balances
        pre_balance_map = {}
        for balance in pre_balances:
            owner = balance.get("owner")
            if owner == wallet:
                mint = balance.get("mint", "")
                amount = float(balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                pre_balance_map[mint] = amount
        
        # Check if any post-balance increased
        for balance in post_balances:
            owner = balance.get("owner")
            if owner == wallet:
                mint = balance.get("mint", "")
                post_amount = float(balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                pre_amount = pre_balance_map.get(mint, 0)
                
                if post_amount > pre_amount:
                    return True
        
        # Also check SOL balance increase
        account_keys = tx_details.get("transaction", {}).get("message", {}).get("accountKeys", [])
        pre_sol = tx_details["meta"].get("preBalances", [])
        post_sol = tx_details["meta"].get("postBalances", [])
        
        for idx, key in enumerate(account_keys):
            addr = key.get("pubkey", "") if isinstance(key, dict) else str(key)
            if addr == wallet and idx < len(pre_sol) and idx < len(post_sol):
                if post_sol[idx] > pre_sol[idx]:
                    return True
        
    except Exception:
        pass
    
    return False


def has_token_action(tx_details: dict, wallet: str) -> bool:
    """Check if transaction involves sending/swapping tokens"""
    if not tx_details or not tx_details.get("meta"):
        return False
    
    try:
        # Check if wallet initiated the transaction (is signer)
        account_keys = tx_details.get("transaction", {}).get("message", {}).get("accountKeys", [])
        
        for key in account_keys:
            addr = key.get("pubkey", "") if isinstance(key, dict) else str(key)
            is_signer = key.get("signer", False) if isinstance(key, dict) else False
            
            if addr == wallet and is_signer:
                # Check if tokens were sent (balance decreased)
                post_balances = tx_details["meta"].get("postTokenBalances", [])
                pre_balances = tx_details["meta"].get("preTokenBalances", [])
                
                # Create a map of pre-balances
                pre_balance_map = {}
                for balance in pre_balances:
                    owner = balance.get("owner")
                    if owner == wallet:
                        mint = balance.get("mint", "")
                        amount = float(balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                        pre_balance_map[mint] = amount
                
                # Check if any balance decreased
                for balance in post_balances:
                    owner = balance.get("owner")
                    if owner == wallet:
                        mint = balance.get("mint", "")
                        post_amount = float(balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                        pre_amount = pre_balance_map.get(mint, 0)
                        
                        if post_amount < pre_amount:
                            return True
                
                # Also check SOL balance decrease (excluding fees)
                pre_sol = tx_details["meta"].get("preBalances", [])
                post_sol = tx_details["meta"].get("postBalances", [])
                fee = tx_details["meta"].get("fee", 0)
                
                for idx, key2 in enumerate(account_keys):
                    addr2 = key2.get("pubkey", "") if isinstance(key2, dict) else str(key2)
                    if addr2 == wallet and idx < len(pre_sol) and idx < len(post_sol):
                        balance_decrease = pre_sol[idx] - post_sol[idx]
                        # If decrease is more than just the fee, tokens were sent
                        if balance_decrease > fee * 1.5:  # 1.5x buffer
                            return True
                
                return True  # Is signer, so some action was taken
        
    except Exception:
        pass
    
    return False


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


def visualize_profile(df: pd.DataFrame, wallet: str, probs: ProfileProbabilities, sleep: SleepWindow, reaction: ReactionSpeedAnalysis):
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
    fig = plt.figure(figsize=(16, 16))  # Increased height for reaction speed panel
    
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
    fig.suptitle(f"GATOR PROFILE — {wallet[:12]}...{wallet[-6:]}", 
                 fontsize=16, color=accent_green, fontweight='bold', y=0.98)
    
    # Panel 1: Profile probabilities
    ax0 = fig.add_subplot(5, 2, (1, 2))  # Changed to 5x2 grid
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
    ax1 = fig.add_subplot(5, 2, 3)
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
    ax2 = fig.add_subplot(5, 2, 4)
    ax2.set_facecolor(panel_color)
    
    geo_labels = ['Europe/Africa', 'Americas', 'Asia/Pacific']
    geo_values = [probs.eu_trader, probs.us_trader, probs.asia_trader]
    geo_colors = ['#3b82f6', '#ef4444', '#22c55e']
    
    ax2.pie(geo_values, labels=geo_labels, autopct='%1.1f%%', colors=geo_colors, startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 1}, textprops={'color': 'white', 'fontsize': 9})
    ax2.set_title("GEOGRAPHIC PROBABILITY", color=accent_cyan, fontsize=11, fontweight='bold')
    
    # Panel 4: Weekly routine
    ax3 = fig.add_subplot(5, 2, 5)
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
    ax4 = fig.add_subplot(5, 2, 6)
    ax4.set_facecolor(panel_color)
    
    ax4.pie([probs.retail_hobbyist, probs.professional], labels=['Retail/Hobbyist', 'Professional'],
            autopct='%1.1f%%', colors=[accent_yellow, accent_cyan], startangle=90,
            wedgeprops={'edgecolor': 'white', 'linewidth': 1}, textprops={'color': 'white', 'fontsize': 10})
    ax4.set_title("OCCUPATION PROBABILITY", color=accent_yellow, fontsize=11, fontweight='bold')
    
    # Panel 6: Complexity scatter
    ax5 = fig.add_subplot(5, 2, 7)
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
    ax6 = fig.add_subplot(5, 2, 8)
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
    
    # Panel 8: Reaction Speed Analysis (NEW)
    ax7 = fig.add_subplot(5, 2, (9, 10))  # Spans both columns in row 5
    ax7.set_facecolor(panel_color)
    
    if reaction.total_reaction_pairs > 0:
        # Create data for visualization
        categories = ['Instant\n(<5s)', 'Fast\n(5-30s)', 'Human\n(>30s)']
        counts = [reaction.instant_reactions, reaction.fast_reactions, reaction.human_reactions]
        colors_reaction = [accent_red, accent_orange, accent_green]
        
        # Bar chart of reaction categories
        bars = ax7.bar(categories, counts, color=colors_reaction, alpha=0.7, edgecolor='white', linewidth=1)
        
        # Add counts on bars with better spacing
        max_count = max(counts) if counts else 1
        for bar, count in zip(bars, counts):
            if count > 0:
                percentage = (count / reaction.total_reaction_pairs) * 100
                # Position text higher with more padding
                text_y = bar.get_height() + max_count * 0.05
                ax7.text(bar.get_x() + bar.get_width()/2, text_y,
                        f'{count}\n({percentage:.1f}%)', ha='center', va='bottom', 
                        color='white', fontsize=9, fontweight='bold')
        
        # Add metrics text box with smaller font
        metrics_text = f"Bot: {reaction.bot_confidence:.1f}%\n"
        metrics_text += f"Avg: {reaction.avg_reaction_time:.1f}s\n"
        metrics_text += f"Med: {reaction.median_reaction_time:.1f}s\n"
        metrics_text += f"Min: {reaction.fastest_reaction:.1f}s"
        
        # Color code the text box based on bot confidence
        if reaction.bot_confidence > 70:
            box_color = accent_red
            verdict = "⚠️  HIGH BOT"
        elif reaction.bot_confidence < 30:
            box_color = accent_green
            verdict = "✓ HUMAN-LIKE"
        else:
            box_color = accent_orange
            verdict = "⚡ MIXED"
        
        ax7.text(0.98, 0.98, f"{verdict}\n{metrics_text}", transform=ax7.transAxes, 
                ha='right', va='top', color='white', fontsize=8,
                bbox=dict(boxstyle='round', facecolor=panel_color, edgecolor=box_color, 
                         linewidth=2, alpha=0.9, pad=0.5))
        
        ax7.set_title("REACTION SPEED ANALYSIS", 
                     color=accent_purple, fontsize=11, fontweight='bold', loc='left', pad=8)
        ax7.set_ylabel("Count", color=text_color, fontsize=9)
        # Increase ylim padding for text above bars
        ax7.set_ylim(0, max_count * 1.35 if max_count > 0 else 10)
        ax7.tick_params(colors=text_color, labelsize=8, axis='y')
        ax7.tick_params(colors=text_color, labelsize=9, axis='x')
        ax7.grid(True, alpha=0.2, color=grid_color, axis='y')
        
    else:
        # No reaction data available
        ax7.text(0.5, 0.5, "No Reaction Patterns Detected\n\n(Requires consecutive token receive→action sequences)", 
                transform=ax7.transAxes, ha='center', va='center', 
                color=text_color, fontsize=11, style='italic')
        ax7.set_title("REACTION SPEED ANALYSIS", color=accent_purple, 
                     fontsize=12, fontweight='bold', loc='left')
        ax7.set_xticks([])
        ax7.set_yticks([])
    
    plt.tight_layout(rect=[0, 0, 1, 0.98], h_pad=1.5, w_pad=1.0)
    
    return fig


def print_profile_report(df: pd.DataFrame, wallet: str, probs: ProfileProbabilities, sleep: SleepWindow, reaction: ReactionSpeedAnalysis):
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
    
    # Combine bot detection signals
    combined_bot_score = max(probs.bot, reaction.bot_confidence)
    
    print("\n" + "═" * 70)
    print(" 🐊 GATOR INTELLIGENCE DOSSIER")
    print("═" * 70)
    print(f" Target:            {wallet}")
    print(f" Transactions:      {total_tx}")
    print(f" Period:            {df['timestamp'].min().strftime('%Y-%m-%d %H:%M')} → {df['timestamp'].max().strftime('%Y-%m-%d %H:%M')} UTC")
    print("─" * 70)
    
    print("\n 🤖 ENTITY CLASSIFICATION")
    print("─" * 70)
    if combined_bot_score > 60:
        print(f" ├─ Type:           BOT / AUTOMATED ({combined_bot_score:.1f}%)")
        print(f" ├─ Sleep Pattern:  {probs.bot:.1f}% bot confidence")
        print(f" ├─ Reaction Speed: {reaction.bot_confidence:.1f}% bot confidence")
        print(f" └─ Note:           Automated behavior detected")
    else:
        print(f" ├─ Type:           HUMAN ({100 - combined_bot_score:.1f}%)")
        print(f" ├─ Sleep Window:   {sleep.start_hour}:00 → {sleep.end_hour}:00 UTC")
        print(f" ├─ Confidence:     {sleep.confidence:.1f}%")
        print(f" └─ Reaction Speed: {reaction.bot_confidence:.1f}% bot confidence")
    
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
    
    # Reaction Speed Analysis Section
    if reaction.total_reaction_pairs > 0:
        print("\n REACTION SPEED ANALYSIS (Bot Detection)")
        print("─" * 70)
        print(f" ├─ Reaction Pairs:     {reaction.total_reaction_pairs}")
        print(f" ├─ Avg Reaction:       {reaction.avg_reaction_time:.2f}s")
        print(f" ├─ Median Reaction:    {reaction.median_reaction_time:.2f}s")
        print(f" ├─ Fastest Reaction:   {reaction.fastest_reaction:.2f}s")
        print(f" ├─ Instant (<5s):      {reaction.instant_reactions} ({reaction.instant_reactions/reaction.total_reaction_pairs*100:.1f}%)")
        print(f" ├─ Fast (5-30s):       {reaction.fast_reactions} ({reaction.fast_reactions/reaction.total_reaction_pairs*100:.1f}%)")
        print(f" ├─ Human (>30s):       {reaction.human_reactions} ({reaction.human_reactions/reaction.total_reaction_pairs*100:.1f}%)")
        print(f" └─ Bot Confidence:     {reaction.bot_confidence:.1f}%")
        
        if reaction.bot_confidence > 70:
            print(f"    ⚠️  HIGH BOT PROBABILITY: Average reaction {reaction.avg_reaction_time:.1f}s")
        elif reaction.bot_confidence < 30:
            print(f"    ✓  HUMAN-LIKE BEHAVIOR: Average reaction {reaction.avg_reaction_time:.1f}s")
    
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
        
        # Fetch all transactions in parallel (MUCH FASTER!)
        sig_strings = [sig_info["signature"] for sig_info in signatures]
        tx_details_map = fetch_transactions_parallel(sig_strings, max_workers=10)
        
        for idx, sig_info in enumerate(signatures):
            progress = (idx + 1) / len(signatures)
            bar_len = 30
            filled = int(bar_len * progress)
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"\r    [{bar}] {idx + 1}/{len(signatures)}", end="", flush=True)
            
            signature = sig_info["signature"]
            tx_details = tx_details_map.get(signature)
            
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
    
    ax.set_title("GATOR - Wallet Connection Map", fontsize=14, color='#22c55e', fontweight='bold')
    
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
            
            # Fetch transactions in parallel
            sig_strings = [sig_info["signature"] for sig_info in signatures[:limit]]
            tx_details_map = fetch_transactions_parallel(sig_strings, max_workers=10)
            
            for sig_info in signatures[:limit]:
                tx_details = tx_details_map.get(sig_info["signature"])
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
        df, tx_details_list = analyze_wallet(args.address, args.limit)
        
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
        
        # Analyze reaction speed for bot detection (reuse already-fetched data)
        reaction = analyze_reaction_speed(args.address, tx_details_list)
        
        print_profile_report(df, args.address, probs, sleep, reaction)
        
        csv_path = f"gator_profile_{args.address[:8]}.csv"
        df.to_csv(csv_path, index=False)
        print(f"[+] Data saved: {csv_path}")
        
        if not args.no_plot:
            fig = visualize_profile(df, args.address, probs, sleep, reaction)
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
