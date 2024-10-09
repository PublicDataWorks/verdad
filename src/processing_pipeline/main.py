import os
from dotenv import load_dotenv
from prefect import serve
import sentry_sdk
from stage_1 import initial_disinformation_detection

load_dotenv()

# Setup Sentry
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

if __name__ == "__main__":
    process_group = os.environ.get("FLY_PROCESS_GROUP")
    match process_group:
        case "initial_disinformation_detection":
            deployment = initial_disinformation_detection.to_deployment(
                name="Stage 1",
                concurrency_limit=5,
                parameters=dict(repeat=True),
            )
            serve(deployment)
        case "audio_clipping":
            pass
        case "in_depth_analysis":
            pass
        case _:
            raise ValueError(f"Invalid process group: {process_group}")
