import requests, json
r=requests.get("https://openrouter.ai/api/v1/models", timeout=30)
print("status", r.status_code)
data=r.json()
print("total models", len(data.get("data",[])))
free=[m for m in data["data"] if m["id"].endswith(":free")]
print("free count", len(free))
for m in sorted(free, key=lambda x: x["id"]):
    arch = m.get("architecture", {})
    modality = arch.get("modality")
    # only text->text
    if modality != "text->text":
        continue
    # check if supports json
    params = m.get("supported_parameters", [])
    print(f"{m['id']:55} ctx={m.get('context_length')} params={params[:4]} pricing={m.get('pricing')} name={m.get('name')}")
