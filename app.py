from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from dotenv import load_dotenv
import os
import time
import requests
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Get API keys
gemini_key = os.getenv("GOOGLE_API_KEY")
giphy_key = os.getenv("GIPHY_API_KEY", "")  # Optional: Get free key from developers.giphy.com

if not gemini_key:
    raise ValueError("❌ GOOGLE_API_KEY not found in .env file!")

# Configure Gemini API
genai.configure(api_key=gemini_key)

# Simple rate limiting tracker
request_times = []
MAX_REQUESTS_PER_MINUTE = 2

def check_rate_limit():
    """Check if we're within rate limits"""
    global request_times
    now = datetime.now()
    request_times = [t for t in request_times if now - t < timedelta(minutes=1)]
    
    if len(request_times) >= MAX_REQUESTS_PER_MINUTE:
        oldest_request = min(request_times)
        wait_time = 60 - (now - oldest_request).total_seconds()
        return False, int(wait_time)
    
    request_times.append(now)
    return True, 0

# Create FastAPI app
app = FastAPI(
    title="Gemini API Integration with Media",
    description="FastAPI app with Gemini AI and GIF search integration",
    version="2.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/home", response_class=HTMLResponse)
async def home_page():
    """Serve the HTML interface"""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Error: index.html not found</h1>", status_code=404)

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "✅ Welcome to Gemini API Integration with Media!",
        "endpoints": {
            "/home": "Access the web interface",
            "/generate": "Generate GIF/video ideas with Gemini AI",
            "/search-gif": "Search for actual GIFs based on keywords",
            "/models": "List available Gemini models"
        },
        "features": [
            "AI-powered content idea generation",
            "Real GIF search and display",
            "Rate limiting protection",
            "Professional error handling"
        ]
    }

@app.get("/models")
async def list_models():
    """List available Gemini models and test which ones work"""
    try:
        all_models = genai.list_models()
        generate_models = []
        all_model_info = []
        
        for m in all_models:
            model_info = {
                "name": m.name,
                "display_name": m.display_name if hasattr(m, 'display_name') else m.name,
                "supported_methods": m.supported_generation_methods
            }
            all_model_info.append(model_info)
            
            if 'generateContent' in m.supported_generation_methods:
                generate_models.append(model_info)
        
        # Test which models actually work
        working_models = []
        test_models = [
            "gemini-2.0-flash-exp",
            "gemini-exp-1206", 
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-pro"
        ]
        
        for model_name in test_models:
            try:
                test_model = genai.GenerativeModel(model_name)
                # Try a simple generation to verify it works
                test_response = test_model.generate_content("Hi")
                if test_response.text:
                    working_models.append({
                        "name": model_name,
                        "status": "✅ Working",
                        "test_response_length": len(test_response.text)
                    })
            except Exception as e:
                working_models.append({
                    "name": model_name,
                    "status": "❌ Not Available",
                    "error": str(e)[:100]
                })
        
        return {
            "status": "success",
            "working_models": working_models,
            "all_models_with_generateContent": generate_models,
            "total_models_found": len(all_model_info),
            "recommendation": "Use the first working model from the list"
        }
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

