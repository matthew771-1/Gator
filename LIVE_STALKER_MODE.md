# Live "Stalker" Mode - Real-Time Wallet Monitoring

## Overview

Live Stalker Mode transforms GATOR from a historical analysis tool to a **real-time surveillance system**. Instead of analyzing what a wallet *did*, you can now watch what it's doing *right now*. This feature uses WebSocket connections to EVM chains (Ethereum, Base, Arbitrum, Optimism, Polygon) to receive instant notifications when watched wallets execute transactions.

## 🎯 Use Cases

- **Security**: "Wake me up when the hacker moves the stolen funds"
- **Trading**: Monitor whale wallets for instant position changes
- **Investigation**: Track suspect addresses in real-time during active incidents
- **Research**: Study bot behavior as it happens live

---

## 🏗️ Architecture

### Backend Components

1. **`stalker_service.py`** - Core WebSocket monitoring service
   - Manages persistent WSS connections to EVM RPC providers
   - Handles multiple wallet subscriptions over a single connection
   - Implements debouncing to avoid duplicate alerts
   - Tracks wallet activity states and timestamps

2. **`backend_api.py`** - FastAPI WebSocket endpoint
   - Endpoint: `ws://localhost:8000/ws/stalker`
   - Manages client connections and broadcasts events
   - Integrates with existing wallet analysis functions

### Frontend Components

1. **Live Stalker Panel** - Fixed floating panel (top-right)
   - Shows all actively watched wallets (max 5 simultaneously)
   - Real-time status updates: 🟢 Active / ⚪ Idle
   - Last activity timestamps
   - Individual stop watching controls

2. **Watch Live Button** - Appears after wallet analysis
   - One-click to start/stop monitoring
   - Visual feedback when watching
   - Persists across panel collapse

3. **WebSocket Client** - JavaScript implementation
   - Auto-reconnection with exponential backoff
   - Desktop notifications for wallet activity
   - In-app flash alerts with visual feedback

---

## 🚀 Quick Start

### Step 1: Configure RPC WebSocket Endpoints

Edit `stalker_service.py` and add your RPC provider WebSocket URLs:

```python
EVM_WSS_ENDPOINTS = {
    "ethereum": "wss://eth-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "base": "wss://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "arbitrum": "wss://arb-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "optimism": "wss://opt-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
    "polygon": "wss://polygon-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"
}
```

**Recommended Providers:**
- Alchemy (free tier: 3M compute units/month)
- Infura (free tier: 100k requests/day)
- QuickNode (free tier: 1 endpoint)

### Step 2: Install Dependencies

```bash
pip install websockets fastapi uvicorn
```

### Step 3: Start the Server

```bash
cd Gator
python run_server.py
```

### Step 4: Use Stalker Mode

1. Navigate to `http://localhost:8000`
2. Analyze any EVM wallet (Ethereum, Base, etc.)
3. Click the **"👁️ Watch Live"** button
4. The Live Stalker panel will appear in the top-right corner
5. You'll receive instant alerts when the wallet becomes active

---

## 📡 WebSocket Protocol

### Client → Server Commands

#### Watch a Wallet
```json
{
  "action": "watch",
  "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
  "chain": "ethereum"
}
```

#### Stop Watching
```json
{
  "action": "unwatch",
  "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
  "chain": "ethereum"
}
```

#### Request Status
```json
{
  "action": "status",
  "chain": "ethereum"
}
```

### Server → Client Events

#### Connection Confirmed
```json
{
  "type": "connected",
  "message": "Stalker mode ready"
}
```

#### Watch Started
```json
{
  "type": "watch_started",
  "wallet": "0x742d35Cc...",
  "chain": "ethereum",
  "message": "Now watching 0x742d35Cc..."
}
```

#### Wallet Activity (🚨 KEY EVENT)
```json
{
  "type": "wallet_activity",
  "data": {
    "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
    "tx_hash": "0xabc123...",
    "block_number": "0x112a880",
    "timestamp": "2025-12-29T10:30:45.123456",
    "chain": "ethereum",
    "event_data": { ... }
  }
}
```

#### Status Update
```json
{
  "type": "status_update",
  "chain": "ethereum",
  "wallets": {
    "0x742d35Cc...": {
      "state": "active",
      "last_activity": "5s ago",
      "last_activity_timestamp": "2025-12-29T10:30:40",
      "tx_count": 3
    }
  }
}
```

