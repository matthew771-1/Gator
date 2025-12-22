
# 🐊 Gator OSINT Suite (EVM & Solana)

**Gator** is a behavioral profiling tool for blockchain addresses. Unlike standard block explorers that show *what* happened, Gator uses side-channel analysis (Time, Gas/Compute, Failure Rates, **Reaction Speed**) to determine **who** is behind a wallet.

It answers questions like:
* "Is this user a human or a bot?"
* "What timezone do they sleep in?" (London vs. NY vs. Tokyo)
* "Are they using privacy mixers or complex DeFi scripts?"
* "Are these separate wallets actually connected or funding each other?"
* **NEW:** "How fast do they react to receiving tokens?" (Bots: <5s, Humans: >30s)

---

## 🚀 Getting Started

### 1. Prerequisites
You need Python 3.8+. Install the dependencies:

```
pip install requests pandas matplotlib numpy argparse

```

### 2. API Configuration (Security First!)**Do not commit API keys to GitHub.**
Set these environment variables in your terminal or a `.env` file before running the scripts.

* **Etherscan API Key** (For Ethereum/Base/Arbitrum): Get one [here](https://etherscan.io/myapikey).
* **Helius API Key** (For Solana): Get one [here](https://dev.helius.xyz/dashboard/app).

```bash
# Mac/Linux
export ETHERSCAN_API_KEY="your_key_here"
export HELIUS_API_KEY="your_key_here"

# Windows (PowerShell)
$env:ETHERSCAN_API_KEY="your_key_here"
$env:HELIUS_API_KEY="your_key_here"

```

---

## 🛠️ Usage (CLI)There are three main modes. The Solana script currently supports advanced network scanning.

### 1. Profiling a Target (The "Dossier")Generates a behavioral profile including sleep patterns, risk score, and occupation.

```bash
# Solana
python gator_solana.py profile 5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1 --limit 200

# Ethereum (or Base, Arbitrum, etc.)
python gator_evm.py profile 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --chain ethereum

```

### 2. Finding Connections (Multi-Wallet Check)This command takes a list of **multiple wallet addresses** and checks if they have ever interacted directly (transfers, swaps, etc.).

* **Goal:** Determine if "Wallet A," "Wallet B," and "Wallet C" are actually the same person or working together.
* **Output:** Generates a "Connection Map" showing transaction counts and volume between all listed addresses.

```bash
# Check if these 3 wallets are connected
python gator_solana.py connect WalletAddressA WalletAddressB WalletAddressC

```

### 3. Network Scanning (The "Spider" Mode)**Solana Only:** This maps the target's network to N degrees of separation. This is useful for finding "Cluster Wallets" or money laundering hops.

* **`--depth`**: How many "hops" to follow.
* `1`: Only direct connections.
* `2`: Friends of friends (The target's connections' connections).
* `3+`: Deep network (Warning: Exponentially slower).



```bash
# Scan 2 degrees deep to find "friends of friends"
python gator_solana.py scan 5Q544fKrFoe... --depth 2

# Deep scan (3 degrees) with higher transaction limit
python gator_solana.py scan 5Q544fKrFoe... --depth 3 --limit 50

```

---

## 🎨 Frontend Integration GuideThe goal is to turn these CLI scripts into a "God Mode" dashboard.

### Architecture RecommendationDo not call these scripts via `subprocess`. Instead, import the functions directly into a backend API (like FastAPI or Flask).

**Example Backend Wrapper:**

```python
# main.py (FastAPI)
from fastapi import FastAPI
from gator_solana import analyze_wallet, calculate_probabilities, detect_sleep_window

app = FastAPI()

@app.get("/profile/{address}")
def get_profile(address: str):
    # 1. Run the analysis logic
    # Note: For EVM, analyze_wallet returns (df, tx_details_list)
    df, tx_details_list = analyze_wallet(address)  # EVM
    # df = analyze_wallet(address)  # Solana (single return)
    
    # 2. Process metrics
    hourly_counts = [0] * 24
    daily_counts = [0] * 7
    for _, row in df.iterrows():
        hourly_counts[row["hour"]] += 1
        daily_counts[row["day_of_week"]] += 1
        
    sleep = detect_sleep_window(hourly_counts)
    reaction = analyze_reaction_speed(address, tx_details_list)  # Add reaction analysis
    probs = calculate_probabilities(df, hourly_counts, daily_counts, sleep, reaction)
    
    # 3. Return JSON for your frontend
    return {
        "probabilities": probs.__dict__,
        "sleep_window": sleep.__dict__,
        "reaction_speed": reaction.__dict__,  # Add reaction speed data
        "transactions": df.to_dict(orient="records")
    }

```

### Visualization RequirementsThe frontend should have **3 Main Panels**:

#### Panel 1: The "Sleep Window" (Timezone Leak)* **Data Source:** `df['hour']` (0-23 UTC).
* **Component:** Bar Chart.
* **Goal:** Highlight the 4-6 hour gap where activity drops to near zero.
* **Inference:**
* Gap at 02:00 UTC → **Europe**
* Gap at 08:00 UTC → **USA (East Coast)**
* Gap at 22:00 UTC → **Asia**



#### Panel 2: Complexity Map (Scatter Plot)* **Data Source:** X-axis = `Time (Hour)`, Y-axis = `Compute Units` (Solana) or `Gas Used` (EVM).
* **Component:** Scatter Plot.
* **Color Coding:**
* 🟢 Green: Low Compute (Simple Transfers)
* 🔴 Red: High Compute (Complex DeFi / Privacy Mixers)


* **Goal:** If you see "Red Dots" appearing during the "Sleep Window," it's likely a **Bot**.

#### Panel 3: Risk Radar (Pie/Bar)* **Data Source:** `probs` object (Bot %, Whale %, Degen %).
* **Component:** Radar Chart or Progress Bars.
* **Goal:** Show the likelihood of the entity being a Bot vs. Human.

#### Panel 4: Reaction Speed Analysis (Bar Chart)* **Data Source:** `reaction` object from `analyze_reaction_speed()`.
* **Component:** Bar Chart showing Instant/Fast/Human reaction distribution.
* **Goal:** Visualize bot detection metrics with bot confidence score.
* **Available for:** Both Solana and EVM chains.

---

## ⚡ Reaction Speed Analysis (Bot Detection)

**Available for both Solana and EVM chains**

Gator includes advanced reaction speed analysis to detect bots with high precision. The algorithm measures the time between **receiving tokens/ETH** and **taking action** (selling, swapping, transferring). This works for both native tokens and ERC20 token transfers on EVM chains.

### How It Works:
1. **Analyzes consecutive transactions** to find "receive → action" patterns
2. **Calculates time deltas** between receiving and acting on tokens
3. **Categorizes reactions:**
   - **Instant (<5s)**: Nearly impossible for humans → **BOT**
   - **Fast (5-30s)**: Possible but suspicious → **Likely BOT**
   - **Human (>30s)**: Normal human decision time → **HUMAN**

### Output Metrics:
- **Bot Confidence Score** (0-100%)
- **Average & Median Reaction Times**
- **Fastest Reaction** (if <1s, definitely a bot)
- **Reaction Distribution** (% instant vs fast vs human)

### Example Output:
```
REACTION SPEED ANALYSIS (Bot Detection)
----------------------------------------------------------------------
Reaction Pairs:     64
Avg Reaction:       17.44s
Median Reaction:    12.00s
Fastest Reaction:   0.00s
Instant (<5s):      4 (6.2%)
Fast (5-30s):       57 (89.1%)
Human (>30s):       3 (4.7%)
Bot Confidence:    70.0%
[WARNING] HIGH BOT PROBABILITY: Average reaction 17.4s
```

### Use Cases:
- **MEV Bot Detection**: Instantly identify arbitrage bots
- **Trading Bot Identification**: Find automated trading strategies
- **Human vs Bot Classification**: High-confidence separation
- **Scam Detection**: Bots often show instant reactions to incoming funds

---

## 👨‍💻 Developer Guide: Customizing the LogicFor the junior devs: Here is where you can tweak the "brains" of the tool in `gator_solana.py` and `gator_evm.py`.

### 1. Adjusting "Whale" ThresholdsIf you want to change what counts as a "Whale" or "High Complexity," look for the `calculate_probabilities` function.

```python
# gator_solana.py
# Change this to > 100,000 if you only want to catch SUPER heavy scripts
if avg_cu > 300000:
    probs.whale = 85

```

### 2. Customizing Network Depth LogicThe `scan_network` function in `gator_solana.py` currently connects *any* wallet it finds. You can filter this to reduce noise.

**Idea:** Only follow connections where the transaction value > 10 SOL.

```python
# In scan_network() loop:
if tx_value > 10:  # You will need to extract 'lamports' from tx_details
    next_level.add(acc)

```

### 3. Adding New LabelsUpdate the `KNOWN_LABELS` dictionary at the top of the script to tag your own known wallets (e.g., your company's cold storage or competitor wallets).

```python
KNOWN_LABELS = {
    "YourWalletAddress": "Internal Treasury",
    ...
}

```

### 4. Adjusting Reaction Speed ThresholdsYou can customize the bot detection thresholds in the `analyze_reaction_speed()` function in both `gator_solana.py` and `gator_evm.py`:

```python
# Current thresholds:
# - Instant: < 5 seconds
# - Fast: 5-30 seconds  
# - Human: > 30 seconds
# - Analysis window: 1 hour (reactions beyond are excluded)

# Make it more strict (only flag super-fast bots):
if time_delta < 2:  # Instead of 5
    instant_count += 1

# Or adjust the bot confidence calculation:
if instant_ratio > 0.5:  # Instead of 0.7
    bot_confidence = 95.0

# Change analysis window (default is 3600 seconds = 1 hour):
if time_delta > 1800:  # 30 minutes instead of 1 hour
    break
```

**Note for EVM**: The analysis includes both regular ETH transactions and ERC20 token transfers. Token transfers are automatically detected and included in the reaction speed analysis.

---

## ⚠️ DisclaimerThis tool uses **only public data**. It does not break encryption or access private keys. It is strictly for educational research and behavioral analysis.

```

