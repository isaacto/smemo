"""Smemo: Explicit session memoization.

Allow functions to be written naturally with explicit cache control.
"""

import collections
import contextlib
import copy
import functools
import inspect
import pickle
import typing


FuncType = typing.Callable[..., typing.Any]
PosType = typing.Tuple[typing.Any, ...]
KwdType = typing.Dict[str, typing.Any]
KeyType = typing.Tuple[PosType, typing.Any]
ResType = typing.Tuple[typing.Any, typing.Optional[Exception]]


PICKLED = object()
"""Marker object to identify pickled keys."""


MISSING = object()
"""Marker object to denote missing value in cache."""


PERSISTENT_FUNCS = set()  # type: typing.Set[FuncType]
PKEY_FUNCS = collections.defaultdict(
    set)  # type: typing.Dict[str, typing.Set[FuncType]]


def _no_arg(func: FuncType) -> bool:
    return len(inspect.signature(func).parameters) <= 1


class BaseSession:
    """Session management interface."""

    def get_cache(self, func: FuncType, *_args: typing.Any,
                  **_kwargs: typing.Any) -> typing.Any:
        """Get the cached result for a function.

        Args:
            func: The decorated function
            args: The arguments used to call the function
            kwargs: The keyword arguments used to call the function
        """
        _ = func

    def simple_get_cache(self, func: FuncType) -> typing.Any:
        """Like get_cache, but for no-arg functions.

        Args:
            func: The decorated function
        """
        _ = func
        return MISSING

    def pre_call(self, _func: FuncType, _args: PosType,
                 _kwargs: KwdType) -> typing.Optional['BaseSession']:
        """Called before actually checking cache.

        This returns the session for making the call.  If it returns
        None, the call is skipped and it is treated as if the function
        returns None.

        Args:
            func: The decorated function.
            args: The positional arguments for the call.
            kwargs: The keyword arguments for the call.
        """
        return None

    def simple_pre_call(
            self, _func: FuncType) -> typing.Optional['BaseSession']:
        """Like pre_call, but for no-arg functions.

        Args:
            func: The decorated function.
        """
        return None

    def cache_exc(self, func: FuncType, _exc: Exception,
                  *args: typing.Any, **kwargs: typing.Any) -> None:
        """Insert an exception return as the cached value for a function call.

        Args:
            func: The decorated function.
            _exc: The exception to cache.
            args: The positional arguments.
            kwargs: The keyword arguments.
        """

    def cache(self, func: FuncType, _val: typing.Any,
              *args: typing.Any, **kwargs: typing.Any) -> None:
        """Insert a value as the cached value for a function call.

        Args:
            func: The decorated function.
            _val: The value to cache.
            args: The positional arguments.
            kwargs: The keyword arguments.
        """
        _ = func