#### Error
```json
{
  "type": "error",
  "message": "Failed to subscribe to wallet"
}
```

---

## ⚙️ Configuration & Limits

### Current Limits

| Setting | Value | Reason |
|---------|-------|--------|
| Max Watched Wallets | 5 | Prevent resource exhaustion |
| Reconnect Attempts | 5 | Avoid infinite loops |
| Reconnect Delay | 3 seconds | Allow time for RPC recovery |
| Debounce Window | 100 tx per wallet | Prevent duplicate alerts |

### Adjusting Limits

Edit `static/index.html`:

```javascript
// Increase max watched wallets (line ~1262)
if (Object.keys(watchedWallets).length >= 5) {  // Change to 10
    alert('Maximum 5 wallets...');  // Update message
    return;
}
```

Edit `backend_api.py`:

```python
# Add rate limiting to WebSocket endpoint
@app.websocket("/ws/stalker")
async def stalker_websocket(websocket: WebSocket):
    # Add rate limiter here if needed
    ...
```

---

## 🔧 Troubleshooting

### Issue: WebSocket Won't Connect

**Symptoms:**
- "WebSocket not connected" errors in console
- Watch Live button does nothing

**Solutions:**
1. Check if backend is running: `http://localhost:8000/health`
2. Verify WebSocket URL in browser console
3. Check firewall/antivirus blocking WebSocket connections
4. Try different port in `run_server.py` and update frontend

### Issue: No Activity Alerts

**Symptoms:**
- Wallet shows as "Idle" even when active
- No desktop notifications

**Solutions:**
1. **Verify RPC WebSocket endpoints are configured correctly**
2. Check if wallet is actually active on block explorer
3. Enable desktop notifications when prompted
4. Check browser console for WebSocket messages
5. For EVM chains: subscription filter may need adjustment

### Issue: Connection Drops Frequently

**Symptoms:**
- Panel disappears randomly
- "Reconnecting..." messages in console

**Solutions:**
1. Use a more reliable RPC provider (Alchemy > free public RPCs)
2. Increase reconnect attempts in `stalker_service.py`
3. Check your internet connection stability
4. Reduce number of watched wallets

### Issue: Duplicate Alerts

**Symptoms:**
- Multiple notifications for same transaction

**Solutions:**
1. Debouncing is already implemented in `stalker_service.py`
2. Check `_handle_wallet_activity()` method
3. Increase debounce cache size if needed (currently 100 tx)

---

## 🔐 Security & Privacy

### Data Handling

- **No Private Data**: Only watches public blockchain data
- **No Logging**: Wallet addresses are not persisted server-side
- **Client-Side State**: Watch list stored in browser memory only
- **No Authentication**: Currently open (add auth for production)

### Production Recommendations

1. **Add Authentication**
   ```python
   @app.websocket("/ws/stalker")
   async def stalker_websocket(websocket: WebSocket, token: str = Query(...)):
       if not verify_token(token):
           await websocket.close(code=1008, reason="Unauthorized")
           return
   ```

2. **Rate Limiting**
   ```python
   from slowapi import Limiter
   limiter = Limiter(key_func=get_remote_address)
   
   @app.websocket("/ws/stalker")
   @limiter.limit("10/minute")
   async def stalker_websocket(websocket: WebSocket):
       ...
   ```

3. **Use WSS (TLS)**
   - Deploy behind nginx/caddy with SSL certificate
   - Update frontend to use `wss://` instead of `ws://`

4. **Monitor Resource Usage**
   - Track number of active WebSocket connections
   - Set maximum connections per IP
   - Implement connection timeout (e.g., 1 hour)

---

## 🎨 Customization

### Change Panel Position

Edit `static/index.html` CSS:

```css
.stalker-panel {
    position: fixed;
    top: 20px;        /* Change to bottom: 20px; */
    right: 20px;      /* Change to left: 20px; */
    width: 380px;
    ...
}
```

### Change Alert Colors

```css
/* Active state (green by default) */
.stalker-status-badge.active {
    background: rgba(16, 185, 129, 0.15);  /* Change to your color */
    color: #10b981;
}

/* Watch button (red by default) */
.watch-btn {
    border-color: rgba(239, 68, 68, 0.4);  /* Change to your color */
    color: #ef4444;
}
```

