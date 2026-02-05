#!/usr/bin/env python3 
"""Entry point for Render deployment""" 
import uvicorn 
import os 
ECHO is on.
if __name__ == "__main__": 
    port = int(os.getenv("PORT", 8000)) 
    uvicorn.run("app.main:app", host="0.0.0.0", port=port) 
