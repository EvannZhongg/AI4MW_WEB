from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from ..models import Conversation, Message

_PENDING_RESPONSE_STALE_AFTER = timedelta(minutes=10)


def prune_transient_messages(
    conversation: Conversation,
    *,
    delete_empty_conversation: bool = False,
) -> int:
    deleted_ids = _find_redundant_message_ids(conversation)
    if not deleted_ids:
        return 0

    deleted_count, _ = Message.objects.filter(id__in=deleted_ids).delete()
    _refresh_conversation_state(conversation, delete_empty_conversation=delete_empty_conversation)
    return deleted_count


def prune_unanswered_user_tail(
    conversation: Conversation,
    *,
    delete_empty_conversation: bool = False,
) -> int:
    trailing_user_ids: list[int] = []
    for message in conversation.message_set.order_by("-created_at", "-id").only("id", "role"):
        if message.role == "assistant":
            break
        if message.role == "user":
            trailing_user_ids.append(message.id)
            continue
        break

    if not trailing_user_ids:
        return 0

    deleted_count, _ = Message.objects.filter(id__in=trailing_user_ids).delete()
    _refresh_conversation_state(conversation, delete_empty_conversation=delete_empty_conversation)
    return deleted_count


def discard_user_message(
    conversation: Conversation,
    message: Message | None,
    *,
    delete_empty_conversation: bool = False,
) -> None:
    if message is not None:
        Message.objects.filter(id=message.id).delete()
    Conversation.objects.filter(id=conversation.id).update(response_pending_since=None)
    _refresh_conversation_state(conversation, delete_empty_conversation=delete_empty_conversation)


def _refresh_conversation_state(
    conversation: Conversation,
    *,
    delete_empty_conversation: bool,
) -> None:
    has_messages = Message.objects.filter(conversation_id=conversation.id).exists()
    if not has_messages:
        if delete_empty_conversation:
            Conversation.objects.filter(id=conversation.id).delete()
        return
    Conversation.objects.filter(id=conversation.id).update(updated_at=timezone.now())


def _find_redundant_message_ids(conversation: Conversation) -> list[int]:
    messages = list(conversation.message_set.order_by("created_at", "id").only("id", "role"))
    if not messages:
        return []

    deleted_ids: list[int] = []
    previous_message: Message | None = None
    for message in messages:
        if previous_message is not None and message.role == previous_message.role:
            deleted_ids.append(previous_message.id)
        previous_message = message

    deleted_id_set = set(deleted_ids)
    kept_messages = [message for message in messages if message.id not in deleted_id_set]
    keep_latest_trailing_user = _has_live_pending_response(conversation)
    kept_pending_user = False
    for message in reversed(kept_messages):
        if message.role == "assistant":
            break
        if message.role == "user":
            if keep_latest_trailing_user and not kept_pending_user:
                kept_pending_user = True
                continue
            deleted_ids.append(message.id)
            continue
        break
    return deleted_ids


def _has_live_pending_response(conversation: Conversation) -> bool:
    pending_since = conversation.response_pending_since
    if pending_since is None:
        return False
    return pending_since >= timezone.now() - _PENDING_RESPONSE_STALE_AFTER
