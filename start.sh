#!/bin/bash
set -e

cd /home/runner/workspace

echo "🐍 Creating venv..."
python3 -m venv .venv

echo "🔌 Activating venv..."
. .venv/bin/activate

echo "🚫 Removing Nix interference..."
unset PIP_CONFIG_FILE
unset PYTHONPATH

echo "📦 Installing dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "🚀 Starting app..."
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}