# 🐊 GATOR - Complete Setup Guide

## What Changed

✅ **Transaction Limit Removed** - Now fetches ALL available transactions (up to 1000)
✅ **Beautiful Dark UI** - Matches your design screenshots exactly
✅ **Fully Functional Charts** - All visualizations connected to real backend data
✅ **Comprehensive Analysis** - Activity patterns, geographic origin, risk assessment, and more

## Quick Start

### 1. Install Dependencies

```bash
pip install fastapi uvicorn pydantic requests pandas matplotlib numpy
```

### 2. Start the Server

```bash
cd Gator
python run_server.py
```

You should see:
```
🐊 Gator OSINT Backend Server
============================================================
Starting server...
Frontend will be available at: http://localhost:8000
```

### 3. Open in Browser

Go to: **http://localhost:8000**

### 4. Analyze a Wallet

1. Paste a Solana wallet address in the search box
2. Click "Analyze" or press Enter
3. Watch the loading animation
4. Scroll down to see all the beautiful charts and insights!

## Features

### 📊 What You'll See

1. **Wallet Info Card**
   - Wallet address (shortened)
   - Confidence level
   - Total transactions analyzed

2. **Activity Pattern (24h)**
   - Blue bar chart showing hourly activity
   - Detects sleep patterns and timezone

3. **Geographic Origin**
   - Doughnut chart showing likely location
   - Asia/Pacific, Europe, Americas breakdown

4. **Weekly Pattern**
   - Bar chart showing activity by day
   - Weekend vs weekday patterns
   - Retail vs professional trader detection

5. **Trader Classification**
   - Pie chart: Professional vs Retail vs Institutional

6. **Transaction Complexity**
   - Scatter plot of compute units over time
   - Color-coded by complexity: Standard, Jito Bundle, Complex

7. **Risk Assessment**
   - Bar chart: Low/Medium/High risk

8. **Key Insights**
   - Automated bullet points with findings
   - Bot detection
   - Geographic insights
   - Trading pattern analysis

9. **Profile Classification**
   - Beautiful horizontal bars showing:
     - Bot probability
     - Institutional
     - Whale
     - Airdrop Farmer
     - Professional

## API Endpoints

### POST `/analyze-wallet`

Comprehensive wallet analysis with ALL data.

**Request:**
```json
{
  "wallet": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
}
```

**Response:** Complete analysis including all charts data

## Customization

### Change Colors

Edit `static/index.html` and modify the color variables:

```javascript
backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444']
```

### Change Transaction Limit

In `backend_api.py`, line 98:

```python
df = analyze_wallet(request.wallet, limit=1000)  # Change 1000 to any number
```

### Add More Charts

1. Add a new canvas in HTML
2. Create chart in JavaScript using Chart.js
3. Connect to backend data

## Troubleshooting

### Charts Not Showing

- Make sure Chart.js CDN is loading (check browser console)
- Verify backend is returning data

### Loading Forever

- Check browser console for errors
- Verify API_BASE URL matches your server
- Make sure wallet address is valid

### Slow Performance

- Reduce transaction limit in backend
- Use fewer data points in scatter plot

## Example Wallets to Test

```
5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1
```

## Technical Details

- **Frontend**: Vanilla JS + Chart.js 4.4.0
- **Backend**: FastAPI + Python
- **Charts**: Chart.js (bar, doughnut, scatter)
- **Animations**: CSS transitions and keyframes
- **Responsive**: Works on mobile and desktop

Enjoy your beautiful Gator analytics dashboard! 🐊



