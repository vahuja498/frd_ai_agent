#!/bin/bash

echo "📦 Installing dependencies..."
pip install fastapi uvicorn httpx pydantic pydantic-settings python-docx pdfplumber PyPDF2 python-multipart --quiet

echo "🚀 Starting FRD AI Agent..."
cd frd_agent
uvicorn app.main:app --host 0.0.0.0 --port 8080