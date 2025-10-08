# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Intel Corporation

project('foo', 'c', 'vala', meson_version : '>= 1.10')

glib = dependency('glib-2.0')
gobject = dependency('gobject-2.0')
g_ir_compiler = find_program('g-ir-compiler')

foo = shared_library('foo', 'foo.vala',
                     install : true,
                     install_dir : [true, false, false, true],
                     vala_gir: 'Foo-1.0.gir',
                     dependencies: [glib, gobject])

gnome = import('gnome')
gnome.generate_typelib(foo.vala_gir())
