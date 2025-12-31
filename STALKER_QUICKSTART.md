# Live Stalker Mode - Quick Start Guide

## 🚀 5-Minute Setup

### Step 1: Get RPC WebSocket Credentials

You need WebSocket access to EVM chains. Choose a provider:

#### Option A: Alchemy (Recommended - Free Tier)

1. Go to [alchemy.com](https://www.alchemy.com/)
2. Sign up for free account
3. Create a new app for each chain you want:
   - Ethereum Mainnet
   - Base Mainnet  
   - Arbitrum One
   - Optimism Mainnet
   - Polygon Mainnet
4. Copy the WebSocket URLs (looks like: `wss://eth-mainnet.g.alchemy.com/v2/YOUR_KEY`)

#### Option B: Infura

1. Go to [infura.io](https://infura.io/)
2. Create free account
3. Create project
4. Get WebSocket endpoints from dashboard

#### Option C: QuickNode

1. Go to [quicknode.com](https://www.quicknode.com/)
2. Create endpoint
3. Select WebSocket endpoint type

---

### Step 2: Configure GATOR

Open `stalker_service.py` and replace the placeholder URLs:

```python
EVM_WSS_ENDPOINTS = {
    "ethereum": "wss://eth-mainnet.g.alchemy.com/v2/YOUR_KEY_HERE",
    "base": "wss://base-mainnet.g.alchemy.com/v2/YOUR_KEY_HERE",
    "arbitrum": "wss://arb-mainnet.g.alchemy.com/v2/YOUR_KEY_HERE",
    "optimism": "wss://opt-mainnet.g.alchemy.com/v2/YOUR_KEY_HERE",
    "polygon": "wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY_HERE"
}
```

**⚠️ Important:** Replace `YOUR_KEY_HERE` with your actual API key!

---

### Step 3: Install Dependencies

```bash
pip install websockets
```

(Other dependencies should already be installed from initial GATOR setup)

---

### Step 4: Start Server

```bash
cd Gator
python run_server.py
```

Or on Windows, double-click: `START_SERVER.bat`

---

### Step 5: Test It!

1. Open browser: `http://localhost:8000`
2. Select **Ethereum** as the chain
3. Enter a wallet address (try this active one):
   ```
   0x28C6c06298d514Db089934071355E5743bf21d60
   ```
   (This is Binance Hot Wallet - very active)
4. Click **Analyze** and wait for results
5. Click the **👁️ Watch Live** button
6. Watch the top-right corner - the red panel should appear!

---

## 🧪 Testing

### Immediate Test (No Waiting)

Use the browser console to simulate activity:

1. Open DevTools (F12)
2. After clicking "Watch Live", paste this:

```javascript
handleWalletActivity({
    wallet: currentAnalyzedWallet,
    tx_hash: '0xtest123456789abcdef',
    block_number: '0x112a880',
    timestamp: new Date().toISOString(),
    chain: currentAnalyzedChain,
    event_data: {}
});
```

You should see:
- ✅ Flash animation on the wallet panel
- ✅ Desktop notification (if enabled)
- ✅ In-app alert banner
- ✅ Status changes to "Active Now"

### Real-World Test

Watch these wallets (they're constantly active):

| Wallet | Chain | Description |
|--------|-------|-------------|
| `0x28C6c06298d514Db089934071355E5743bf21d60` | Ethereum | Binance Hot Wallet |
| `0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D` | Ethereum | Uniswap Router V2 |
| `0x1111111254EEB25477B68fb85Ed929f73A960582` | Ethereum | 1inch Router |

Expected: You'll see activity within 1-5 minutes for these wallets.

---

## 📱 Enable Desktop Notifications

For the best experience:

**Chrome/Edge:**
1. Browser will prompt "Allow notifications?" → Click **Allow**
2. If you missed it: Click 🔒 in address bar → Site Settings → Notifications → Allow

**Firefox:**
1. Browser prompts → Click **Allow**
2. Or: Click 🔒 → Permissions → Notifications → Allow

**Safari:**
1. Safari → Settings → Websites → Notifications
2. Find localhost:8000 → Allow

---

## 🐛 Troubleshooting

### "WebSocket not connected" Error

**Check 1:** Is the server running?
```bash
curl http://localhost:8000/health
```
Should return: `{"status":"healthy"}`

**Check 2:** Check browser console (F12 → Console tab)
Look for connection errors. Common causes:
- Firewall blocking WebSocket
- Port 8000 already in use
- Server crashed (check terminal)

**Fix:** Restart server, check firewall settings

---

### "Failed to watch wallet" Error

**Check 1:** Did you configure RPC endpoints?
Open `stalker_service.py` and verify URLs are not placeholders.

**Check 2:** Are your RPC keys valid?
Test manually:
```bash
# Install wscat: npm install -g wscat
wscat -c "wss://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
```
Should connect without error.

**Fix:** Get valid API keys from provider

---

### No Activity Alerts

**Check 1:** Is the wallet actually active?
- Check on Etherscan if wallet has recent transactions
- Try with a known-active wallet (see table above)

**Check 2:** Check server logs
Server terminal should show:
```
[Stalker] 🚨 TARGET ACTIVE! 0x28C6c0... | Tx: 0xabc123... | Block: 0x112a880
```

**Check 3:** Verify subscription in console
Should see:
```
[Stalker] 👁️  Now watching: 0x28C6c0... (sub: 0x...)
```

---

### Panel Won't Stay Open

**Behavior:** Panel slides out immediately after appearing

**Cause:** No wallets being watched (this is normal behavior)

**Fix:** 
1. Analyze a wallet first
2. Then click "Watch Live"
3. Panel should stay open

---

## 🎯 What's Next?

### Scenario 1: Monitor Suspected Hacker
```
1. Investigate hack → identify attacker address
2. Analyze address in GATOR
3. Click "Watch Live"
4. Enable desktop notifications
5. Go about your day
6. Get alerted when hacker moves funds
```

### Scenario 2: Study Whale Behavior
```
1. Find whale address from on-chain data
2. Watch live for 24-48 hours
3. Document when they trade (time patterns)
4. Correlate with price movements
5. Identify their strategy
```

### Scenario 3: Bot Analysis
```
1. Suspect address is a bot
2. Analyze → High bot confidence? → Watch Live
3. Record exact reaction times to events
4. Verify bot hypothesis with live data
```

---

## ⚙️ Advanced Configuration

### Increase Watch Limit (Default: 5)

Edit `static/index.html`, line ~1262:
```javascript
if (Object.keys(watchedWallets).length >= 10) {  // Changed from 5
    alert('Maximum 10 wallets can be watched simultaneously.');
    return;
}
```

### Change Reconnect Behavior

Edit `static/index.html`, line ~1247:
```javascript
const MAX_RECONNECT_ATTEMPTS = 10;  // Changed from 5
```

### Add Auto-Analysis on Activity

Edit `static/index.html`, line ~1412:
```javascript
function handleWalletActivity(data) {
    // ... existing code ...
    
    // ADD THIS: Auto-trigger analysis
    currentAnalyzedWallet = data.wallet;
    currentAnalyzedChain = data.chain;
    analyzeWallet();  // This will re-analyze automatically
}
```

---

## 📊 Resource Usage

### Free Tier Limits (Alchemy)

- **3M Compute Units/month**
- **Watching 5 wallets**: ~500-1000 CU/hour
- **Estimated runtime**: ~3000-6000 hours/month (plenty!)

### Memory Usage

- Backend: ~50-100MB per WebSocket connection
- Frontend: ~10-20MB for panel state
- Total: Minimal impact

### Network Usage

- WebSocket: ~1-5 KB/second when idle
- Spike to ~50-100 KB/second during activity
- Monthly: <1GB for typical use

---

## 🔗 Helpful Links

- [Full Documentation](./LIVE_STALKER_MODE.md)
- [GATOR Main README](./README.md)
- [Backend API Docs](http://localhost:8000/docs) (when server running)
- [Alchemy Docs](https://docs.alchemy.com/)
- [Ethereum WebSocket Docs](https://ethereum.org/en/developers/docs/apis/json-rpc/#eth_subscribe)

---

## 🆘 Still Stuck?

**Check the logs:**
1. Browser Console (F12 → Console)
2. Server Terminal (where you ran `python run_server.py`)

**Common log messages:**

✅ **Good:**
```
[Stalker] Connected to ethereum WebSocket
[Stalker] 👁️  Now watching: 0x...
[Stalker] 🚨 TARGET ACTIVE!
```

❌ **Problems:**
```
[Stalker] Connection failed: ...
  → Check RPC URL and API key

[Stalker] Subscription failed: ...
  → Check if chain is supported

[Stalker] WebSocket error: ...
  → Check network/firewall
```

---

**🐊 You're All Set! Start Stalking! 🔴**

Remember: Only use for legitimate security research, investigation, and analysis purposes. Respect privacy and legal boundaries.

