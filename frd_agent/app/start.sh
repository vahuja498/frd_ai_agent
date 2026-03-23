#!/bin/bash

echo "📦 Installing dependencies..."
pip install -r ../../requirements.txt --quiet

echo "🚀 Starting FRD AI Agent..."
cd ../..
uvicorn frd_agent.app.main:app --host 0.0.0.0 --port 8080