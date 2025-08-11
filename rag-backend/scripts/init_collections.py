import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

url = os.getenv("QDRANT_URL", "http://qdrant:6333")
col = os.getenv("QDRANT_COLLECTION", "pmx_docs")
store = QdrantDocumentStore(url=url, collection_name=col, recreate_index=False)
print("Collection ready:", col)
