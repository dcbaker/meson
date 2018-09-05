# Copyright © 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

project('gcc func attributes', ['c', 'cpp'])

# For msvc these will fail because msvc doesn't support __attribute__, for
# Clang and GCC, they should pass.
c = meson.get_compiler('c')
cpp = meson.get_compiler('cpp')

# If the compiler isn't GCC, Clang, or MSVC we don't know what this will
# return, so we don't run
if not ['gcc', 'clang', 'msvc'].contains(c.get_id())
  error('MESON_SKIP_TEST: Compiler __attribute__ support unknown.')
endif

expected_result = c.get_id() != 'msvc'

attributes = [
  'aligned',
  'alloc_size',
  'always_inline',
  'cold',
  'const',
  'constructor',
  'constructor_priority',
  'deprecated',
  'destructor',
  'flatten',
  'format',
  'format_arg',
  'gnu_inline',
  'hot',
  'malloc',
  'noinline',
  'nonnull',
  'noreturn',
  'nothrow',
  'pure',
  'unused',
  'used',
  'warn_unused_result',
  'weak',
  'weakref',
]

# These are unsupported on darwin with apple clang 9.1.0
if host_machine.system() != 'darwin'
  attributes += 'alias'
  attributes += 'visibility'
endif

if c.get_id() == 'gcc'
  # not supported by clang as of 5.0.0 (at least up to 6.0.1)
  attributes += 'artificial'
  attributes += 'error'
  attributes += 'externally_visible'
  attributes += 'leaf'
  attributes += 'noclone'
  attributes += 'optimize'
  attributes += 'warning'

  if c.version().version_compare('>= 7.0.0')
    attributes += 'fallthrough'
  endif
endif

if host_machine.system() == 'windows'
  attributes += 'dllexport'
  attributes += 'dllimport'
endif

# Clang does support ifunc, but I can't figure out how to make a valid ifunc
# for clang++, andditionally older versions of g++ (or possibly glib) don't
# seem to work with C++ ifuncs. Additionally (since libc support is required)
# ifuncs never work on windows or apple
if not ['windows', 'darwin'].contains(host_machine.system())
  x = c.has_function_attribute('ifunc')
  assert(x == expected_result, 'ifunc')
endif

foreach a : attributes
  x = c.has_function_attribute(a)
  assert(x == expected_result, '@0@: @1@'.format(c.get_id(), a))
  x = cpp.has_function_attribute(a)
  assert(x == expected_result, '@0@: @1@'.format(cpp.get_id(), a))
endforeach

message('checking get_supported_function_attributes')
if c.get_id() != 'msvc'
  multi_expected = attributes
else
  multi_expected = []
endif

multi_check = c.get_supported_function_attributes(attributes)
assert(multi_check == multi_expected, 'get_supported_function_arguments works (C)')
multi_check = cpp.get_supported_function_attributes(attributes)
assert(multi_check == multi_expected, 'get_supported_function_arguments works (C++)')
