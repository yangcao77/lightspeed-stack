"""Unit tests for NoopCache class."""

import pytest

from models.cache_entry import CacheEntry
from cache.noop_cache import NoopCache
from utils import suid

USER_ID = suid.get_suid()
CONVERSATION_ID = suid.get_suid()
USER_PROVIDED_USER_ID = "test-user1"
cache_entry_1 = CacheEntry(
    query="user message1", response="AI message1", provider="foo", model="bar"
)
cache_entry_2 = CacheEntry(
    query="user message2", response="AI message2", provider="foo", model="bar"
)


@pytest.fixture(name="cache_fixture")
def cache():
    """Fixture with constucted and initialized in memory cache object."""
    c = NoopCache()
    c.initialize_cache()
    return c


def test_connect(cache_fixture):
    """Test the behavior of connect method."""
    cache_fixture.connect()


def test_insert_or_append(cache_fixture):
    """Test the behavior of insert_or_append method."""
    cache_fixture.insert_or_append(
        USER_ID,
        CONVERSATION_ID,
        cache_entry_1,
    )


def test_insert_or_append_skip_user_id_check(cache_fixture):
    """Test the behavior of insert_or_append method."""
    skip_user_id_check = True
    cache_fixture.insert_or_append(
        USER_PROVIDED_USER_ID, CONVERSATION_ID, cache_entry_1, skip_user_id_check
    )


def test_insert_or_append_existing_key(cache_fixture):
    """Test the behavior of insert_or_append method for existing item."""
    cache_fixture.insert_or_append(
        USER_ID,
        CONVERSATION_ID,
        cache_entry_1,
    )
    cache_fixture.insert_or_append(
        USER_ID,
        CONVERSATION_ID,
        cache_entry_2,
    )


def test_get_nonexistent_user(cache_fixture):
    """Test how non-existent items are handled by the cache."""
    # this UUID is different from DEFAULT_USER_UID
    assert (
        cache_fixture.get("ffffffff-ffff-ffff-ffff-ffffffffffff", CONVERSATION_ID) == []
    )


def test_delete_existing_conversation(cache_fixture):
    """Test deleting an existing conversation."""
    cache_fixture.insert_or_append(USER_ID, CONVERSATION_ID, cache_entry_1)

    result = cache_fixture.delete(USER_ID, CONVERSATION_ID)

    assert result is True


def test_delete_nonexistent_conversation(cache_fixture):
    """Test deleting a conversation that doesn't exist."""
    result = cache_fixture.delete(USER_ID, CONVERSATION_ID)
    assert result is True


def test_delete_improper_conversation_id(cache_fixture):
    """Test delete with invalid conversation ID."""
    with pytest.raises(ValueError, match="Invalid conversation ID"):
        cache_fixture.delete(USER_ID, "invalid-id")


def test_delete_skip_user_id_check(cache_fixture):
    """Test deleting an existing conversation."""
    skip_user_id_check = True
    cache_fixture.insert_or_append(
        USER_PROVIDED_USER_ID, CONVERSATION_ID, cache_entry_1, skip_user_id_check
    )

    result = cache_fixture.delete(
        USER_PROVIDED_USER_ID, CONVERSATION_ID, skip_user_id_check
    )

    assert result is True


def test_list_conversations(cache_fixture):
    """Test listing conversations for a user."""
    # Create multiple conversations
    conversation_id_1 = suid.get_suid()
    conversation_id_2 = suid.get_suid()

    cache_fixture.insert_or_append(USER_ID, conversation_id_1, cache_entry_1)
    cache_fixture.insert_or_append(USER_ID, conversation_id_2, cache_entry_2)

    conversations = cache_fixture.list(USER_ID)

    assert len(conversations) == 0


def test_list_conversations_skip_user_id_check(cache_fixture):
    """Test listing conversations for a user."""
    # Create multiple conversations
    conversation_id_1 = suid.get_suid()
    conversation_id_2 = suid.get_suid()
    skip_user_id_check = True

    cache_fixture.insert_or_append(
        USER_PROVIDED_USER_ID, conversation_id_1, cache_entry_1, skip_user_id_check
    )
    cache_fixture.insert_or_append(
        USER_PROVIDED_USER_ID, conversation_id_2, cache_entry_2, skip_user_id_check
    )

    conversations = cache_fixture.list(USER_PROVIDED_USER_ID, skip_user_id_check)

    assert len(conversations) == 0


def test_list_no_conversations(cache_fixture):
    """Test listing conversations for a user with no conversations."""
    conversations = cache_fixture.list(USER_ID)
    assert len(conversations) == 0


def test_ready(cache_fixture):
    """Test if in memory cache always report ready."""
    assert cache_fixture.ready()


improper_user_uuids = [
    None,
    "",
    " ",
    "\t",
    ":",
    "foo:bar",
    "ffffffff-ffff-ffff-ffff-fffffffffff",  # UUID-like string with missing chararacter
    "ffffffff-ffff-ffff-ffff-fffffffffffZ",  # UUID-like string, but with wrong character
    "ffffffff:ffff:ffff:ffff:ffffffffffff",
]


@pytest.mark.parametrize("uuid", improper_user_uuids)
def test_list_improper_user_id(cache_fixture, uuid):
    """Test list with invalid user ID."""
    with pytest.raises(ValueError, match=f"Invalid user ID {uuid}"):
        cache_fixture.list(uuid)


@pytest.mark.parametrize("uuid", improper_user_uuids)
def test_delete_improper_user_id(cache_fixture, uuid):
    """Test delete with invalid user ID."""
    with pytest.raises(ValueError, match=f"Invalid user ID {uuid}"):
        cache_fixture.delete(uuid, CONVERSATION_ID)


@pytest.mark.parametrize("uuid", improper_user_uuids)
def test_get_improper_user_id(cache_fixture, uuid):
    """Test how improper user ID is handled."""
    with pytest.raises(ValueError, match=f"Invalid user ID {uuid}"):
        cache_fixture.get(uuid, CONVERSATION_ID)


def test_get_improper_conversation_id(cache_fixture):
    """Test how improper conversation ID is handled."""
    with pytest.raises(ValueError, match="Invalid conversation ID"):
        cache_fixture.get(USER_ID, "this-is-not-valid-uuid")
