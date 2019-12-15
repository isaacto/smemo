# smemo: Explicit session memoization

Memoization of function return values is a very common optimization
technique.  Even the standard Python 3 library provides multiple
facilities for it, e.g., `functools.cached_property` and
`functools.lru_cache`.  Needless to say, many user-contributed
facilities are also available.

Most of them focuses on ensuring that the cache is invisible to the
user.  When you call a function decorated by `functools.lru_cache`,
you don't really need to know that the function value is cached.  That
is usually a big merit, but at times this is a big drawback.

The problem is on invalidation.  Most libraries spent a lot of efforts
to keep track of them magically so that we don't need to worry about
them.  But at times, all these work are not necessary or outright
counterproductive.  The run of your program might be divided into
parts, or sessions, where each session is benefited by having return
values of functions, usually many of them, saved rather than
recomputed.  But after a session, the saved values of the function is
of little value or even may be invalid, so there is not much to be
gained by keeping them in memory.

In such cases, most other caching tools either do not help at all, or
requires you to carefully find the functions being used by the session
and invalidate their caches one by one.

This module uses a more explicit approach.  A "session" object is
used, providing the cache required by the memoization process.  The
availability of this object makes a few operations, tricky in other
libraries, to become trivial.  They include:

  * Invalidation of all caches of a session.
  * One single function uses different caches for different calls.
  * Fine-grain control of whether values of a function should skip
    caching.
  * Injection of values to a particular function for a session.

In fact, the implementation of the module is so simple that the core
of it can be done in just a couple of hours.

## Usage

Functions requiring caching should be written like this:

    @smemo.cached
    def efib(session: smemo.BaseSession, n: int,
             a0: float, a1: float) -> float:
        "Return an extended Fibonacci number where efib[0] = a0, efib[1] = a1"
        if n == 0:
            return a0
        if n == 1:
            return a1
        return efib(session, n - 1, a0, a1) + efib(session, n - 2, a0, a1)

Note that it explicitly includes the session object as the first
argument.  All functions decorated by @smemo.cached does the same.

It can then be called like this:

    session = smemo.Session()
    print(efib(session, 5, 1, 3))

After the call, the session contains entries like `{((2, 1, 3), ()):
(4, None)}`, the key contains a hashable representation of the
positional and keyword arguments, while the values are the return
value or exception raised.  The value can be observed without
triggering a call to the inner function, by:

    print(session.get_cache(efib, 5, 1, 3))

The returned value of the function decorated by `@smemo.cached` goes
through `copy.deepcopy`, so that the caller can freely manipulate the
returned object without affecting the cache.  If that is undesirable
(usually because it slows things down or you really want the actual
object returned), you would replace `@smemo.cached` by
`@smemo.rcached`.

For many purposes these are good enough.  But at times some of the
values (e.g., 3 and 1 above) are really constants for a session, and
you can save a lot of space by not including them in the keys of the
cache.  In such cases you can rewrite your function as follows:

    @smemo.cached
    def efib(session: smemo.BaseSession, n: int) -> float:
        "Return an extended Fibonacci number where efib[0] = a0, efib[1] = a1"
        if n == 0:
            return session.getval('a0')  # Same as smemo.getter('a0')
        if n == 1:
            return session.getval('a1')
        return efib(session, n - 1) + efib(session, n - 2)

You call your function like this instead:

    session = smemo.Session()
    session.putval(1, 'a0')
    session.putval(3, 'a1')
    print(efib(session, 5))

This is a trivial function to implement.  It just composes other
session facilities with a "getter" function, the latter simply raises
an exception.  On the other hand, this is a very useful mechanism,
because it enables you to use memoization where previously you might
not even think you want to.  For example, you can read a whole config
file and put it to your session.  Now your functions can freely use
the configuration values, and you don't need to worry about having
cache which has huge entries, and at the same time you don't need to
worry about cross-talk when your function is called with multiple
sessions concurrently.

## Cache control

The big differentiation between smemo and other solutions is cache
control.  We do not do implicit cached control like LRU at all, all
cached values are kept there until explicitly invalidated.  In fact,
we don't even store those information (e.g., when is a value last
needed), so the overheads in our module is quite small.

Having a session object, explicit cache control can be done trivially.
For example, you can clear the cache either for one call, for one
function or for all functions, by the following respectively:

    session.invalidate(efib, 7)
    session.invalidate_all(efib)
    session.invalidate_all()

For the first call, the call needs to match the calling arguments, but
mypy will not be able to catch it if there is a type error.  An
alternative method can be used instead, which does trigger mypy to
catch a type error:

    efib(session.inv, 7)

Because it is just another call to efib, it has to match the type
correctly to pass mypy.

For the last `session.invalidate` call, it actually doesn't invalidate
all function values cached.  If a function is marked as "persistent",
the values cached for it can only be invalidated more explicitly.
This is done by using `@smemo.gcached(persistent=True)` instead of
`@smemo.cached`, or (more commonly) using `@smemo.gcached(ref=True,
persistent=True)` instead of `@smemo.rcached`.  This is the mechanism
used by `getval` and `putval` to avoid getting values removed.  If you
want to avoid these calls (which mypy cannot check for type errors),
you can create functions returning the correct type and mark them as
persistent instead.

You can force a value into the cache, like one of these:

    session.cache(efib, 5.0, 7)
    session.cache_exc(efib, RuntimeError('My error'), 7)

In this case, it causes efib(7, session) to return 5.0 and raises "My
error" respectively.  This is very useful during unit tests, where at
times you don't want your functions to actually be called.  Again, we
have alternative methods which allows mypy to catch type errors:

    efib(session.setcache(5.0), 7)
    efib(session.setcache(exception=RuntimeError('My error')), 7)

Finally, you can call a function without caching it, by:

    session.call(efib, 7)

The skipping of caching does not extend to the calls made by efib.  If
you want that, you can do the following:

    with session.nocache:
        print(efib(session, 7))

Caching would be disabled for all the duration of the above efib call.
