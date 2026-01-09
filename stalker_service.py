#!/usr/bin/env python3
"""
Live Wallet Stalker Service
WebSocket-based real-time wallet monitoring for EVM and Solana chains
"""

import asyncio
import json
import os
from typing import Dict, Set, Optional, Callable
from datetime import datetime
from collections import defaultdict
import websockets
from dotenv import load_dotenv

load_dotenv()

# Solana imports
try:
    from solana.rpc.websocket_api import connect as solana_connect
    from solders.pubkey import Pubkey
    from solders.rpc.config import RpcTransactionLogsFilterMentions
    SOLANA_SUPPORTED = True
except ImportError:
    SOLANA_SUPPORTED = False
    print("[!] Warning: Solana support not available (install solana, solders)")

# TODO: Configure RPC WebSocket endpoints per chain
EVM_WSS_ENDPOINTS = {
    "ethereum": "wss://eth-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "base": "wss://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "arbitrum": "wss://arb-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "optimism": "wss://opt-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "polygon": "wss://polygon-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"
}

# Solana RPC WebSocket endpoint
# Prefer explicit override, otherwise fall back to Helius if HELIUS_API_KEY is present.
# NOTE: Never hardcode API keys in source control.
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
SOLANA_WSS_URL = os.getenv("SOLANA_WSS_URL") or (
    f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY else None
)


