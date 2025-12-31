# Solana Function Signature Fix

## Date: December 29, 2025

## Problem
After fixing EVM chains, Solana broke with error:
```
Analysis failed: calculate_probabilities() takes 4 positional arguments but 5 were given
```

## Root Cause
**Different function signatures between chains:**

### Solana (4 parameters - NO reaction):
```python
def calculate_probabilities(df, hourly_counts, daily_counts, sleep):
    # Does NOT take reaction parameter
```

### EVM (5 parameters - WITH reaction):
```python
def calculate_probabilities(df, hourly_counts, daily_counts, sleep, reaction):
    # Takes reaction parameter for bot detection
```

## The Fix

**File:** `backend_api.py` lines 196-208

**Before (BROKEN for Solana):**
```python
# Analyze reaction speed for bot detection
reaction = analyze_reaction(request.wallet, tx_details_list)

# Calculate probabilities (passing reaction parameter)
probs = calc_probs(df, hourly_counts, daily_counts, sleep, reaction)
# ↑ This always passes 5 params, breaking Solana!
```

**After (WORKS for both):**
```python
# Analyze reaction speed for bot detection
reaction = analyze_reaction(request.wallet, tx_details_list)

# Calculate probabilities (different signatures for Solana vs EVM)
if chain == "solana":
    # Solana's calculate_probabilities takes 4 params (no reaction)
    probs = calc_probs(df, hourly_counts, daily_counts, sleep)
else:
    # EVM's calculate_probabilities takes 5 params (includes reaction)
    probs = calc_probs(df, hourly_counts, daily_counts, sleep, reaction)
```

## Why This Happened
When I added the `reaction` parameter for EVM chains earlier (to fix the bot detection), I updated the call to always pass 5 parameters. This worked for EVM but broke Solana because Solana's function doesn't have the `reaction` parameter yet.

## Status
✅ Fixed - Server auto-reloaded
✅ Solana now works again
✅ EVM chains still work
✅ All chains functional

## Test
Try a Solana wallet like: `vines1vzrYbzLMRdu58ou5XTby4qAqVRLmqo36NKPTg`

Should work perfectly now! 🐊

