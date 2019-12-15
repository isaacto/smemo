"""Smemo: Explicit session memoization

Allow functions to be written naturally with explicit cache control.

"""

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
"Marker object to identify pickled keys"


class Session:
    "Session object to hold cached results"
    def __init__(self) -> None:
        self._disabled = False
        self._cache \
            = {}  # type: typing.Dict[FuncType, typing.Dict[KeyType, ResType]]

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

    def call(self, func: FuncType, *args: typing.Any,
             **kwargs: typing.Any) -> typing.Any:
        """Call a function without caching

        This calls a function decorated with @cached or @rcached.  The
        first session argument is automatically inserted.

        """
        inner = inspect.getclosurevars(func)[0]['func']
        return inner(self, *args, **kwargs)

    def cache(self, func: FuncType, _val: typing.Any,
              *args: typing.Any, **kwargs: typing.Any) -> None:
        "Insert a value as the cached value for a function call"
        self._cache_store(func, args, kwargs, (_val, None))

    def cache_exc(self, func: FuncType, _exc: Exception,
                  *args: typing.Any, **kwargs: typing.Any) -> None:
        "Insert an exception return as the cached value for a function call"
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
        "Get the cached result for a function"
        if func not in self._cache:
            return None
        return self._cache[func].get(self._key(args, kwargs))

    def invalidate(self, func: FuncType,
                   *args: typing.Any, **kwargs: typing.Any) -> None:
        "Invalidate the result of a single function call"
        if func in self._cache:
            self._cache[func].pop(self._key(args, kwargs), None)

    def invalidate_all(self, func: FuncType = None) -> None:
        "Invalidate all results, possibly restricted to a function call"
        if func:
            self._cache.pop(func, None)
        else:
            new_cache = {}
            if getter in self._cache:
                new_cache[getter] = self._cache[getter]
            self._cache = new_cache

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


FuncT = typing.TypeVar('FuncT', bound=typing.Callable[..., typing.Any])


def cached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function

    The first argument of func should be the session object.  It is
    consulted to look for cached values.

    This version will deep copy the cached value before returning.
    See rcached also.

    """
    @functools.wraps(func)
    def _func(session: Session, *args: typing.Any, **kwargs: typing.Any) \
            -> typing.Any:
        ret = _maybe_call(session, _func, func, args, kwargs)
        exc = ret[1]
        if exc:
            raise exc
        return copy.deepcopy(ret[0])
    _func.inner = func  # type: ignore
    return typing.cast(FuncT, _func)


def rcached(func: FuncT) -> FuncT:
    """Decorator to cache the return value of a function

    The first argument of func should be the session object.  It is
    consulted to look for cached values.

    This version will not deep copy the cached value before returning.
    This is more efficent and handle reference values right, but if
    the user change the result the modification is also seen in
    results of later call.

    """
    @functools.wraps(func)
    def _func(session: Session, *args: typing.Any, **kwargs: typing.Any) \
            -> typing.Any:
        ret = _maybe_call(session, _func, func, args, kwargs)
        exc = ret[1]
        if exc:
            raise exc
        return ret[0]
    return typing.cast(FuncT, _func)


@rcached
def getter(session: Session, *args: typing.Any, **kwargs: typing.Any) \
        -> typing.Any:
    "The underlying function to get a value from the cache"
    raise KeyError('No value cached for args %s %s' % (args, kwargs))


def _maybe_call(session: Session, func: FuncType, actual: FuncType,
                args: PosType, kwargs: KwdType) -> ResType:
    ret = session.get_cache(func, *args, **kwargs)
    if ret:
        return ret
    try:
        res = actual(session, *args, **kwargs)
    except Exception as exc:
        session.cache_exc(func, exc, *args, **kwargs)
        return (None, exc)
    session.cache(func, res, *args, **kwargs)
    return (res, None)
