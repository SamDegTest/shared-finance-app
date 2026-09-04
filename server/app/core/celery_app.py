from collections.abc import Callable
from typing import Any, TypeVar

from app.core.config import settings

F = TypeVar("F", bound=Callable[..., Any])

try:
    from celery import Celery  # type: ignore

    celery_app: Any = Celery(
        "shared_finance_worker",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["app.tasks.receipt_tasks"],
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=180,  # 3 minuti max
    )
except Exception:

    class _DummyTask:
        name = "dummy_task"
        request = type("DummyRequest", (), {"retries": 0, "id": "dummy-task-id"})()

        def retry(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _DummyCelery:
        def task(self, *_args: Any, **kwargs: Any) -> Callable[[F], F]:
            bind = kwargs.get("bind", False)

            def decorator(fn: F) -> F:
                if bind:

                    def wrapper(*f_args: Any, **f_kwargs: Any) -> Any:
                        return fn(_DummyTask(), *f_args, **f_kwargs)

                    wrapper.__name__ = getattr(fn, "__name__", "wrapper")
                    return wrapper  # type: ignore[return-value]
                return fn

            return decorator

    celery_app = _DummyCelery()