class WalletStalker:
    """
    Manages live wallet monitoring via WebSocket subscriptions.
    Supports multiple wallets over a single persistent connection per chain.
    """
    
    def __init__(self, chain: str = "ethereum"):
        self.chain = chain
        self.ws_url = EVM_WSS_ENDPOINTS.get(chain)
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        
        # State management
        self.watched_wallets: Set[str] = set()  # Wallets currently being watched
        self.subscription_ids: Dict[str, str] = {}  # wallet -> subscription_id
        self.last_seen_txs: Dict[str, Set[str]] = defaultdict(set)  # wallet -> {tx_hashes}
        self.last_activity: Dict[str, datetime] = {}  # wallet -> last_activity_time
        
        # Callbacks
        self.on_activity: Optional[Callable] = None  # Called when wallet becomes active
        
        # Connection state
        self.connected = False
        self.connection_task = None
        
    async def connect(self):
        """Establish persistent WebSocket connection to EVM RPC"""
        if not self.ws_url:
            raise ValueError(f"No WebSocket endpoint configured for chain: {self.chain}")
        
        try:
            # TODO: Add authentication headers if required by RPC provider
            self.websocket = await websockets.connect(self.ws_url)
            self.connected = True
            print(f"[Stalker] Connected to {self.chain} WebSocket")
            
            # Start listening loop
            self.connection_task = asyncio.create_task(self._listen_loop())
            
        except Exception as e:
            print(f"[Stalker] Connection failed: {e}")
            self.connected = False
            raise
    
    async def disconnect(self):
        """Cleanly close WebSocket connection"""
        self.connected = False
        
        # Unsubscribe all wallets
        for wallet in list(self.watched_wallets):
            await self.unwatch_wallet(wallet)
        
        # Close connection
        if self.websocket:
            await self.websocket.close()
            print(f"[Stalker] Disconnected from {self.chain}")
        
        # Cancel listening task
        if self.connection_task:
            self.connection_task.cancel()
    
    async def watch_wallet(self, wallet_address: str):
        """
        Subscribe to real-time events for a specific wallet address.
        Uses eth_subscribe with logs filter.
        """
        if not self.connected or not self.websocket:
            raise RuntimeError("WebSocket not connected. Call connect() first.")
        
        wallet_address = wallet_address.lower()
        
        if wallet_address in self.watched_wallets:
            print(f"[Stalker] Already watching {wallet_address[:10]}...")
            return
        
        # Subscribe to logs mentioning this address
        # This captures both FROM and TO transactions
        subscription_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": None,  # Any contract
                    "topics": [
                        None,  # Any event signature
                        # Listen for address in any topic position (flexible)
                        # TODO: May need to adjust based on specific event patterns
                    ]
                }
            ]
        }
        
        try:
            await self.websocket.send(json.dumps(subscription_request))
            response = await self.websocket.recv()
            result = json.loads(response)
            
            if "result" in result:
                sub_id = result["result"]
                self.subscription_ids[wallet_address] = sub_id
                self.watched_wallets.add(wallet_address)
                self.last_activity[wallet_address] = datetime.utcnow()
                
                print(f"[Stalker] 👁️  Now watching: {wallet_address[:10]}... (sub: {sub_id})")
                return True
            else:
                print(f"[Stalker] Subscription failed: {result}")
                return False
                
        except Exception as e:
            print(f"[Stalker] Failed to watch wallet: {e}")
            return False
    
    async def unwatch_wallet(self, wallet_address: str):
        """Unsubscribe from wallet events"""
        wallet_address = wallet_address.lower()
        
        if wallet_address not in self.watched_wallets:
            return
        
        sub_id = self.subscription_ids.get(wallet_address)
        if sub_id and self.websocket:
            unsubscribe_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_unsubscribe",
                "params": [sub_id]
            }
            
            try:
                await self.websocket.send(json.dumps(unsubscribe_request))
                await self.websocket.recv()  # Confirmation
            except Exception as e:
                print(f"[Stalker] Unsubscribe error: {e}")
        
        # Clean up state
        self.watched_wallets.discard(wallet_address)
        self.subscription_ids.pop(wallet_address, None)
        self.last_seen_txs.pop(wallet_address, None)
        
        print(f"[Stalker] Stopped watching: {wallet_address[:10]}...")
    
    async def _listen_loop(self):
        """
        Continuous loop that listens for incoming WebSocket messages.
        Processes events and triggers callbacks.
        """
        try:
            while self.connected and self.websocket:
                message = await self.websocket.recv()
                await self._process_message(message)
                
        except websockets.exceptions.ConnectionClosed:
            print("[Stalker] Connection closed")
            self.connected = False
        except asyncio.CancelledError:
            print("[Stalker] Listen loop cancelled")
        except Exception as e:
            print(f"[Stalker] Listen loop error: {e}")
            self.connected = False
    
    async def _process_message(self, message: str):
        """
        Process incoming WebSocket message.
        Detects wallet activity and triggers callbacks.
        """
        try:
            data = json.loads(message)
            
            # Check if this is a subscription notification
            if "method" in data and data["method"] == "eth_subscription":
                params = data.get("params", {})
                result = params.get("result", {})
                
                # Extract transaction hash and address info
                tx_hash = result.get("transactionHash")
                topics = result.get("topics", [])
                address = result.get("address")
                block_number = result.get("blockNumber")
                
                if not tx_hash:
                    return
                
                # Check which watched wallet this event relates to
                # TODO: More sophisticated matching based on topics/address
                for wallet in self.watched_wallets:
                    # Simple check: see if wallet appears in topics or address
                    # EVM addresses in topics are padded to 32 bytes
                    wallet_padded = "0x" + wallet[2:].zfill(64)
                    
                    found_match = False
                    if address and wallet.lower() == address.lower():
                        found_match = True
                    elif any(wallet.lower() in topic.lower() or wallet_padded.lower() == topic.lower() for topic in topics):
                        found_match = True
                    
                    if found_match:
                        await self._handle_wallet_activity(wallet, tx_hash, block_number, result)
                        
        except json.JSONDecodeError:
            pass  # Ignore malformed messages
        except Exception as e:
            print(f"[Stalker] Message processing error: {e}")
    
    async def _handle_wallet_activity(self, wallet: str, tx_hash: str, block_number: str, event_data: dict):
        """
        Handle detected wallet activity with debouncing.
        """
        # Debounce: Skip if we've already seen this transaction
        if tx_hash in self.last_seen_txs[wallet]:
            return
        
        # Add to seen transactions (keep last 100 per wallet)
        self.last_seen_txs[wallet].add(tx_hash)
        if len(self.last_seen_txs[wallet]) > 100:
            # Remove oldest (simple FIFO)
            self.last_seen_txs[wallet].pop()
        
        # Update last activity timestamp
        self.last_activity[wallet] = datetime.utcnow()
        
        # Log detection
        print(f"[Stalker] 🚨 TARGET ACTIVE! {wallet[:10]}... | Tx: {tx_hash[:10]}... | Block: {block_number}")
        
        # Trigger callback if registered
        if self.on_activity:
            activity_event = {
                "wallet": wallet,
                "tx_hash": tx_hash,
                "block_number": block_number,
                "timestamp": datetime.utcnow().isoformat(),
                "chain": self.chain,
                "event_data": event_data
            }
            
            try:
                # Call the callback (likely triggers profile scan)
                await self.on_activity(activity_event)
            except Exception as e:
                print(f"[Stalker] Callback error: {e}")
    
    def get_watched_wallets_status(self) -> Dict:
        """
        Get current status of all watched wallets.
        Returns dict with wallet info for frontend display.
        """
        status = {}
        now = datetime.utcnow()
        
        for wallet in self.watched_wallets:
            last_activity = self.last_activity.get(wallet)
            
            if last_activity:
                time_diff = (now - last_activity).total_seconds()
                
                # Determine status
                if time_diff < 30:  # Active in last 30 seconds
                    state = "active"
                    time_ago = f"{int(time_diff)}s ago"
                elif time_diff < 3600:  # Active in last hour
                    state = "idle"
                    time_ago = f"{int(time_diff / 60)}m ago"
                else:
                    state = "idle"
                    time_ago = f"{int(time_diff / 3600)}h ago"
            else:
                state = "idle"
                time_ago = "Never"
            
            status[wallet] = {
                "state": state,
                "last_activity": time_ago,
                "last_activity_timestamp": last_activity.isoformat() if last_activity else None,
                "tx_count": len(self.last_seen_txs.get(wallet, set()))
            }
        
        return status


