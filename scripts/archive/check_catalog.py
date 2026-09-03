import sys
sys.path.insert(0, '/app')
from app.llm.catalog import load_catalog, list_available_models
load_catalog.cache_clear()
print([m.model_dump() for m in load_catalog()])
print("available", [m.id for m in list_available_models()])
print("API payload", __import__('app.llm.catalog', fromlist=['list_models_for_api']).list_models_for_api())
