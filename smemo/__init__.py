"""Smemo: Explicit session memoization

Allow functions to be written naturally with explicit cache control.

"""

import contextlib
import copy
import functools
import pickle
import typing


FuncType = typing.Callable[..., typing.Any]
PosType = typing.Tuple[typing.Any, ...]
KwdType = typing.Dict[str, typing.Any]
KeyType = typing.Tuple[PosType, typing.Any]
ResType = typing.Tuple[typing.Any, typing.Optional[Exception]]


PICKLED = object()
"Marker object to identify pickled keys"


PERSISTENT_FUNCS = set()  # type: typing.Set[FuncType]


class BaseSession:
    "Session management interface"
    def get_cache(self, func: FuncType, *args: typing.Any,
                  **kwargs: typing.Any) -> typing.Any:
        "Get the cached result for a function"
        return None

    def do_call(self, func: FuncType, actual: FuncType,
                args: PosType, kwargs: KwdType) -> typing.Any:
        """Call a function without caching

        This normally calls a function directly, but may be overridden
        for other behavior.

        Args:
            func: The decorated function
            actual: The corresponding undecorated function
            args: The positional arguments for the call
            kwargs: The keyword arguments for the call

        """
        return None

    def cache_exc(self, func: FuncType, _exc: Exception,
                  *args: typing.Any, **kwargs: typing.Any) -> None:
        """Insert an exception return as the cached value for a function call

        Args:
            func: The decorated function
            _exc: The exception to cache
            args: The positional arguments
            kwargs: The keyword arguments

        """

    def cache(self, func: FuncType, _val: typing.Any,
              *args: typing.Any, **kwargs: typing.Any) -> None:
        """Insert a value as the cached value for a function call

        Args:
            func: The decorated function
            _val: The value to cache
            args: The positional arguments
            kwargs: The keyword arguments

        """