### Add Custom Alerts

Edit `handleWalletActivity()` in `static/index.html`:

```javascript
function handleWalletActivity(data) {
    const wallet = data.wallet;
    
    // Custom alert: Play sound
    const audio = new Audio('/static/alert.mp3');
    audio.play();
    
    // Custom alert: Send to Discord webhook
    fetch('YOUR_DISCORD_WEBHOOK', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            content: `🚨 Wallet ${wallet} is active! Tx: ${data.tx_hash}`
        })
    });
    
    // Existing code...
}
```

---

## 🧪 Testing

### Test WebSocket Connection

```bash
# Install wscat
npm install -g wscat

# Connect to stalker endpoint
wscat -c ws://localhost:8000/ws/stalker

# Send watch command
> {"action": "watch", "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb", "chain": "ethereum"}

# You should receive:
< {"type":"connected","message":"Stalker mode ready"}
< {"type":"watch_started","wallet":"0x742d35Cc...","chain":"ethereum"}
```

### Test with Known Active Wallet

Use a known-active wallet for testing:
- Binance Hot Wallet: `0x28C6c06298d514Db089934071355E5743bf21d60`
- Uniswap Router: `0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D`

These wallets have constant activity, so you should see alerts within minutes.

### Mock Activity (Development)

Add test button to frontend:

```html
<button onclick="testActivity()">Test Activity Alert</button>

<script>
function testActivity() {
    handleWalletActivity({
        wallet: currentAnalyzedWallet,
        tx_hash: '0xtest123...',
        block_number: '0x112a880',
        timestamp: new Date().toISOString(),
        chain: currentAnalyzedChain
    });
}
</script>
```

---

## 🚀 Future Enhancements

### Planned Features

- [ ] **Auto-Scan on Activity**: Automatically trigger profile analysis when wallet becomes active
- [ ] **Webhook Support**: Send alerts to Discord, Telegram, Slack
- [ ] **Mobile App**: Push notifications to phone
- [ ] **Transaction Filtering**: Only alert on high-value transactions
- [ ] **Multi-Chain Aggregation**: Watch same address across multiple chains
- [ ] **Historical Playback**: Replay wallet activity from past 24h
- [ ] **Alert Patterns**: "Alert me when wallet moves >$10k" or "Alert when bot-like activity"
- [ ] **Solana Support**: Extend to Solana using existing `jito_scan.py` infrastructure

### Contributing

To add a new feature:

1. Update `stalker_service.py` for backend logic
2. Update `backend_api.py` WebSocket endpoint if needed
3. Update frontend JavaScript in `static/index.html`
4. Update this documentation
5. Add tests

---

## 📚 References

- [WebSocket API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [Ethereum JSON-RPC (WebSocket)](https://ethereum.org/en/developers/docs/apis/json-rpc/#eth_subscribe)
- [Alchemy WebSocket API](https://docs.alchemy.com/reference/ethereum-websockets-api)

---

## 📄 License & Credits

Part of the GATOR OSINT Suite.

**Live Stalker Mode** implemented as Task 2: "Live 'Stalker' Mode (WebSockets)" - Moving from "History" to "Now."

---

## ❓ FAQ

**Q: Does this work with Solana?**  
A: Not yet. The backend infrastructure exists (`jito_scan.py`), but it's not integrated with the API. Solana support is planned for a future update.

**Q: Can I watch the same wallet across multiple chains?**  
A: Not simultaneously. You'd need to analyze and watch it separately on each chain. Multi-chain aggregation is a planned feature.

**Q: Will this drain my RPC provider quota?**  
A: WebSocket subscriptions use minimal resources compared to HTTP polling. A single connection can monitor multiple wallets efficiently. Alchemy's free tier (3M compute units/month) is sufficient for ~5-10 watched wallets.

**Q: Can I self-host my own node?**  
A: Yes! Point the WSS URL to your own Geth/Erigon node with WebSocket enabled. This is the most reliable option for production use.

**Q: What if the wallet is a contract?**  
A: Stalker Mode watches for any transaction involving the address, whether it's an EOA or contract. You'll see activity when the contract is called or calls other contracts.

**Q: Can I watch ENS names instead of addresses?**  
A: Not directly. Resolve the ENS name to an address first, then watch the address. ENS resolution is planned for a future update.

---

**🐊 Happy Stalking!**

