CREATE INDEX snippet_embeddings_sub_vector_idx ON snippet_embeddings
USING hnsw ((sub_vector(embedding, 512)::vector(512)) vector_ip_ops)
WITH (m = 32, ef_construction = 400);
