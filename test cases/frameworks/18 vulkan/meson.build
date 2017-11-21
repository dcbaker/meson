project('vulkan test', 'c')

vulkan_dep = dependency('vulkan', method : 'system')
e = executable('vulkanprog', 'vulkanprog.c', dependencies : vulkan_dep)
test('vulkantest', e)

vulkan_dep = dependency('vulkan', method : 'pkg-config')
e = executable('vulkanprog-pkg', 'vulkanprog.c', dependencies : vulkan_dep)
test('vulkantest-pkg', e)
