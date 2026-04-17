# Testing Setup Guide

## Prerequisites Checklist
- [ ] Backend Python environment activated
- [ ] Frontend built and ready
- [ ] Firecrawl API key configured
- [ ] OpenAI API key configured
- [ ] Database running and migrations applied

## STEP 1: Verify Backend Setup

```bash
# Navigate to backend
cd c:\Users\Arunabha\Desktop\Major\code\chatbot-backend

# Activate virtual environment
.venv\Scripts\activate

# Check environment variables are set
echo $env:OPENAI_API_KEY  # Should show a key
echo $env:FIRECRAWL_API_KEY  # Should show a key
```

## STEP 2: Start Backend Server

```bash
# From chatbot-backend directory
python -m uvicorn app.main:app --reload --port 8000

# You should see:
# INFO:     Started server process
# INFO:     Uvicorn running on http://127.0.0.1:8000
# INFO:     Application startup complete
```

## STEP 3: Start Frontend (in new terminal)

```bash
cd c:\Users\Arunabha\Desktop\Major\code\chatbot-web

# Install dependencies if needed
pnpm install

# Start development server
pnpm dev

# You should see:
# ▲ Next.js 15.x.x
# - Local: http://localhost:3000
```

## STEP 4: Open the Application

1. Open browser: http://localhost:3000
2. Login with test credentials
3. Start new chat conversation

## Testing Workflow

### For Each Test Prompt:

1. **Copy the prompt** from TEST_PROMPTS.md
2. **Send to agent** in chat interface
3. **Observe tools called** (look at backend terminal logs)
4. **Note the response** time and quality
5. **Manual verification** using the provided sources
6. **Record results** in testing sheet

### What to Look For:

#### In Backend Console:
```
# You should see logs like:
2026-04-17 16:30:45 - Tool: search_flights
2026-04-17 16:30:46 - Query: Pune to Delhi May 15, 2026
2026-04-17 16:30:52 - Result: Found 12 flights
```

#### In Frontend Response:
- Agent should cite tools used
- Should provide formatted results
- Should link to booking/reservation pages
- Should ask clarifying questions if needed

## Monitoring & Debugging

### Check Backend Health
```bash
# In separate terminal
curl http://127.0.0.1:8000/api/v1/health

# Should return: {"status": "ok"}
```

### View Logs
```bash
# Tail the logs in real-time
Get-Content -Tail 50 -Wait logs/app.log
```

### Common Issues & Fixes

#### Issue: "OPENAI_API_KEY not found"
**Fix:**
```bash
$env:OPENAI_API_KEY = "your-key-here"
# Or add to .env file in chatbot-backend/
```

#### Issue: "Firecrawl API error"
**Fix:**
```bash
# Check FIRECRAWL_API_KEY is set
$env:FIRECRAWL_API_KEY = "your-key-here"
# Check API key has quota remaining
```

#### Issue: "Tool returns empty results"
**Fix:**
```bash
# Check tool logs in backend terminal
# Verify API endpoints are responsive
# Check rate limits (Firecrawl has 100 calls/day free)
```

#### Issue: "Frontend can't connect to backend"
**Fix:**
```bash
# Check backend is running on port 8000
netstat -ano | findstr :8000

# Clear CORS errors by checking:
# - Backend CORS settings in app/main.py
# - Frontend API calls are using correct URL
```

## Test Data Available

### Real Routes to Test:
- **Domestic India**: Pune↔Delhi, Mumbai↔Bangalore, Delhi↔Jaipur
- **International**: India→Bangkok, India→Singapore, India→Dubai
- **European**: Paris, Rome, Barcelona, London, Amsterdam
- **Asia**: Tokyo, Bangkok, Bali, Singapore

### Test Dates (All in 2026):
- April 20-30: Spring travel, good weather
- May 1-15: Peak travel season
- May 20-31: Summer season begins

## Stopping the Servers

```bash
# Backend: Press Ctrl+C in backend terminal
# Frontend: Press Ctrl+C in frontend terminal

# Or from PowerShell:
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9
lsof -i :3000 | grep LISTEN | awk '{print $2}' | xargs kill -9
```

## Success Criteria

✅ **All systems ready when:**
- [ ] Backend API responds to `/api/v1/health`
- [ ] Frontend loads and you can login
- [ ] New chat opens successfully
- [ ] First message to agent completes without errors
- [ ] Backend logs show tool invocations
- [ ] Frontend displays agent response with formatting

## Testing Phase Progression

### Phase 1: Basic Functionality (CATEGORY 1-2)
- Test flight search (HIGHEST PRIORITY - recently fixed)
- Test hotel search
- ~15 minutes

### Phase 2: Secondary Features (CATEGORY 3-5)
- Test ground transport
- Test attractions and weather
- ~20 minutes

### Phase 3: Advanced Integration (CATEGORY 6-7)
- Test web search
- Test multi-tool itineraries
- ~20 minutes

### Phase 4: Error Handling (CATEGORY 8)
- Test invalid inputs
- Test edge cases
- ~10 minutes

**Total estimated testing time: 60-75 minutes**

## Documentation During Testing

Keep a testing log with:
- Test number and name
- Exact prompt sent
- Tools called (from logs)
- Agent response quality (1-5 stars)
- Manual verification result (MATCH/MISMATCH)
- Any errors encountered
- Time taken for response

This will help identify:
- Which tools are working
- Which need parameter fixes
- Which have API issues
- Performance bottlenecks

---

**Ready to begin testing? Start with the backend server!** 🚀
