import os
import sys
import requests
from typing import Dict

# Force UTF-8 output encoding in Windows terminal
sys.stdout.reconfigure(encoding='utf-8')

class UniversalCouncil:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        
        # Updated with stable OpenRouter model IDs and explicit max_tokens limits (< 4000)
        self.models = {
            "Chief of Staff (Gemini)": "google/gemini-2.0-flash-001",
            "Lead Engineer (Claude)": "anthropic/claude-3.5-sonnet",
            "Architect (GPT)": "openai/gpt-4o-mini",
            "Tactician (Grok)": "x-ai/grok-2-1212"
        }

    def query_model(self, model_name: str, model_id: str, prompt: str) -> str:
        if not self.api_key:
            return "[SIMULATION] API Key not set."
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost:3080",
            "X-Title": "Joshs Command Center"
        }
        
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500
        }
        
        try:
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=30)
            res_data = response.json()
            
            if "error" in res_data:
                return f"OpenRouter Error: {res_data['error']}"
            if "choices" not in res_data:
                return f"Unexpected API Response: {res_data}"
                
            return res_data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error querying {model_name}: {str(e)}"

    def convene(self, prompt: str) -> Dict[str, str]:
        print(f"[Council] Convening AI Universal Council for directive: '{prompt}'\n" + "-"*50)
        results = {}
        for name, mid in self.models.items():
            print(f"-> Consulting {name} ({mid})...")
            results[name] = self.query_model(name, mid, prompt)
        return results

if __name__ == "__main__":
    council = UniversalCouncil()
    directive = "Assess system baseline and provide operational readiness report."
    responses = council.convene(directive)
    print("\n=== COUNCIL RESPONSES ===")
    for model, ans in responses.items():
        print(f"\n[{model}]:\n{ans}")
