import pytest
import asyncio

from onionstream.backend.lib.connector import TaskAsyncIterator, IdentifiableSingleton


####################
# TaskAsyncIterator
####################

@pytest.mark.asyncio
async def test_async_iterator_initialization():
    t = TaskAsyncIterator()
    assert isinstance(t.futures, list)
    assert t.futures == []
    assert t.wait_for_futures is False

    t_with_wait = TaskAsyncIterator(wait_for_futures=True)
    assert t_with_wait.wait_for_futures is True

@pytest.mark.asyncio
async def test_async_iterator_is_empty():
    t = TaskAsyncIterator()

    # Initially it should be empty
    assert t.is_empty() is True

    # Add a dummy task
    async def dummy_coroutine():
        return

    task = asyncio.create_task(dummy_coroutine())
    t.append(task)
    
    #Wait for the task to finish
    await task

    # It shouldn't be empty now
    assert t.is_empty() is False

    await t.__anext__()

    assert t.is_empty() is True


########################
# IdentifiableSingleton
########################

def test_identifiable_singleton_initialization():
    identifier = {"IdentifiableSingleton":"test_initialization"}
    identifiable_singleton = IdentifiableSingleton(identifier = identifier)
    
    assert isinstance(identifiable_singleton, IdentifiableSingleton)
    assert identifiable_singleton._mutable_identifier == identifier
    assert identifiable_singleton._imutable_identifier in IdentifiableSingleton._instances

def test_identifiable_singleton_imutable_identifier():
    identifier = {"IdentifiableSingleton":"test_imutable_identifier"}
    identifiable_singleton = IdentifiableSingleton(identifier = identifier)

    assert identifiable_singleton._imutable_identifier == IdentifiableSingleton.get_imutable_identifier(identifier)
    assert IdentifiableSingleton.__name__ in identifiable_singleton._imutable_identifier

def test_identifiable_singleton_hash():
    identifier = {"IdentifiableSingleton":"test_hash"}
    identifiable_singleton = IdentifiableSingleton(identifier = identifier)

    assert hash(identifiable_singleton) == hash(identifiable_singleton._imutable_identifier)

def test_identifiable_singleton_eq():
    identifier1 = {"IdentifiableSingleton":"test_eq1"}
    identifiable_singleton1a = IdentifiableSingleton(identifier = identifier1)
    identifiable_singleton1b = IdentifiableSingleton(identifier = identifier1)
    identifier2 = {"IdentifiableSingleton":"test_eq2"}
    identifiable_singleton2a = IdentifiableSingleton(identifier = identifier2)

    assert identifiable_singleton1a == identifier1
    assert identifiable_singleton1a == identifiable_singleton1a
    assert identifiable_singleton1a == identifiable_singleton1b
    assert identifiable_singleton1a != identifier2
    assert identifiable_singleton1a != identifiable_singleton2a

def test_identifiable_singleton_singularity():
    identifier1 = {"IdentifiableSingleton":"test_singularity1"}
    identifiable_singleton1a = IdentifiableSingleton(identifier = identifier1)
    identifiable_singleton1b = IdentifiableSingleton(identifier = identifier1)
    identifier2 = {"IdentifiableSingleton":"test_singularity2"}
    identifiable_singleton2a = IdentifiableSingleton(identifier = identifier2)

    assert identifiable_singleton1a is identifiable_singleton1b
    assert identifiable_singleton1a is not identifiable_singleton2a
    

if __name__ == "__main__":
    pytest.main()