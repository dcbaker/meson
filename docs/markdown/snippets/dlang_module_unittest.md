## dlang module has gained a test() method

This method allows you to be much DRYer when building D in-source tests.
meson will do the necessary code copying for you:

```meson

target = executable('target', ...)

dlang = import('dlang')
dlang.test('target_test', dlang)
```