class Session(BaseSession):
    """Session object to hold cached results.

    Args:

        parent: Use a parent in addition to its own cache.  If a value
            is not found in the cache when upon a get_cache operation,
            the parent is consulted.

        restrict: Restrict local cache to these functions.  If not
            None, functions not in restricted will always consult the
            parent, for get_cache, cache and cache_exc operations.
    """
    def __init__(self, parent: typing.Optional[BaseSession] = None,
                 restrict: typing.Optional[typing.Iterable[FuncType]]
                     = None) -> None:
        self._disabled = False
        self._cache \
            = {}  # type: typing.Dict[FuncType, typing.Dict[KeyType, ResType]]
        self._simple_cache = {}  # type: typing.Dict[FuncType, typing.Any]
        self._parent = parent
        self._restrict = None if restrict is None else set(restrict)
        self.inv = InvalidatorSession(self)
        self.callonly = CallOnlySession(self)

    def pre_call(self, _func: FuncType,
                 _args: PosType, _kwargs: KwdType) -> typing.Any:
        return self

    def simple_pre_call(self, _func: FuncType) -> typing.Any:
        return self

    def setcache(self, ret: typing.Any = None,
                 exc: typing.Optional[Exception] = None) -> 'SetCacheSession':
        """Get a SetCacheSession using the specified return value.

        Args:

            ret: The return value if exc is None.

            exc: The exception to raise.  Works only if the function
                takes arguments other than the first session argument.
        """
        return SetCacheSession(self, ret, exc)

    def getval(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        """Get values set by putval().

        The other arguments should match those of putval() exactly.
        """
        return getter(self, *args, **kwargs)

    def putval(self, val: typing.Any, *args: typing.Any,
               **kwargs: typing.Any) -> typing.Any:
        """Put values to be used by getval().

        Use the session as a key-value store.  It actually uses the
        same caching mechanism to hold the data, so you can use any
        number of positional and keyword parameters to identify the
        value.

        Args:
            val: The value to put.
            args: The arguments to identify the value.
            kwargs: The keyword arguments to identify the value.
        """
        self.cache(getter, val, *args, **kwargs)

    def cache(self, func: FuncType, _val: typing.Any,
              *args: typing.Any, **kwargs: typing.Any) -> None:
        if self._parent_only(func):
            assert self._parent
            self._parent.cache(func, _val, *args, **kwargs)
        else:
            self._cache_store(func, args, kwargs, (_val, None))

    def cache_exc(self, func: FuncType, _exc: Exception,
                  *args: typing.Any, **kwargs: typing.Any) -> None:
        if self._parent_only(func):
            assert self._parent
            self._parent.cache_exc(func, _exc, *args, **kwargs)
        else:
            self._cache_store(func, args, kwargs, (None, _exc))

    def _cache_store(self, func: FuncType, args: PosType,
                     kwargs: KwdType, entry: ResType) -> None:
        if self._disabled:
            return
        if _no_arg(func):
            self._simple_cache[func] = entry[0]
            return
        if func not in self._cache:
            self._cache[func] = {}
        self._cache[func][self._key(args, kwargs)] = entry

    def get_cache(self, func: FuncType, *args: typing.Any,
                  **kwargs: typing.Any) -> typing.Optional[ResType]:
        ret = None
        if not self._parent_only(func) and func in self._cache:
            ret = self._cache[func].get(self._key(args, kwargs))
        return ret if (ret is not None or self._parent is None) \
            else self._parent.get_cache(func, *args, **kwargs)

    def simple_get_cache(self, func: FuncType) -> typing.Any:
        if not self._parent:
            return self._simple_cache.get(func, MISSING)
        ret = MISSING
        if not self._parent_only(func) and func in self._simple_cache:
            ret = self._simple_cache[func]
        return ret if (ret is not MISSING or self._parent is None) \
            else self._parent.simple_get_cache(func)

    def _parent_only(self, func: FuncType) -> bool:
        return self._restrict is not None and func not in self._restrict

    def invalidate(self, func: FuncType,
                   *args: typing.Any, **kwargs: typing.Any) -> None:
        """Invalidate the result of a single function call."""
        if _no_arg(func):
            if func in self._simple_cache:
                self._simple_cache.pop(func, None)
        else:
            if func in self._cache:
                self._cache[func].pop(self._key(args, kwargs), None)

    def invalidate_all(self, func: typing.Optional[FuncType] = None) -> None:
        """Invalidate all results, possibly restricted to a function call.

        If func is not specified, it invalidate all functions that are
        not persistent.

        Args:
            func: The function to invalidate all cache.
        """
        if func:
            self._cache.pop(func, None)
            self._simple_cache.pop(func, None)
            return
        for cfunc in set(self._cache):
            if cfunc not in PERSISTENT_FUNCS:
                del self._cache[cfunc]
        for cfunc in set(self._simple_cache):
            if cfunc not in PERSISTENT_FUNCS:
                del self._simple_cache[cfunc]

    def invalidate_by_pkey(self, pkey: str) -> None:
        """Invalidate all results for all function with a persistence key.

        Args:
            pkey: The persistent key.
        """
        for func in set(self._cache):
            if func in PKEY_FUNCS.get(pkey, set()):
                del self._cache[func]
        for func in set(self._simple_cache):
            if func in PKEY_FUNCS.get(pkey, set()):
                del self._simple_cache[func]

    @contextlib.contextmanager
    def nocache(self) -> typing.Iterator[None]:
        """Establish a context where caching is not performed."""
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


class InvalidatorSession(BaseSession):
    """Session which performs invalidation."""
    def __init__(self, session: Session) -> None:
        self._session = session

    # pylint: disable=useless-return
    def pre_call(self, func: FuncType, args: PosType,
                 kwargs: KwdType) -> typing.Optional['BaseSession']:
        self._session.invalidate(func, *args, **kwargs)
        return None

    def simple_pre_call(
            self, func: FuncType) -> typing.Optional['BaseSession']:
        self._session.invalidate(func)
        return None


class CallOnlySession(BaseSession):
    """Session which performs call only without caching."""
    def __init__(self, session: Session) -> None:
        self._session = session

    def pre_call(self, _func: FuncType,
                 _args: PosType, _kwargs: KwdType) -> typing.Any:
        """Call a function without caching.

        This normally calls a function directly, but may be overridden
        for other behavior.
        """
        return self._session

    def simple_pre_call(self, _func: FuncType) -> typing.Any:
        """Call a function without caching.

        This normally calls a function directly, but may be overridden
        for other behavior.
        """
        return self._session


class SetCacheSession(BaseSession):
    """Session which causes a fixed value to be used."""
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


def gcached(ref: bool = False, persistent: typing.Union[bool, str] = False) \
        -> typing.Callable[[FuncT], FuncT]:
    """Decorator to cache the return value of a function.

    This is the generic decorator, and must be called instead of used
    directly as a decorator.  For such usage, use cached or rcached.

    Args:

        ref: If False, copy.deepcopy is invoked before value is returned.

        persistent: If True, don't drop cached value upon
            invalidation.  If may be a string, which is called a
            "persistence key", or pkey, and can be used to
            mass-invalidate persistent functions of the same pkey in
            the cache.
    """
    def _deco(func: FuncT) -> FuncT:
        if _no_arg(func):
            ret = _gc0_func(func, ref)
        else:
            ret = _gc_func(func, ref)
        if persistent is not False:
            PERSISTENT_FUNCS.add(ret)
            if isinstance(persistent, str):
                PKEY_FUNCS[persistent].add(ret)
        return typing.cast(FuncT, functools.wraps(func)(ret))
    return _deco


def _gc_func(func: FuncType, ref: bool) -> FuncType:
    def _func(session: BaseSession, *args: typing.Any,
              **kwargs: typing.Any) -> typing.Any:
        entry = session.get_cache(_func, *args, **kwargs)
        if entry:
            if entry[1]:
                entry[1].__traceback__ = None  # type: ignore
                raise entry[1]
            return entry[0]
        try:
            ret = None  # type: typing.Any
            call_session = session.pre_call(_func, args, kwargs)
            if call_session:
                ret = func(call_session, *args, **kwargs)
        except Exception as exc:
            session.cache_exc(_func, exc, *args, **kwargs)
            raise
        session.cache(_func, ret, *args, **kwargs)
        return ret if ref else copy.deepcopy(ret)
    return _func


def _gc0_func(func: FuncType, ref: bool) -> FuncType:
    # Simplified version of _gc_func that does not do varargs.  In
    # such usages, the session reduces to a singleton, which might be
    # used very often in the program.  It is vital that the getter is
    # very fast.  We speed it up by (1) have a simple version of
    # get_cache and pre_call that does not forwarding arguments, (2)
    # use a simplified cache, (3) do not process exceptions, and (4)
    # have a special case in simple_get_cache() for the usual case
    # where no parent is used.
    def _func(session: BaseSession) -> typing.Any:
        ret = session.simple_get_cache(_func)
        if ret is not MISSING:
            return ret
        call_session = session.simple_pre_call(_func)
        ret = func(call_session) if call_session else None
        session.cache(_func, ret, (), {})
        return ret if ref else copy.deepcopy(ret)
    return _func


def cached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function.

    Equivalent to gcached()(func).
    """
    return gcached()(func)


def rcached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function.

    Equivalent to gcached(ref=True)(func).
    """
    return gcached(ref=True)(func)


def prcached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function persistently.

    Equivalent to gcached(ref=True, persistent=True)(func).
    """
    return gcached(ref=True, persistent=True)(func)


@prcached
def getter(session: BaseSession, *args: typing.Any, **kwargs: typing.Any) \
        -> typing.Any:
    """The underlying function to get a value from the cache."""
    raise KeyError(f'No value cached for args {args} {kwargs}')
