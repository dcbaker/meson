## Improvements to the python module

### Merge the Python module finding logic ahd dependency('python3') logic

The python module logic is much more sophisticated and capable. Calling dependency
for `python`, `python2`, and/or `python3` now uses this logic. This includes the addition
of the `embed` keyword for regular `dependency()`.
