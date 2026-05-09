"""`python -m diary_rag` — local smoke entrypoint.

Boots the FastAPI app under uvicorn on 127.0.0.1:8000. Used by `make run`.
"""

from __future__ import annotations

import uvicorn

from diary_rag.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "diary_rag.app:app",
        host="127.0.0.1",
        port=8000,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
