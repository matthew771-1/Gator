#!/usr/bin/env python3
"""
FastAPI backend for Gator OSINT Suite
Provides REST API endpoints for wallet analysis and mempool forensics
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Dict, Set
import sys
import os
import traceback
import asyncio
import json
from datetime import datetime

# Import Gator functions
from gator_solana import (
    analyze_wallet_execution_profiles,
    analyze_execution_profile,
    fetch_transaction,
    fetch_signatures,
    analyze_wallet as analyze_wallet_solana,
    detect_sleep_window as detect_sleep_window_solana,
    calculate_probabilities as calculate_probabilities_solana,
    analyze_reaction_speed as analyze_reaction_speed_solana
)

# Import EVM functions
try:
    from gator_evm import (
        analyze_wallet as analyze_wallet_evm,
        detect_sleep_window as detect_sleep_window_evm,
        calculate_probabilities as calculate_probabilities_evm,
        analyze_reaction_speed as analyze_reaction_speed_evm
    )
    EVM_SUPPORTED = True
except ImportError:
    EVM_SUPPORTED = False
    print("[!] Warning: EVM support not available (gator_evm.py not found)")

# Import Stalker Service for live monitoring
try:
    from stalker_service import get_stalker, cleanup_stalkers, WalletStalker
    STALKER_SUPPORTED = True
except ImportError:
    STALKER_SUPPORTED = False
    print("[!] Warning: Stalker mode not available (stalker_service.py not found)")

app = FastAPI(title="Gator OSINT API", version="1.0.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Stalker Mode: Active WebSocket connections
active_stalker_connections: Set[WebSocket] = set()

# Stalker Mode: Callback for wallet activity
async def on_wallet_activity(event: dict):
    """
    Callback triggered when a watched wallet becomes active.
    Broadcasts event to all connected WebSocket clients.
    """
    print(f"[API] 🚨 Wallet activity detected: {event['wallet'][:10]}...")
    
    # TODO: Optionally trigger automatic profile scan here
    # scan_result = await trigger_profile_scan(event['wallet'], event['chain'])
    # event['scan_result'] = scan_result
    
    # Broadcast to all connected clients
    message = json.dumps({
        "type": "wallet_activity",
        "data": event
    })
    
    disconnected = set()
    for connection in active_stalker_connections:
        try:
            await connection.send_text(message)
        except Exception:
            disconnected.add(connection)
    
    # Clean up disconnected clients
    active_stalker_connections.difference_update(disconnected)

# Serve static files (frontend)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    @app.get("/")
    def serve_frontend():
        """Serve the main frontend page"""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Frontend not found. API is running."}


class MempoolForensicsRequest(BaseModel):
    wallet: str
    limit: Optional[int] = 100


class WalletAnalysisRequest(BaseModel):
    wallet: str
    limit: Optional[int] = 200
    chain: Optional[str] = "solana"  # solana, ethereum, base, arbitrum, optimism, polygon


class TransactionAnalysisRequest(BaseModel):
    signature: str


@app.get("/")
def root():
    return {"message": "Gator OSINT API", "version": "1.0.0"}


@app.post("/mempool-forensics")
def mempool_forensics(request: MempoolForensicsRequest):
    """
    Analyze wallet's execution profiles across transactions.
    Returns execution profile classification (RETAIL, URGENT_USER, PRO_TRADER, MEV_STYLE).
    """
    try:
        result = analyze_wallet_execution_profiles(request.wallet, request.limit)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/analyze-transaction")
def analyze_transaction(request: TransactionAnalysisRequest):
    """
    Analyze a single transaction for execution profile.
    """
    try:
        tx_details = fetch_transaction(request.signature)
        if not tx_details:
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        result = analyze_execution_profile(tx_details)
        result["signature"] = request.signature
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/analyze-wallet")
def analyze_wallet_comprehensive(request: WalletAnalysisRequest):
    """
    Comprehensive wallet analysis - supports Solana and EVM chains.
    """
    try:
        chain = request.chain.lower()
        
        # Select the appropriate analysis functions based on chain
        if chain == "solana":
            df, tx_details_list = analyze_wallet_solana(request.wallet, limit=request.limit)
            detect_sleep = detect_sleep_window_solana
            calc_probs = calculate_probabilities_solana
            analyze_reaction = analyze_reaction_speed_solana
            compute_unit_field = "compute_units"
        else:
            # EVM chains
            if not EVM_SUPPORTED:
                raise HTTPException(status_code=501, detail="EVM support not available")
            df, tx_details_list = analyze_wallet_evm(request.wallet, chain=chain, limit=request.limit)
            detect_sleep = detect_sleep_window_evm
            calc_probs = calculate_probabilities_evm
            analyze_reaction = analyze_reaction_speed_evm
            compute_unit_field = "gas_used"  # EVM uses gas instead of compute units
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No transactions found for this wallet")
        
        # Calculate hourly and daily counts
        hourly_counts = [0] * 24
        daily_counts = [0] * 7
        for _, row in df.iterrows():
            hourly_counts[row["hour"]] += 1
            daily_counts[row["day_of_week"]] += 1
        
        # Detect sleep window
        sleep = detect_sleep(hourly_counts)
        
        # Analyze reaction speed for bot detection
        reaction = analyze_reaction(request.wallet, tx_details_list)
        
        # Calculate probabilities (different signatures for Solana vs EVM)
        if chain == "solana":
            # Solana's calculate_probabilities takes 4 params (no reaction)
            probs = calc_probs(df, hourly_counts, daily_counts, sleep)
        else:
            # EVM's calculate_probabilities takes 5 params (includes reaction)
            probs = calc_probs(df, hourly_counts, daily_counts, sleep, reaction)
        
        # Analyze execution profiles (Solana only for now)
        mempool_data = {}
        if chain == "solana":
            mempool_data = analyze_wallet_execution_profiles(request.wallet, limit=100)
        
        # Prepare transaction complexity data
        complexity_data = []
        for _, row in df.iterrows():
            # Use appropriate complexity metric based on chain
            complexity_value = row.get(compute_unit_field, 0)
            
            if chain == "solana":
                # Solana compute units
                if complexity_value > 300000:
                    tx_type = "Complex"
                elif complexity_value > 150000:
                    tx_type = "Jito Bundle"
                else:
                    tx_type = "Standard"
            else:
                # EVM gas
                if complexity_value > 300000:
                    tx_type = "Heavy"
                elif complexity_value > 150000:
                    tx_type = "Complex"
                elif complexity_value > 65000:
                    tx_type = "Moderate"
                else:
                    tx_type = "Simple"
            
            complexity_data.append({
                "hour": int(row["hour"]),
                compute_unit_field: int(complexity_value),
                "type": tx_type
            })
        
        # Calculate risk assessment
        total_tx = len(df)
        fail_rate = (~df["success"]).sum() / total_tx if total_tx > 0 else 0
        
        # Use appropriate high complexity threshold based on chain
        high_complexity_threshold = 200000 if chain == "solana" else 300000
        high_complexity_ratio = (df[compute_unit_field] > high_complexity_threshold).sum() / total_tx if total_tx > 0 else 0
        
        low_risk_count = ((fail_rate < 0.05) and (high_complexity_ratio < 0.1))
        medium_risk_count = ((fail_rate >= 0.05 and fail_rate < 0.2) or (high_complexity_ratio >= 0.1 and high_complexity_ratio < 0.3))
        high_risk_count = ((fail_rate >= 0.2) or (high_complexity_ratio >= 0.3))
        
        # Determine risk level
        if high_risk_count:
            risk_level = "High Risk"
            risk_score = min(100, int(fail_rate * 100 + high_complexity_ratio * 100))
        elif medium_risk_count:
            risk_level = "Medium Risk"
            risk_score = min(60, int(fail_rate * 100 + high_complexity_ratio * 50))
        else:
            risk_level = "Low Risk"
            risk_score = min(30, int(fail_rate * 50))
        
        # Generate key insights
        insights = []
        if probs.bot > 60:
            insights.append(f"{probs.bot:.0f}% bot probability - highly automated behavior detected")
        else:
            insights.append(f"Human trader detected with {100-probs.bot:.0f}% confidence")
        
        if probs.eu_trader > probs.us_trader and probs.eu_trader > probs.asia_trader:
            insights.append("Primary activity in Europe/Africa timezone")
        elif probs.asia_trader > probs.us_trader and probs.asia_trader > probs.eu_trader:
            insights.append("Primary activity in Asia/Pacific timezone")
        elif probs.us_trader > probs.eu_trader and probs.us_trader > probs.asia_trader:
            insights.append("Primary activity in Americas timezone")
        
        insights.append(f"{risk_level} profile with sophisticated patterns")
        
        if probs.professional > probs.retail_hobbyist:
            insights.append("Weekday activity suggests professional operations")
        else:
            insights.append("Weekend activity suggests retail/hobbyist trader")
        
        # Add reaction speed insight
        if reaction.total_reaction_pairs > 0:
            if reaction.bot_confidence > 70:
                insights.append(f"⚡ {reaction.bot_confidence:.0f}% bot confidence - {reaction.instant_reactions} instant reactions detected (<5s)")
            elif reaction.bot_confidence > 40:
                insights.append(f"⚡ Moderate automation detected - avg reaction time {reaction.avg_reaction_time:.1f}s")
            else:
                insights.append(f"⚡ Human-like reaction patterns - avg response time {reaction.avg_reaction_time:.1f}s")
        
        # Determine confidence level
        confidence = "High" if total_tx > 100 else "Medium" if total_tx > 50 else "Low"
        
        # Find most recent transaction timestamp
        most_recent_timestamp = None
        if tx_details_list and len(tx_details_list) > 0:
            # tx_details_list should be sorted with most recent first
            # Format: [{"timestamp": unix_timestamp, "details": {...}}, ...]
            first_tx = tx_details_list[0]
            
            # Get the timestamp field (already a Unix timestamp int)
            most_recent_timestamp = first_tx.get('timestamp')
            
            # Convert to ISO format if it's a unix timestamp
            if most_recent_timestamp and isinstance(most_recent_timestamp, (int, float)):
                from datetime import datetime
                most_recent_timestamp = datetime.utcfromtimestamp(most_recent_timestamp).isoformat() + 'Z'
        
        return {
            "wallet": request.wallet,
            "chain": chain,
            "total_transactions": total_tx,
            "confidence": confidence,
            "most_recent_transaction": most_recent_timestamp,
            "activity_pattern": {
                "hourly": hourly_counts,
                "daily": daily_counts
            },
            "geographic_origin": {
                "europe": round(probs.eu_trader, 2),
                "americas": round(probs.us_trader, 2),
                "asia_pacific": round(probs.asia_trader, 2),
                "other": round(100 - probs.eu_trader - probs.us_trader - probs.asia_trader, 2)
            },
            "trader_classification": {
                "retail": round(probs.retail_hobbyist, 2),
                "institutional": round(probs.professional, 2),
                "professional": round(probs.professional * 0.5, 2)
            },
            "profile_classification": {
                "bot": round(probs.bot, 2),
                "institutional": round(probs.professional, 2),
                "whale": round(probs.whale, 2),
                "airdrop_farmer": round(probs.degen * 0.5, 2),
                "professional": round(probs.professional * 0.5, 2)
            },
            "transaction_complexity": complexity_data[:200],  # Limit for performance
            "risk_assessment": {
                "level": risk_level,
                "score": risk_score,
                "low_risk": 30 if low_risk_count else 0,
                "medium_risk": 55 if medium_risk_count else 0,
                "high_risk": 2 if high_risk_count else 0
            },
            "key_insights": insights,
            "mempool_forensics": mempool_data if chain == "solana" else {"note": "Mempool forensics only available for Solana"},
            "sleep_window": {
                "start_hour": sleep.start_hour,
                "end_hour": sleep.end_hour,
                "confidence": round(sleep.confidence, 2)
            },
            "reaction_speed": {
                "bot_confidence": round(reaction.bot_confidence, 2),
                "avg_reaction_time": round(reaction.avg_reaction_time, 2),
                "median_reaction_time": round(reaction.median_reaction_time, 2),
                "fastest_reaction": round(reaction.fastest_reaction, 2),
                "instant_reactions": reaction.instant_reactions,
                "fast_reactions": reaction.fast_reactions,
                "human_reactions": reaction.human_reactions,
                "total_pairs": reaction.total_reaction_pairs
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        # Print full traceback for debugging
        print("\n" + "="*60)
        print("ERROR IN /analyze-wallet:")
        print("="*60)
        traceback.print_exc()
        print("="*60 + "\n")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.websocket("/ws/stalker")
async def stalker_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for Live Stalker Mode.
    Handles real-time wallet monitoring commands and broadcasts activity.
    
    Protocol:
    - Client sends: {"action": "watch", "wallet": "0x...", "chain": "ethereum"}
    - Client sends: {"action": "unwatch", "wallet": "0x..."}
    - Client sends: {"action": "status"}
    - Server sends: {"type": "wallet_activity", "data": {...}}
    - Server sends: {"type": "status_update", "data": {...}}
    """
    if not STALKER_SUPPORTED:
        await websocket.close(code=1011, reason="Stalker mode not available")
        return
    
    await websocket.accept()
    active_stalker_connections.add(websocket)
    
    print(f"[API] 👁️  Stalker client connected (total: {len(active_stalker_connections)})")
    
    # Send initial connection confirmation
    await websocket.send_json({
        "type": "connected",
        "message": "Stalker mode ready"
    })
    
    try:
        while True:
            # Receive command from client
            data = await websocket.receive_text()
            command = json.loads(data)
            action = command.get("action")
            
            if action == "watch":
                # Start watching a wallet
                wallet = command.get("wallet")
                chain = command.get("chain", "ethereum")
                
                if not wallet:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Wallet address required"
                    })
                    continue
                
                try:
                    # Get or create stalker for this chain
                    stalker = await get_stalker(chain)
                    
                    # Register callback if not already set
                    if not stalker.on_activity:
                        stalker.on_activity = on_wallet_activity
                    
                    # Subscribe to wallet
                    success = await stalker.watch_wallet(wallet)
                    
                    if success:
                        await websocket.send_json({
                            "type": "watch_started",
                            "wallet": wallet,
                            "chain": chain,
                            "message": f"Now watching {wallet[:10]}..."
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Failed to watch {wallet}"
                        })
                        
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Watch failed: {str(e)}"
                    })
            
            elif action == "unwatch":
                # Stop watching a wallet
                wallet = command.get("wallet")
                chain = command.get("chain", "ethereum")
                
                if not wallet:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Wallet address required"
                    })
                    continue
                
                try:
                    stalker = await get_stalker(chain)
                    await stalker.unwatch_wallet(wallet)
                    
                    await websocket.send_json({
                        "type": "watch_stopped",
                        "wallet": wallet,
                        "message": f"Stopped watching {wallet[:10]}..."
                    })
                    
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unwatch failed: {str(e)}"
                    })
            
            elif action == "status":
                # Get status of all watched wallets
                chain = command.get("chain", "ethereum")
                
                try:
                    stalker = await get_stalker(chain)
                    status = stalker.get_watched_wallets_status()
                    
                    await websocket.send_json({
                        "type": "status_update",
                        "chain": chain,
                        "wallets": status,
                        "connected": stalker.connected
                    })
                    
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Status check failed: {str(e)}"
                    })
            
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown action: {action}"
                })
                
    except WebSocketDisconnect:
        print("[API] Stalker client disconnected")
    except Exception as e:
        print(f"[API] Stalker WebSocket error: {e}")
    finally:
        active_stalker_connections.discard(websocket)
        print(f"[API] Stalker clients remaining: {len(active_stalker_connections)}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up stalker connections on server shutdown"""
    if STALKER_SUPPORTED:
        print("[API] Shutting down stalker services...")
        await cleanup_stalkers()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