@app.get("/search-gif")
async def search_gif(query: str = Query(..., description="Search term for GIF")):
    """
    Search for GIFs using Giphy API (or Tenor as fallback)
    """
    try:
        # Try Giphy first (if API key available)
        if giphy_key:
            url = f"https://api.giphy.com/v1/gifs/search?api_key={giphy_key}&q={query}&limit=6&rating=g"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                gifs = []
                for item in data.get('data', [])[:6]:
                    gifs.append({
                        "url": item['images']['fixed_height']['url'],
                        "title": item.get('title', 'GIF'),
                        "source": "Giphy"
                    })
                
                return {
                    "status": "success",
                    "query": query,
                    "gifs": gifs,
                    "count": len(gifs)
                }
        
        # Fallback to Tenor (no API key needed for basic usage)
        tenor_url = f"https://tenor.googleapis.com/v2/search?q={query}&key=AIzaSyAyimkuYQYF_FXVALexPuGQctUWRURdCYQ&limit=6"
        response = requests.get(tenor_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            gifs = []
            for item in data.get('results', [])[:6]:
                gifs.append({
                    "url": item['media_formats']['gif']['url'],
                    "title": item.get('content_description', 'GIF'),
                    "source": "Tenor"
                })
            
            return {
                "status": "success",
                "query": query,
                "gifs": gifs,
                "count": len(gifs)
            }
        
        return JSONResponse(
            {"status": "error", "error": "Failed to fetch GIFs"},
            status_code=500
        )
        
    except Exception as e:
        return JSONResponse(
            {"status": "error", "error": f"GIF search failed: {str(e)}"},
            status_code=500
        )

@app.get("/generate")
async def generate(
    prompt: str = Query(..., description="Enter prompt text for Gemini AI"),
    include_media: bool = Query(False, description="Also search for related GIFs")
):
    """
    Generate creative content using Gemini AI and optionally find related GIFs
    """
    try:
        # Check rate limit
        can_proceed, wait_time = check_rate_limit()
        if not can_proceed:
            return JSONResponse(
                {
                    "status": "rate_limited",
                    "error": f"Rate limit exceeded. Free tier allows {MAX_REQUESTS_PER_MINUTE} requests per minute.",
                    "wait_seconds": wait_time,
                    "message": f"Please wait {wait_time} seconds before trying again."
                },
                status_code=429
            )
        
        if not prompt or len(prompt.strip()) == 0:
            return JSONResponse(
                {"status": "error", "error": "Prompt cannot be empty"}, 
                status_code=400
            )
        
        # Try models - using the latest Gemini 2.x models
        model_names = [
            "gemini-2.0-flash-exp",      # Gemini 2.0 Flash (fastest)
            "gemini-exp-1206",            # Gemini 2.5 Pro experimental
            "gemini-2.0-flash",           # Stable Gemini 2.0 Flash
            "gemini-pro"                  # Fallback
        ]
        model = None
        model_name = None
        
        for name in model_names:
            try:
                model = genai.GenerativeModel(name)
                model_name = name
                print(f"✅ Successfully using model: {name}")
                break
            except Exception as e:
                print(f"❌ Failed to use model {name}: {str(e)}")
                continue
        
        if not model:
            raise Exception("No available models found")
        
        # Generate AI response
        response = model.generate_content(prompt)
        
        if not response.text:
            return JSONResponse(
                {"status": "error", "error": "No response generated"}, 
                status_code=500
            )
        
        result = {
            "status": "success",
            "model_used": model_name,
            "prompt": prompt,
            "output": response.text,
            "idea": response.text,
            "requests_remaining": MAX_REQUESTS_PER_MINUTE - len(request_times)
        }
        
        # Optionally search for related GIFs
        if include_media:
            # Extract keywords from prompt for GIF search
            keywords = prompt.lower().replace("create", "").replace("generate", "").replace("gif", "").replace("video", "").strip()
            if len(keywords) > 50:
                keywords = keywords[:50]
            
            try:
                gif_response = await search_gif(keywords)
                if gif_response.get("status") == "success":
                    result["related_gifs"] = gif_response.get("gifs", [])
            except:
                pass  # Don't fail if GIF search fails
        
        return JSONResponse(result)
    
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower():
            import re
            wait_match = re.search(r'retry in (\d+)', error_str)
            wait_seconds = int(wait_match.group(1)) if wait_match else 60
            
            return JSONResponse(
                {
                    "status": "quota_exceeded",
                    "error": "API quota exceeded. Free tier limit: 2 requests per minute.",
                    "wait_seconds": wait_seconds,
                    "message": f"Please wait {wait_seconds} seconds and try again."
                },
                status_code=429
            )
        
        print(f"❌ Error: {str(e)}")
        return JSONResponse(
            {"status": "error", "error": f"Failed to generate content: {str(e)}"},
            status_code=500
        )