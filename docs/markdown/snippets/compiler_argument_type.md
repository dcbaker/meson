## new compiler method `get_argument_type`

The compiler object now has `get_argument_type` method, which returns a string
value of `gcc`, `msvc`, or `other`. This can be used to determine if a compiler
takes gcc style arguments `-Wfoo`, msvc style args `/w1234` or some other kind
of arguments.

```meson
cc = meson.get_compiler('c')

if cc.get_argument_type() == 'msvc'
  if cc.has_argument('/w1235')
    add_project_arguments('/w1235', language : ['c'])
  endif
elif cc.get_argument_type() == 'gcc'
  if cc.has_argument('-Wfoo')
    add_project_arguments('-Wfoo', language : ['c'])
  endif
else
  if cc.has_argument('--error-on-foo')
    add_project_arguments('--error-on-foo', language : ['c'])
  endif
endif
```
