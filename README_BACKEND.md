# Gator Backend API - Quick Start

## Mempool Forensics Feature

This backend provides REST API endpoints for analyzing Solana wallet execution profiles.

## Setup

1. Install dependencies:
```bash
pip install fastapi uvicorn pydantic
```

2. Start the backend server:
```bash
python backend_api.py
```

Or with uvicorn directly:
```bash
uvicorn backend_api:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Endpoints

### POST `/mempool-forensics`
Analyze a wallet's execution profile across multiple transactions.

**Request:**
```json
{
  "wallet": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
  "limit": 50
}
```

**Response:**
```json
{
  "wallet": "5Q544fKr...",
  "total_transactions": 50,
  "profiles": {
    "RETAIL": 30,
    "URGENT_USER": 15,
    "PRO_TRADER": 5,
    "MEV_STYLE": 0
  },
  "profile_percentages": {
    "RETAIL": 60.0,
    "URGENT_USER": 30.0,
    "PRO_TRADER": 10.0,
    "MEV_STYLE": 0.0
  },
  "aggregate_profile": "RETAIL",
  "statistics": {
    "avg_priority_fee_microlamports": 50000.0,
    "total_jito_tips_sol": 0.0,
    "jito_tip_count": 0,
    "jito_tip_percentage": 0.0
  }
}
```

### POST `/analyze-transaction`
Analyze a single transaction for execution profile.

**Request:**
```json
{
  "signature": "transaction_signature_here"
}
```

**Response:**
```json
{
  "signature": "...",
  "execution_profile": "URGENT_USER",
  "priority_fee_microlamports": 1000000,
  "compute_unit_limit": 200000,
  "has_jito_tip": false,
  "jito_tip_sol": 0.0,
  "indicators": ["High priority fee: 1.00M microlamports"]
}
```

## Execution Profile Classifications

- **RETAIL**: Standard transactions with no/minimal priority fees
- **URGENT_USER**: Transactions with moderate to high priority fees (>100K microlamports)
- **PRO_TRADER**: Transactions with very high compute unit limits (>1.4M) or high priority fees
- **MEV_STYLE**: Transactions that include Jito tips (private execution)

## Frontend

Open `static/index.html` in a browser to use the web interface. Make sure the backend is running on `http://localhost:8000`.



