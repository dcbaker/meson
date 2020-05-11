## Improvements to the python module

### Merge the Python module finding logic ahd dependency('python3') logic

The python module logic is much more sophisticated and capable. Calling
dependency for `python`, `python2`, and/or `python3` now uses this logic.
This includes the addition of the `embed` keyword for regular `dependency()`.

### Allow setting additional values in machine files

Previously only the `python` field was honored from a machine file in the
`[binaries]` section to override the behavior of `find_installation`, it now
accepts `python2` and `python3`, if those are passed as names to `find_installation`.

```ini
[binaries]
python = 'some/path'
python2 = 'some/path2'
python3 = 'some/path3'
```

```meson
pymod = import('python')
pymod.find_installation('python2')  # tries `python2` entry then `python` entry
pymod.find_installation('python3')  # tries `python` entry then `python` entry
pymod.find_installation()  # tries only `python`
```

### Add version keyword to find_installation()

This allow more fine tuning of which versions are supported.

### Consider modules part of found() status

Previously:

```python
pymod.find_installation('python3', modules : ['numpy'])
```

would fail if multiple versions of python3 were installed, but numpy was not
installed in the one meson happened to pick first. Now meson will consider
a version of python3 that doesn't have numpy as not found, and will continue
searching.
