"""Kald til AI-modeller via OpenRouter (https://openrouter.ai/docs)."""

import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    pass


class OpenRouter:
    def __init__(self, models, api_key=None):
        self.models = models
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise LLMError("Mangler OPENROUTER_API_KEY. Læg den i filen .env (se .env.example).")
        self.total_cost = 0.0
        self.calls = 0

    def json_call(self, system, user, schema_name, schema, retries=3):
        """Sender en prompt og returnerer et JSON-objekt, der følger `schema`."""
        body = {
            # OpenRouter prøver næste model i listen, hvis den første fejler.
            "models": self.models,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            "temperature": 0,
            "usage": {"include": True},
        }
        last_err = None
        for attempt in range(retries):
            try:
                data = self._post(body)
                self.calls += 1
                self.total_cost += float((data.get("usage") or {}).get("cost") or 0)
                content = data["choices"][0]["message"]["content"]
                return parse_json(content)
            except (LLMError, KeyError, IndexError, ValueError) as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"AI-kaldet fejlede efter {retries} forsøg: {last_err}")

    def _post(self, body):
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "Tender Radar",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"OpenRouter svarede {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Kunne ikke forbinde til OpenRouter ({e.reason})") from e
        if "error" in data:
            raise LLMError(f"OpenRouter-fejl: {data['error']}")
        return data


def parse_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Intet JSON i svaret: {text[:200]}")
    return json.loads(text[start:end + 1])
