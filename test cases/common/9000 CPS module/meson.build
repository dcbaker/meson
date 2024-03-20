project(
  'CPS',
  'cpp',
  version : '0.1.0',
  license : 'Apache-2.0',
  meson_version : '>= 1.5',
)

cps = import('cps')
mt = cps.create_package('meson-test', description : 'A test CPS package')

exe = executable('exe', 'main.cpp')
mt.add_component(exe, name : 'meson-test-builder')

static = static_library('static', 'lib.cpp')
mt.add_component(
  static,
  include_directories : ['include/meson-test'],
  arguments : ['-DFOO', '-UBAR', '-fi-am-awesome'],
)

shared = shared_library('shared', 'shlib.cpp', link_with : static)
mt.add_component(shared, include_directories : ['include/meson-test'])

shared_external = shared_library('shared2', 'shlib.cpp', link_with : static)
mt2 = cps.create_package('meson-test2', description : 'Another test CPS package')
mt2.add_component(shared, include_directories : ['include/meson-test'])
