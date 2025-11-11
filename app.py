from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from dotenv import load_dotenv
import os
import requests

load_dotenv()

gemini_key = os.getenv("GOOGLE_API_KEY")
giphy_key = os.getenv("GIPHY_API_KEY", "")

if not gemini_key:
    raise ValueError("❌ GOOGLE_API_KEY not found!")

genai.configure(api_key=gemini_key)

app = FastAPI(title="Gemini API Integration", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/home", response_class=HTMLResponse)
async def home_page():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Error: index.html not found</h1>", status_code=404)

@app.get("/")
async def root():
    return {
        "message": "✅ Gemini API Integration - v3.0",
        "status": "running",
        "endpoints": {
            "/home": "Web interface",
            "/generate": "Generate content",
            "/search-gif": "Search GIFs"
        }
    }

@app.get("/search-gif")
async def search_gif(query: str = Query(..., description="Search term")):
    try:
        if giphy_key:
            url = f"https://api.giphy.com/v1/gifs/search?api_key={giphy_key}&q={query}&limit=6&rating=g"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                gifs = [
                    {
                        "url": item['images']['fixed_height']['url'],
                        "title": item.get('title', 'GIF'),
                        "source": "Giphy"
                    }
                    for item in data.get('data', [])[:6]
                ]
                return {"status": "success", "query": query, "gifs": gifs, "count": len(gifs)}
        
        # Fallback to Tenor
        tenor_url = f"https://tenor.googleapis.com/v2/search?q={query}&key=AIzaSyAyimkuYQYF_FXVALexPuGQctUWRURdCYQ&limit=6"
        response = requests.get(tenor_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            gifs = [
                {
                    "url": item['media_formats']['gif']['url'],
                    "title": item.get('content_description', 'GIF'),
                    "source": "Tenor"
                }
                for item in data.get('results', [])[:6]
            ]
            return {"status": "success", "query": query, "gifs": gifs, "count": len(gifs)}
        
        return JSONResponse({"status": "error", "error": "Failed to fetch GIFs"}, status_code=500)
        
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

@app.get("/generate")
async def generate(
    prompt: str = Query(..., description="Prompt text"),
    include_media: bool = Query(False, description="Include GIFs")
):
    try:
        if not prompt or not prompt.strip():
            return JSONResponse({"status": "error", "error": "Prompt cannot be empty"}, status_code=400)
        
        # Try models in order
        models_to_try = ["gemini-2.0-flash", "gemini-2.5-pro", "gemini-pro"]
        model = None
        model_name = None
        
        for name in models_to_try:
            try:
                model = genai.GenerativeModel(name)
                model_name = name
                break
            except:
                continue
        
        if not model:
            return JSONResponse(
                {"status": "error", "error": "No Gemini models available"},
                status_code=503
            )
        
        # Generate content
        try:
            print(f"📝 Generating with {model_name}: {prompt[:50]}...")
            response = model.generate_content(prompt)
            
            if not response or not response.text:
                return JSONResponse(
                    {"status": "error", "error": "Empty response from API"},
                    status_code=500
                )
            
            result = {
                "status": "success",
                "model_used": model_name,
                "prompt": prompt,
                "output": response.text,
                "idea": response.text
            }
            
            # Add GIFs if requested
            if include_media:
                keywords = prompt.lower()
                for word in ["create", "generate", "gif", "video", "make", "show", "design", "a", "the"]:
                    keywords = keywords.replace(word, "")
                keywords = " ".join(keywords.split())[:50]
                
                if keywords:
                    try:
                        gif_data = await search_gif(keywords)
                        if isinstance(gif_data, dict) and gif_data.get("status") == "success":
                            result["related_gifs"] = gif_data.get("gifs", [])
                    except:
                        pass
            
            print(f"✅ Success!")
            return JSONResponse(result)
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ API Error: {error_msg}")
            
            # Handle rate limiting from Google
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                return JSONResponse(
                    {
                        "status": "quota_exceeded",
                        "error": "Google Gemini API rate limit exceeded",
                        "wait_seconds": 60,
                        "message": "Google's free tier has strict limits. Please wait 60 seconds.",
                        "tip": "Get a new API key from https://aistudio.google.com/apikey or upgrade your quota"
                    },
                    status_code=429
                )
            
            # Handle authentication errors
            if "API" in error_msg and ("key" in error_msg.lower() or "auth" in error_msg.lower()):
                return JSONResponse(
                    {
                        "status": "error",
                        "error": "API key issue",
                        "message": "Your Google API key may be invalid. Get a new one from https://aistudio.google.com/apikey"
                    },
                    status_code=401
                )
            
            # Generic error
            return JSONResponse(
                {"status": "error", "error": f"Generation failed: {error_msg[:150]}"},
                status_code=500
            )
    
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return JSONResponse(
            {"status": "error", "error": f"Unexpected error: {str(e)[:150]}"},
            status_code=500
        )