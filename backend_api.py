#!/usr/bin/env python3
"""
FastAPI backend for Gator OSINT Suite
Provides REST API endpoints for wallet analysis and mempool forensics
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import sys
import os

# Import Gator functions
from gator_solana import (
    analyze_wallet_execution_profiles,
    analyze_execution_profile,
    fetch_transaction,
    fetch_signatures,
    analyze_wallet,
    detect_sleep_window,
    calculate_probabilities
)

app = FastAPI(title="Gator OSINT API", version="1.0.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    Comprehensive wallet analysis - fetches ALL transactions and provides complete profile.
    """
    try:
        # Fetch transactions based on user-specified limit
        df = analyze_wallet(request.wallet, limit=request.limit)
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No transactions found for this wallet")
        
        # Calculate hourly and daily counts
        hourly_counts = [0] * 24
        daily_counts = [0] * 7
        for _, row in df.iterrows():
            hourly_counts[row["hour"]] += 1
            daily_counts[row["day_of_week"]] += 1
        
        # Detect sleep window
        sleep = detect_sleep_window(hourly_counts)
        
        # Calculate probabilities
        probs = calculate_probabilities(df, hourly_counts, daily_counts, sleep)
        
        # Analyze execution profiles
        mempool_data = analyze_wallet_execution_profiles(request.wallet, limit=100)
        
        # Prepare transaction complexity data
        complexity_data = []
        for _, row in df.iterrows():
            cu = row["compute_units"]
            if cu > 300000:
                tx_type = "Complex"
            elif cu > 150000:
                tx_type = "Jito Bundle"
            else:
                tx_type = "Standard"
            
            complexity_data.append({
                "hour": int(row["hour"]),
                "compute_units": int(cu),
                "type": tx_type
            })
        
        # Calculate risk assessment
        total_tx = len(df)
        fail_rate = (~df["success"]).sum() / total_tx if total_tx > 0 else 0
        high_cu_ratio = (df["compute_units"] > 200000).sum() / total_tx if total_tx > 0 else 0
        
        low_risk_count = ((fail_rate < 0.05) and (high_cu_ratio < 0.1))
        medium_risk_count = ((fail_rate >= 0.05 and fail_rate < 0.2) or (high_cu_ratio >= 0.1 and high_cu_ratio < 0.3))
        high_risk_count = ((fail_rate >= 0.2) or (high_cu_ratio >= 0.3))
        
        # Determine risk level
        if high_risk_count:
            risk_level = "High Risk"
            risk_score = min(100, int(fail_rate * 100 + high_cu_ratio * 100))
        elif medium_risk_count:
            risk_level = "Medium Risk"
            risk_score = min(60, int(fail_rate * 100 + high_cu_ratio * 50))
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
        
        # Determine confidence level
        confidence = "High" if total_tx > 100 else "Medium" if total_tx > 50 else "Low"
        
        return {
            "wallet": request.wallet,
            "total_transactions": total_tx,
            "confidence": confidence,
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
            "mempool_forensics": mempool_data,
            "sleep_window": {
                "start_hour": sleep.start_hour,
                "end_hour": sleep.end_hour,
                "confidence": round(sleep.confidence, 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

