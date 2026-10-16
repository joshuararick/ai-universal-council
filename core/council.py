import os
import requests
from typing import Dict

class UniversalCouncil:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        
        # Define our model roster for the Universal Council
        self.models = {
            "Chief of Staff (Gemini)": "google/gemini-2.5-pro",
            "Lead Engineer (Claude)": "anthropic/claude-3.7-sonnet",
            "Architect (GPT)": "openai/gpt-4o",
            "Tactician (Grok)": "x-ai/grok-2"
        }

    def query_model(self, model_name: str, model_id: str, prompt: str) -> str:
        if not self.api_key:
            return f"⚠️ [SIMULATION] API Key not set. Prompt received for {model_name}: {prompt}"
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost:3080",
            "X-Title": "Joshs Command Center"
        }
        
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        try:
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=30)
            res_data = response.json()
            return res_data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"❌ Error querying {model_name}: {str(e)}"

    def convene(self, prompt: str) -> Dict[str, str]:
        print(f"🏛️ Convening AI Universal Council for directive: '{prompt}'\n" + "-"*50)
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