class Session(BaseSession):
    "Session object to hold cached results"
    def __init__(self, parent: BaseSession = None) -> None:
        self._disabled = False
        self._cache \
            = {}  # type: typing.Dict[FuncType, typing.Dict[KeyType, ResType]]
        self._parent = parent
        self.inv = InvalidatorSession(self)
        self.callonly = CallOnlySession(self)

    def setcache(self, ret: typing.Any = None,
                 exc: typing.Optional[Exception] = None) -> 'SetCacheSession':
        """Get a SetCacheSession using the specified return value

        Args:
            ret: The return value if exc is None
            exc: The exception to raise

        """
        return SetCacheSession(self, ret, exc)

    def getval(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        """Get values set by put()

        The other arguments should match those of put() exactly.

        """
        return getter(self, *args, **kwargs)

    def putval(self, val: typing.Any, *args: typing.Any,
               **kwargs: typing.Any) -> typing.Any:
        """Put values to be used by get()

        Use the session as a key-value store.  It actually uses the
        same caching mechanism to hold the data, so you can use any
        number of positional and keyword parameters to identify the
        value.

        """
        self.cache(getter, val, *args, **kwargs)

    def cache(self, func: FuncType, _val: typing.Any,
              *args: typing.Any, **kwargs: typing.Any) -> None:
        self._cache_store(func, args, kwargs, (_val, None))

    def cache_exc(self, func: FuncType, _exc: Exception,
                  *args: typing.Any, **kwargs: typing.Any) -> None:
        self._cache_store(func, args, kwargs, (None, _exc))

    def _cache_store(self, func: FuncType, args: PosType,
                     kwargs: KwdType, entry: ResType) -> None:
        if self._disabled:
            return
        if func not in self._cache:
            self._cache[func] = {}
        self._cache[func][self._key(args, kwargs)] = entry

    def get_cache(self, func: FuncType,
                  *args: typing.Any, **kwargs: typing.Any) \
            -> typing.Optional[ResType]:
        if func not in self._cache:
            ret = None
        else:
            ret = self._cache[func].get(self._key(args, kwargs))
        return ret if (ret is not None or self._parent is None) \
            else self._parent.get_cache(func, *args, **kwargs)

    def invalidate(self, func: FuncType,
                   *args: typing.Any, **kwargs: typing.Any) -> None:
        "Invalidate the result of a single function call"
        if func in self._cache:
            self._cache[func].pop(self._key(args, kwargs), None)

    def invalidate_all(self, func: FuncType = None) -> None:
        """Invalidate all results, possibly restricted to a function call

        If func is not specified, it invalidate all functions that are
        not persistent.

        """
        if func:
            self._cache.pop(func, None)
            return
        for func in set(self._cache):
            if func in PERSISTENT_FUNCS:
                continue
            del self._cache[func]

    @contextlib.contextmanager
    def nocache(self) -> typing.Iterator[None]:
        "Establish a context where caching is not performed"
        old_val = self._disabled
        self._disabled = True
        yield
        self._disabled = old_val

    def _key(self, args: PosType, kwargs: KwdType) -> KeyType:
        try:
            hash(args)
        except TypeError:
            args = (PICKLED, pickle.dumps(args))
        kwlist = tuple(
            sorted(kwargs.items()))  # type: typing.Tuple[typing.Any, ...]
        try:
            hash(kwlist)
        except TypeError:
            kwlist = (PICKLED, pickle.dumps(kwlist))
        return (args, kwlist)

    def do_call(self, func: FuncType, actual: FuncType, args: PosType,
                kwargs: KwdType) -> typing.Any:
        return actual(self, *args, **kwargs)


class InvalidatorSession(BaseSession):
    "Session which performs invalidation"
    def __init__(self, session: Session) -> None:
        self._session = session

    def do_call(self, func: FuncType, actual: FuncType,
                args: PosType, kwargs: KwdType) -> typing.Any:
        """Call a function without caching

        This normally calls a function directly, but may be overridden
        for other behavior.

        """
        self._session.invalidate(func, *args, **kwargs)
        return None


class CallOnlySession(BaseSession):
    "Session which performs call only without caching"
    def __init__(self, session: Session) -> None:
        self._session = session

    def do_call(self, func: FuncType, actual: FuncType,
                args: PosType, kwargs: KwdType) -> typing.Any:
        """Call a function without caching

        This normally calls a function directly, but may be overridden
        for other behavior.

        """
        return actual(self._session, *args, **kwargs)


class SetCacheSession(BaseSession):
    "Session which causes a fixed value to be used"
    def __init__(self, session: Session, ret: typing.Any,
                 exc: typing.Optional[Exception]) -> None:
        self._session = session
        self._ret = ret
        self._exc = exc

    def cache(self, func: FuncType, _val: typing.Any,
              *args: typing.Any, **kwargs: typing.Any) -> None:
        if self._exc:
            self._session.cache_exc(func, self._exc, *args, **kwargs)
        else:
            self._session.cache(func, self._ret, *args, **kwargs)

FuncT = typing.TypeVar('FuncT', bound=typing.Callable[..., typing.Any])


def gcached(ref: bool = False, persistent: bool = False) \
        -> typing.Callable[[FuncType], FuncType]:
    """Decorator to cache the return value of a function

    This is the generic decorator, and must be called instead of used
    directly as a decorator.  For such usage, use cached or rcached.

    Args:
        ref: If False, copy.deepcopy is invoked before value is returned
        persistent: If True, don't drop cached value upon invalidation

    """
    def _deco(func: FuncT) -> FuncT:
        @functools.wraps(func)
        def _func(session: BaseSession, *args: typing.Any,
                  **kwargs: typing.Any) -> typing.Any:
            ret = _maybe_call(session, _func, func, args, kwargs)
            exc = ret[1]
            if exc:
                raise exc
            return ret[0] if ref else copy.deepcopy(ret[0])
        if persistent:
            PERSISTENT_FUNCS.add(_func)
        return typing.cast(FuncT, _func)
    return _deco


@gcached(ref=True, persistent=True)
def getter(session: BaseSession, *args: typing.Any, **kwargs: typing.Any) \
        -> typing.Any:
    "The underlying function to get a value from the cache"
    raise KeyError('No value cached for args %s %s' % (args, kwargs))


def _maybe_call(session: BaseSession, func: FuncType, actual: FuncType,
                args: PosType, kwargs: KwdType) -> ResType:
    ret = session.get_cache(func, *args, **kwargs)
    if ret:
        return ret
    try:
        res = session.do_call(func, actual, args, kwargs)
    except Exception as exc:
        session.cache_exc(func, exc, *args, **kwargs)
        return (None, exc)
    session.cache(func, res, *args, **kwargs)
    return (res, None)


def cached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function

    Equivalent to gcached()(func)

    """
    return gcached()(func)  # type: ignore


def rcached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function

    Equivalent to gcached(ref=True)(func)

    """
    return gcached(ref=True)(func)  # type: ignore
