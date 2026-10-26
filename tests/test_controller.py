"""Прикладной контроллер публикации без зависимости от графического интерфейса."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .profiles import ChannelProfile
from .publishing import PartialPublicationError, publish_sync


@dataclass(frozen=True)
class PublicationRequest:
    """Неизменяемые параметры одной операции публикации."""

    profile: ChannelProfile
    content: str
    image_path: str | None
    mode: str
    series: bool
    parts: list[str] | None = None
    initial_delay: float = 0


class PublicationController:
    """Выполнить публикацию и передать результат вызывающему интерфейсу."""

    def __init__(
        self,
        publisher: Callable[..., int] = publish_sync,
    ) -> None:
        self._publisher = publisher

    def publish(self, request: PublicationRequest) -> int:
        """Опубликовать подготовленный запрос; исключения передаются вызывающему коду."""
        try:
            return self._publisher(
                request.profile.token,
                request.profile.chat_id,
                request.content,
                request.image_path,
                request.mode,
                request.series,
                parts=request.parts,
                initial_delay=request.initial_delay,
            )
        except PartialPublicationError:
            raise