class SolanaWalletStalker:
    """
    Solana-specific wallet monitoring via WebSocket subscriptions.
    Uses logsSubscribe to monitor wallet activity.
    """
    
    def __init__(self):
        self.ws_url = SOLANA_WSS_URL
        self.websocket = None
        
        # State management
        self.watched_wallets: Set[str] = set()
        self.subscription_ids: Dict[str, int] = {}  # wallet -> subscription_id
        self.last_seen_txs: Dict[str, Set[str]] = defaultdict(set)
        self.last_activity: Dict[str, datetime] = {}
        
        # Callbacks
        self.on_activity: Optional[Callable] = None
        
        # Connection state
        self.connected = False
        self.listen_task = None
        
    async def connect(self):
        """Establish persistent WebSocket connection to Solana RPC"""
        if not SOLANA_SUPPORTED:
            raise RuntimeError("Solana libraries not installed. Run: pip install solana solders")
        
        if not self.ws_url:
            raise ValueError("No Solana WebSocket endpoint configured")
        
        try:
            # Enter the context manager properly
            self.websocket = solana_connect(self.ws_url)
            self.websocket = await self.websocket.__aenter__()
            self.connected = True
            print(f"[Stalker] Connected to Solana WebSocket")
            
            # Start listening loop
            self.listen_task = asyncio.create_task(self._listen_loop())
            
        except Exception as e:
            print(f"[Stalker] Solana connection failed: {e}")
            self.connected = False
            raise
    
    async def disconnect(self):
        """Cleanly close WebSocket connection"""
        self.connected = False
        
        # Unsubscribe all wallets
        for wallet in list(self.watched_wallets):
            await self.unwatch_wallet(wallet)
        
        # Cancel listening task
        if self.listen_task:
            self.listen_task.cancel()
            try:
                await self.listen_task
            except asyncio.CancelledError:
                pass
        
        # Close connection (exit context manager)
        if self.websocket:
            try:
                await self.websocket.__aexit__(None, None, None)
            except Exception as e:
                print(f"[Stalker] Error closing Solana connection: {e}")
            print(f"[Stalker] Disconnected from Solana")
    
    async def watch_wallet(self, wallet_address: str):
        """
        Subscribe to real-time logs for a specific Solana wallet address.
        Uses logsSubscribe with mentions filter.
        """
        if not self.connected or not self.websocket:
            raise RuntimeError("WebSocket not connected. Call connect() first.")
        
        if wallet_address in self.watched_wallets:
            print(f"[Stalker] Already watching {wallet_address[:10]}...")
            return True
        
        try:
            # Convert wallet address to Pubkey
            pubkey = Pubkey.from_string(wallet_address)
            
            # Subscribe to logs mentioning this wallet
            await self.websocket.logs_subscribe(
                filter_=RpcTransactionLogsFilterMentions(pubkey),
                commitment="confirmed"
            )
            
            # Note: Solana WebSocket doesn't return subscription ID the same way
            # We'll track by wallet address
            self.watched_wallets.add(wallet_address)
            self.last_activity[wallet_address] = datetime.utcnow()
            
            print(f"[Stalker] 👁️  Now watching Solana: {wallet_address[:10]}...")
            return True
                
        except Exception as e:
            print(f"[Stalker] Failed to watch Solana wallet: {e}")
            return False
    
    async def unwatch_wallet(self, wallet_address: str):
        """Unsubscribe from wallet logs"""
        if wallet_address not in self.watched_wallets:
            return
        
        # Note: Solana WebSocket API doesn't have easy unsubscribe for logs
        # We'll just stop tracking it
        self.watched_wallets.discard(wallet_address)
        self.subscription_ids.pop(wallet_address, None)
        self.last_seen_txs.pop(wallet_address, None)
        
        print(f"[Stalker] Stopped watching Solana: {wallet_address[:10]}...")
    
    async def _listen_loop(self):
        """
        Continuous loop that listens for incoming WebSocket messages from Solana.
        """
        print("[Stalker] Solana listen loop started")
        try:
            while self.connected and self.websocket:
                try:
                    # Receive messages from Solana WebSocket
                    messages = await self.websocket.recv()
                    print(f"[Stalker] Received {len(messages) if messages else 0} Solana messages")
                    
                    # Process each message
                    for message in messages:
                        await self._process_message(message)
                        
                except asyncio.CancelledError:
                    print("[Stalker] Solana listen loop cancelled")
                    break
                except Exception as e:
                    print(f"[Stalker] Solana listen error: {e}")
                    await asyncio.sleep(1)
                    
        except Exception as e:
            print(f"[Stalker] Solana listen loop error: {e}")
            self.connected = False
    
    async def _process_message(self, message):
        """
        Process incoming WebSocket message from Solana.
        Detects wallet activity and triggers callbacks.
        """
        try:
            # Convert message to dict if needed
            if hasattr(message, 'to_json'):
                data = json.loads(message.to_json())
            else:
                data = message
            
            # Show what we're actually receiving (first 3 times for debugging)
            if not hasattr(self, '_debug_count'):
                self._debug_count = 0
            
            if self._debug_count < 3:
                print(f"[Stalker] DEBUG #{self._debug_count + 1} - Full message:")
                print(f"  Type: {type(message)}")
                print(f"  Data type: {type(data)}")
                print(f"  Data: {data}")
                print(f"  Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                self._debug_count += 1
            
            # Check if this is a logs notification
            method = data.get("method", "")
            
            if method == "logsNotification":
                print("[Stalker] ✅ Logs notification received!")
                params = data.get("params", {})
                result = params.get("result", {})
                value = result.get("value", {})
                
                signature = value.get("signature")
                logs = value.get("logs", [])
                
                if not signature:
                    print("[Stalker] No signature in notification")
                    return
                
                print(f"[Stalker] Signature: {signature[:10]}... for {len(self.watched_wallets)} watched wallets")
                
                # Check which watched wallet this relates to
                # For Solana, we check if any watched wallet is in the logs
                for wallet in self.watched_wallets:
                    # For now, alert on any activity for watched wallets
                    print(f"[Stalker] Triggering activity for wallet: {wallet[:10]}...")
                    await self._handle_wallet_activity(wallet, signature, value)
            elif self._debug_count >= 3:
                # After debug phase, just count unknown
                pass
                        
        except Exception as e:
            print(f"[Stalker] Solana message processing error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _handle_wallet_activity(self, wallet: str, signature: str, log_data: dict):
        """
        Handle detected Solana wallet activity with debouncing.
        """
        # Debounce: Skip if we've already seen this signature
        if signature in self.last_seen_txs[wallet]:
            return
        
        # Add to seen transactions
        self.last_seen_txs[wallet].add(signature)
        if len(self.last_seen_txs[wallet]) > 100:
            self.last_seen_txs[wallet].pop()
        
        # Update last activity timestamp
        self.last_activity[wallet] = datetime.utcnow()
        
        # Log detection
        print(f"[Stalker] 🚨 SOLANA TARGET ACTIVE! {wallet[:10]}... | Tx: {signature[:10]}...")
        
        # Trigger callback if registered
        if self.on_activity:
            activity_event = {
                "wallet": wallet,
                "tx_hash": signature,
                "block_number": None,  # Solana uses slots
                "timestamp": datetime.utcnow().isoformat(),
                "chain": "solana",
                "event_data": log_data
            }
            
            try:
                await self.on_activity(activity_event)
            except Exception as e:
                print(f"[Stalker] Callback error: {e}")
    
    def get_watched_wallets_status(self) -> Dict:
        """
        Get current status of all watched Solana wallets.
        """
        status = {}
        now = datetime.utcnow()
        
        for wallet in self.watched_wallets:
            last_activity = self.last_activity.get(wallet)
            
            if last_activity:
                time_diff = (now - last_activity).total_seconds()
                
                if time_diff < 30:
                    state = "active"
                    time_ago = f"{int(time_diff)}s ago"
                elif time_diff < 3600:
                    state = "idle"
                    time_ago = f"{int(time_diff / 60)}m ago"
                else:
                    state = "idle"
                    time_ago = f"{int(time_diff / 3600)}h ago"
            else:
                state = "idle"
                time_ago = "Never"
            
            status[wallet] = {
                "state": state,
                "last_activity": time_ago,
                "last_activity_timestamp": last_activity.isoformat() if last_activity else None,
                "tx_count": len(self.last_seen_txs.get(wallet, set()))
            }
        
        return status


# Global stalker instances (one per chain)
_stalker_instances: Dict[str, WalletStalker] = {}
_solana_stalker: Optional[SolanaWalletStalker] = None


async def get_stalker(chain: str = "ethereum"):
    """
    Get or create a stalker instance for a specific chain.
    Maintains singleton per chain.
    Supports both EVM chains and Solana.
    """
    global _solana_stalker
    
    # Handle Solana separately
    if chain.lower() == "solana":
        if _solana_stalker is None:
            _solana_stalker = SolanaWalletStalker()
            await _solana_stalker.connect()
        return _solana_stalker
    
    # Handle EVM chains
    if chain not in _stalker_instances:
        stalker = WalletStalker(chain)
        await stalker.connect()
        _stalker_instances[chain] = stalker
    
    return _stalker_instances[chain]


async def cleanup_stalkers():
    """Clean up all stalker connections (call on shutdown)"""
    global _solana_stalker
    
    # Clean up EVM stalkers
    for stalker in _stalker_instances.values():
        await stalker.disconnect()
    _stalker_instances.clear()
    
    # Clean up Solana stalker
    if _solana_stalker:
        await _solana_stalker.disconnect()
        _solana_stalker = None

