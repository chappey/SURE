import requests, json
r=requests.get("https://openrouter.ai/api/v1/models", timeout=30)
data=r.json()
free=sorted([m for m in data["data"] if m["id"].endswith(":free")], key=lambda x: x["id"])
for m in free:
    arch = m.get("architecture", {})
    print(f"{m['id']:55} modality={arch.get('modality'):15} params={m.get('supported_parameters',[])[:3]} ctx={m.get('context_length')}")
