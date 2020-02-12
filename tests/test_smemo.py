import typing

import pytest

import smemo


@smemo.cached
def func1(session: smemo.BaseSession, n: int) -> int:
    if n <= 1:
        return 1
    return func1(session, n - 1) + func1(session, n - 2)


def test_basic():
    assert smemo.BaseSession().pre_call(func1, (), {}) is None
    session = smemo.Session()
    assert func1(session, 5) == 8
    session.invalidate_all()
    assert func1(session, 5) == 8


@smemo.cached
def func2(session: smemo.BaseSession, n: int) -> int:
    counter = session.getval('counter')
    if n <= 1:
        return 1
    counter[0] += 1
    return func2(session, n - 1) + func2(session, n - 2)


def test_get_put():
    session = smemo.Session()
    counter = [0]
    with pytest.raises(KeyError):
        session.getval('counter')
    session.putval(counter, 'counter')
    assert func2(session, 5) == 8
    assert counter[0] == 4
    assert func2(session, 5) == 8
    assert counter[0] == 4
    assert func2(session.callonly, 5) == 8
    assert counter[0] == 5
    session.invalidate(func2, 5)
    assert func2(session, 5) == 8
    assert counter[0] == 6
    session.invalidate(func1, 5)
    assert func2(session, 5) == 8
    assert counter[0] == 6
    session.invalidate_all(func2)
    assert func2(session, 5) == 8
    assert counter[0] == 10
    session.invalidate_all()
    assert func2(session, 5) == 8
    assert counter[0] == 14


@smemo.gcached(ref=True, persistent=True)
def do_count(session: smemo.BaseSession) -> typing.List[int]:
    return smemo.getter(session, do_count)


@smemo.cached
def func2b(session: smemo.BaseSession, n: int) -> int:
    if n <= 1:
        return 1
    do_count(session)[0] += 1
    return func2b(session, n - 1) + func2b(session, n - 2)


def test_get_put2():
    session = smemo.Session()
    count = [0]
    do_count(session.setcache(count))
    assert func2b(session, 5) == 8
    assert count[0] == 4
    assert func2b(session, 5) == 8
    assert count[0] == 4
    func2b(session.inv, 5)
    assert func2b(session, 5) == 8
    assert count[0] == 5
    assert func2b(session.callonly, 5) == 8
    assert count[0] == 6
    do_count(session.setcache(exc=RuntimeError('error')))


def test_disabled():
    session = smemo.Session()
    counter = [0]
    session.putval(counter, 'counter')
    with session.nocache():
        assert func2(session, 5) == 8
    assert counter[0] == 7


@smemo.cached
def func3(session: smemo.BaseSession) -> None:
    counter = session.getval('counter')
    counter[0] += 1
    raise RuntimeError('hello')


@smemo.rcached
def func3a(session: smemo.BaseSession) -> None:
    counter = session.getval('counter')
    counter[0] += 1
    raise RuntimeError('hello')


def test_exc():
    session = smemo.Session()
    counter = [0]
    session.putval(counter, 'counter')
    with pytest.raises(RuntimeError):
        func3(session)
    assert counter[0] == 1
    with pytest.raises(RuntimeError):
        func3(session)
    assert counter[0] == 1
    with pytest.raises(RuntimeError):
        func3a(session)
    assert counter[0] == 2


@smemo.rcached
def func4(session: smemo.BaseSession, val: typing.List[int]) -> int:
    counter = session.getval('counter')
    counter[0] += 1
    return sum(val)


def test_ref():
    session = smemo.Session()
    counter = [0]
    session.putval(counter, 'counter')
    assert func4(session, [1, 3]) == 4
    assert counter[0] == 1
    assert func4(session, [1, 3]) == 4
    assert counter[0] == 1
    assert func4(session, [1,  2]) == 3
    assert counter[0] == 2
    assert func4(session, val=[1, 2]) == 3
    assert counter[0] == 3
    assert func4(session, val=[1, 2]) == 3
    assert counter[0] == 3


def test_nested():
    parent = smemo.Session()
    child = smemo.Session(parent)
    parent.putval(10, 'val')
    assert child.getval('val') == 10
    child.putval(11, 'val')
    assert parent.getval('val') == 10
    assert child.getval('val') == 11
