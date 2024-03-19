project(
  'CPS',
  'cpp',
  version : '0.1.0',
  license : 'Apache-2.0',
  meson_version : '>= 1.5',
)

cps = import('cps')
cps.create_package('meson-test', description : 'A test CPS package')

exe = executable('exe', 'main.cpp')
cps.create_component('meson-test', exe, name : 'meson-test-builder')

static = static_library('static', 'lib.cpp')
cps.create_component(
  'meson-test', static,
  include_directories : ['include/meson-test'],
  arguments : ['-DFOO', '-UBAR', '-fi-am-awesome'],
)

shared = shared_library('shared', 'lib.cpp')
cps.create_component(
  'meson-test', shared,
  include_directories : ['include/meson-test'],
)
