project('c++ test', 'cpp')

if meson.get_compiler('cpp').get_id() == 'intel'
  if host_machine.system() == 'windows'
    add_project_arguments('/Qdiag-error=10159', language : 'cpp')
  else
    # Error out if the -std=xxx option is incorrect
    add_project_arguments('-diag-error', '10159', language : 'cpp')
  endif
endif

exe = executable('trivialprog', 'trivial.cc', extra_files : 'something.txt')
test('runtest', exe)
