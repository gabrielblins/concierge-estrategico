class KnowledgeBase:
    def __init__(self, client):
        self.client = client

    def _collection_name(self, project_id):
        return f"project_{project_id}"

    def _chunks(self, text, chunk_size):
        words = text.split()
        out, cur, length = [], [], 0
        for w in words:
            cur.append(w)
            length += len(w) + 1
            if length >= chunk_size:
                out.append(" ".join(cur))
                cur, length = [], 0
        if cur:
            out.append(" ".join(cur))
        return out

    def ingest(self, project_id, filename, text, chunk_size=800):
        coll = self.client.get_or_create_collection(self._collection_name(project_id))
        chunks = self._chunks(text, chunk_size)
        existing = coll.count()
        ids = [f"{filename}-{existing + i}" for i in range(len(chunks))]
        coll.add(documents=chunks, ids=ids)
        return len(chunks)

    def query(self, project_id, question, k=3):
        try:
            coll = self.client.get_collection(self._collection_name(project_id))
        except Exception:
            return ""
        if coll.count() == 0:
            return ""
        res = coll.query(query_texts=[question], n_results=min(k, coll.count()))
        docs = res.get("documents", [[]])[0]
        return "\n\n".join(docs)
