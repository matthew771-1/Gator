# How to Run Gator on Local Server

## Quick Start

### Option 1: Using the Run Script (Easiest)

1. **Install dependencies:**
   ```bash
   pip install fastapi uvicorn pydantic
   ```

2. **Start the server:**
   ```bash
   cd Gator
   python run_server.py
   ```

3. **Open your browser:**
   - Go to: `http://localhost:8000`
   - The frontend will load automatically!

### Option 2: Using uvicorn directly

1. **Install dependencies:**
   ```bash
   pip install fastapi uvicorn pydantic
   ```

2. **Start the server:**
   ```bash
   cd Gator
   uvicorn backend_api:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Open your browser:**
   - Frontend: `http://localhost:8000`
   - API Docs: `http://localhost:8000/docs`

### Option 3: Using Python's HTTP Server (Frontend Only)

If you just want to test the frontend separately:

1. **Start a simple HTTP server:**
   ```bash
   cd Gator/static
   python -m http.server 8080
   ```

2. **Open your browser:**
   - Go to: `http://localhost:8080/index.html`
   - **Note:** Make sure the backend is also running on port 8000 for the API calls to work!

## Full Setup Instructions

### Step 1: Install Python Dependencies

```bash
pip install fastapi uvicorn pydantic requests pandas matplotlib numpy
```

### Step 2: Start the Backend Server

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
API docs will be available at: http://localhost:8000/docs
```

### Step 3: Access the Application

- **Main Frontend:** http://localhost:8000
- **API Documentation:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

## Troubleshooting

### Port Already in Use

If port 8000 is already in use, change it:

```python
# In run_server.py, change:
uvicorn.run(..., port=8001)  # Use different port
```

Then update the frontend API URL in `static/index.html`:
```javascript
const API_BASE = 'http://localhost:8001';  // Match the port
```

### CORS Errors

The backend already has CORS enabled, but if you see CORS errors:
- Make sure you're accessing via `http://localhost:8000` (not `file://`)
- Check that the backend is running

### Frontend Not Loading

- Make sure the `static/` directory exists with `index.html`
- Check the server logs for errors
- Try accessing `http://localhost:8000/static/index.html` directly

## Testing the API

You can test the API endpoints directly:

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test mempool forensics
curl -X POST http://localhost:8000/mempool-forensics \
  -H "Content-Type: application/json" \
  -d '{"wallet": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", "limit": 50}'
```

## Production Deployment

For production, use a proper ASGI server like Gunicorn:

```bash
pip install gunicorn
gunicorn backend_api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```



