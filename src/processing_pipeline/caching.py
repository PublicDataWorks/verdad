def create_generative_model_from_cache():
    pass
    # Find the "System Instruction" cache
    # for cache in caching.CachedContent.list():
    #     print(cache)

    # If found, update the cache's TTL (or expire_time)
    # Only update the cache content when user_comments_and_upvotes changed

    # Otherwise, create a new cache
    # cache = caching.CachedContent.create(
    #     model=MODEL,
    #     display_name="System Instruction",
    #     system_instruction=SYSTEM_INSTRUCTION,
    #     contents=[user_comments_and_upvotes, examples],
    #     ttl=datetime.timedelta(minutes=60),
    # )

    # Construct a GenerativeModel from the cache.
    # model = genai.GenerativeModel.from_cached_content(
    #     cached_content=cache,
    #     generation_config=genai.GenerationConfig(response_mime_type="application/json", response_schema=OutputSchema, max_output_tokens=8192),
    # )
    # return model
