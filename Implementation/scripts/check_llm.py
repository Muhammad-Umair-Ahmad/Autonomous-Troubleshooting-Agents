import json
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text())
    payload = {
        "model": config["model"],
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a network troubleshooting assistant. "
                    "Return only a JSON object containing "
                    "'possible_cause' and 'next_check'. "
                    "Do not claim you inspected a network."
                ),
            },
            {
                "role": "user",
                "content": (
                    "A host can ping its gateway but cannot reach "
                    "a remote subnet. Give one possible cause and "
                    "one useful diagnostic check."
                ),
            },
        ],
        "options": {
            "temperature": config["temperature"],
            "num_ctx": config["context_length"],
            "num_predict": config["max_output_tokens"],
        },
    }
    response = requests.post(
        config["base_url"].rstrip("/") + "/api/chat",
        json=payload,
        timeout=300,
    )
    response.raise_for_status()
    body = response.json()
    answer = json.loads(body["message"]["content"])
    if not isinstance(answer, dict):
        raise ValueError("Expected a JSON object")
    for field in ("possible_cause", "next_check"):
        if not isinstance(answer.get(field), str) or not answer[field].strip():
            raise ValueError(f"Missing or invalid field: {field}")
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": config["model"],
        "answer": answer,
        "input_tokens": body.get("prompt_eval_count"),
        "output_tokens": body.get("eval_count"),
        "total_duration_ns": body.get("total_duration"),
    }
    output = ROOT / "results" / "part1" / "llm_check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(answer, indent=2))
    print("PASS: Python received and validated local-model JSON")


if __name__ == "__main__":
    main()
