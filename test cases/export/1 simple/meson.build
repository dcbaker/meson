# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Intel Corporation

project('simple-export', 'c', meson_version : '>= 1.8')

lib = library('foo', 'foo.c')

export = import('export')
foo_ex = export.create_set('foo')

foo_ex.export('foo', lib)
