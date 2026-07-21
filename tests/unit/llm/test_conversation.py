from ceremyn.llm.conversation import ConversationMessage, InMemoryConversationStore


def make_store(**kwargs: int) -> InMemoryConversationStore:
    return InMemoryConversationStore(**kwargs)


def test_empty_session_has_no_history() -> None:
    store = make_store()
    assert store.history("unknown") == ()


def test_append_and_history_preserve_order() -> None:
    store = make_store()
    store.append("s1", ConversationMessage(role="user", content="hi"))
    store.append("s1", ConversationMessage(role="assistant", content="hello"))
    history = store.history("s1")
    assert [m.role for m in history] == ["user", "assistant"]
    assert [m.content for m in history] == ["hi", "hello"]


def test_history_is_bounded_per_session() -> None:
    store = make_store(max_messages_per_session=3)
    for i in range(5):
        store.append("s1", ConversationMessage(role="user", content=f"msg{i}"))
    history = store.history("s1")
    assert len(history) == 3
    assert [m.content for m in history] == ["msg2", "msg3", "msg4"]


def test_sessions_are_isolated() -> None:
    store = make_store()
    store.append("s1", ConversationMessage(role="user", content="s1 only"))
    assert store.history("s2") == ()


def test_oldest_session_evicted_when_session_cap_reached() -> None:
    store = make_store(max_sessions=2)
    store.append("s1", ConversationMessage(role="user", content="a"))
    store.append("s2", ConversationMessage(role="user", content="b"))
    store.append("s3", ConversationMessage(role="user", content="c"))

    assert store.history("s1") == ()
    assert len(store.history("s2")) == 1
    assert len(store.history("s3")) == 1


def test_touching_a_session_protects_it_from_eviction() -> None:
    store = make_store(max_sessions=2)
    store.append("s1", ConversationMessage(role="user", content="a"))
    store.append("s2", ConversationMessage(role="user", content="b"))
    store.append("s1", ConversationMessage(role="user", content="a again"))  # s1 now newest
    store.append("s3", ConversationMessage(role="user", content="c"))  # should evict s2, not s1

    assert store.history("s2") == ()
    assert len(store.history("s1")) == 2
    assert len(store.history("s3")) == 1


def test_clear_removes_a_session() -> None:
    store = make_store()
    store.append("s1", ConversationMessage(role="user", content="a"))
    store.clear("s1")
    assert store.history("s1") == ()


def test_clear_unknown_session_is_a_no_op() -> None:
    store = make_store()
    store.clear("unknown")  # must not raise
    assert store.history("unknown") == ()


def test_message_timestamp_defaults_to_now_and_is_aware() -> None:
    message = ConversationMessage(role="user", content="hi")
    assert message.at.tzinfo is not None
