project(
	'shared runtime',
	'd',
)

testlib = shared_library(
	'tester',
	'lib.d',
)

t = executable(
	'tester',
	'main.d',
	link_with : testlib,
)

test('runtime', t)
