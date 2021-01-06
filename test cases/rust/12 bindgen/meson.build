# SPDX-license-identifer: Apache-2.0
# Copyright © 2021 Intel Corporation

project('rustmod bindgen', ['c', 'rust'])

if not find_program('bindgen', required : false).found()
  error('MESON_SKIP_TEST bindgen not found')
endif

# This is to test the include_directories argument to bindgen
inc = include_directories('include')

c_lib = static_library('clib', 'src/source.c', include_directories : inc)

rust = import('unstable-rust')

gen = rust.bindgen(
  input : 'src/header.h',
  output : 'header.rs',
  include_directories : inc,
)

# see: https://github.com/mesonbuild/meson/issues/8160
f = configure_file(
  input : 'src/main.rs',
  output : 'main.rs',
  copy : true,
)

rust_bin = executable(
  'rust_bin',
  [f, gen],
  link_with : c_lib,
)

test('main', rust_bin)

# Test a generated header
gen_h = custom_target(
  'gen.h',
  command : [find_program('src/gen_header.py'), '@INPUT@', '@OUTPUT@'],
  output : 'gen.h',
  input : 'src/header.h'
)

gen2_h = custom_target(
  'other.h',
  command : [find_program('src/gen_header.py'), '@INPUT@', '@OUTPUT@'],
  output : 'other.h',
  input : 'include/other.h'
)

gen_rs = rust.bindgen(
  input : [gen_h, gen2_h],
  output : 'gen.rs',
)

f = configure_file(
  input : 'src/main2.rs',
  output : 'main2.rs',
  copy : true,
)

rust_bin2 = executable(
  'rust_bin2',
  [f, gen_rs],
  link_with : c_lib,
)

test('generated header', rust_bin2)

subdir('sub')
