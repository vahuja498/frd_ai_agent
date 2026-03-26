"""
Health Check Routes
Includes a Gemini debug endpoint for diagnosing AI provider issues.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter
from datetime import datetime

from app.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic liveness check."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "FRD AI Agent",
    }


@router.get("/health/ready")
async def readiness_check():
    """Readiness check — confirms config is loaded correctly."""
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "gemini_model": settings.GEMINI_MODEL,
        "hf_configured": bool(settings.HF_API_TOKEN),
        "hf_model": settings.HF_MODEL,
        "ado_configured": bool(settings.ADO_PAT),
        "ado_org": settings.ADO_ORG_URL,
        "ado_project": settings.ADO_PROJECT,
    }


@router.get("/debug/gemini-test")
async def test_gemini():
    """
    Test Gemini API connectivity and authentication directly.
    Use this to diagnose AI provider issues without triggering a full webhook.

    Visit: /debug/gemini-test
    Expected response when working:
        { "status": "ok", "http_status": 200, "model": "gemini-2.0-flash", ... }
    """
    key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL

    if not key:
        return {
            "status": "error",
            "reason": "GEMINI_API_KEY is empty — check Azure Portal environment variables",
        }

    if not model:
        return {
            "status": "error",
            "reason": "GEMINI_MODEL is empty — check Azure Portal environment variables",
        }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "contents": [
            {"parts": [{"text": "Say exactly: Gemini is working correctly."}]}
        ],
        "generationConfig": {
            "maxOutputTokens": 50,
            "temperature": 0.1,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)

        response_body = resp.json()

        if resp.status_code == 200:
            # Extract the text response
            candidates = response_body.get("candidates", [])
            text_output = ""
            for candidate in candidates:
                parts = candidate.get("content", {}).get("parts", [])
                text_output = " ".join(
                    p.get("text", "") for p in parts if p.get("text")
                )
                break

            return {
                "status": "ok",
                "http_status": 200,
                "model": model,
                "key_prefix": key[:12] + "...",
                "gemini_response": text_output,
            }
        else:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "model": model,
                "key_prefix": key[:12] + "...",
                "error_body": response_body,
                "hint": _error_hint(resp.status_code),
            }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "reason": "Request timed out after 30 seconds",
            "hint": "Check if Azure App Service can reach external APIs (outbound network)",
        }
    except Exception as exc:
        return {
            "status": "exception",
            "error": str(exc),
            "hint": "Unexpected error — check Azure App Service logs for details",
        }


@router.get("/debug/hf-test")
async def test_huggingface():
    """
    Test HuggingFace API connectivity and authentication directly.
    Visit: /debug/hf-test
    """
    import asyncio
    from huggingface_hub import InferenceClient

    token = settings.HF_API_TOKEN
    model = settings.HF_MODEL

    if not token:
        return {
            "status": "error",
            "reason": "HF_API_TOKEN is empty — check Azure Portal environment variables",
        }

    try:
        client = InferenceClient(api_key=token)

        messages = [
            {
                "role": "user",
                "content": "Say exactly: HuggingFace is working correctly.",
            }
        ]

        def _sync_call():
            return client.chat_completion(
                model=model,
                messages=messages,
                max_tokens=50,
                temperature=0.1,
            )

        loop = asyncio.get_event_loop()
        completion = await loop.run_in_executor(None, _sync_call)

        text_output = ""
        if completion and getattr(completion, "choices", None):
            message = completion.choices[0].message
            text_output = getattr(message, "content", "") or ""

        return {
            "status": "ok",
            "model": model,
            "token_prefix": token[:8] + "...",
            "hf_response": text_output,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "model": model,
            "token_prefix": token[:8] + "..." if token else "empty",
        }


def _error_hint(status_code: int) -> str:
    hints = {
        400: "Bad request — model name may be invalid. Try 'gemini-2.0-flash' or 'gemini-1.5-flash'",
        401: "Unauthorized — API key is invalid or malformed",
        403: "Forbidden — API key does not have access to this model or project",
        404: "Model not found — the model name in GEMINI_MODEL does not exist",
        429: "Rate limit exceeded — too many requests or quota exhausted",
        500: "Gemini internal server error — retry later",
    }
    return hints.get(
        status_code, f"Unexpected status {status_code} — check Gemini API docs"
    )
