"""Прикладная логика публикации без зависимости от графического интерфейса."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class PublicationSession:
    """Состояние отправки и очереди, не связанное с конкретным интерфейсом."""

    editor_parts: list[str] | None = None
    publishing_from_editor: bool = False
    send_in_progress: bool = False
    finalized_plain_parts: list[str] | None = None
    pending_messages: list[str] = field(default_factory=list)
    pending_sent_count: int = 0
    pending_retry_after: float = 0.0
    resuming_pending: bool = False

    def record_partial(self, error: PartialPublicationError) -> int:
        """Сохранить подтверждённый результат и остаток после частичной отправки."""
        total_sent = (
            self.pending_sent_count + error.sent_count
            if self.resuming_pending
            else error.sent_count
        )
        self.pending_messages = list(error.pending_messages)
        self.pending_sent_count = total_sent
        self.pending_retry_after = error.retry_after + 1.0
        self.resuming_pending = False
        self.send_in_progress = False
        return total_sent

    def prepare_retry(self, messages: list[str]) -> None:
        """Подготовить очередь к повторной отправке после ручной проверки."""
        self.pending_messages = []
        self.resuming_pending = True
        self.finalized_plain_parts = list(messages)
        self.publishing_from_editor = True

    def complete(self, sent_count: int) -> int:
        """Очистить очередь после успешной отправки и вернуть общий счётчик."""
        total_sent = (
            sent_count + self.pending_sent_count
            if self.resuming_pending
            else sent_count
        )
        self.send_in_progress = False
        self.resuming_pending = False
        self.pending_messages = []
        self.pending_sent_count = 0
        self.pending_retry_after = 0.0
        return total_sent

    def mark_failed(self) -> None:
        """Снять блокировку отправки после ошибки, не теряя очередь на досылку."""
        self.send_in_progress = False


class PublicationController:
    """Выполнить публикацию и передать результат вызывающему коду."""

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
