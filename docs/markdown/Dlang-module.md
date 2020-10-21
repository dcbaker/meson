# Dlang module

This module provides tools related to the D programming language.

## Usage

To use this module, just do: **`dlang = import('dlang')`**.
You can, of course, replace the name `dlang` with anything else.

The module has the following functions:

### generate_dub_file()
This method only has two required arguments, the project name and the
source folder. You can pass other arguments with additional keywords,
they will be automatically translated to json and added to the
`dub.json` file.

**Structure**
```meson
generate_dub_file("project name", "source/folder", key: "value" ...)
```

**Example**
```meson
dlang = import('dlang')
dlang.generate_dub_file(meson.project_name().to_lower(), meson.source_root(),
                        authors: 'Meson Team',
                        description: 'Test executable',
                        copyright: 'Copyright © 2018, Meson Team',
                        license: 'MIT',
                        sourceFiles: 'test.d',
                        targetType: 'executable',
                        dependencies: my_dep
)
```

You can manually edit a meson generated `dub.json` file or provide a
initial one. The module will only update the values specified in
`generate_dub_file()`.

Although not required, you will need to have a `description` and
`license` if you want to publish the package in the [D package registry](https://code.dlang.org/).

### test()
*(new in 0.57.0)*

This method creates a dlang unittest executable and test target from an
existing D language build target. This simplifies using dlang's in-source
test strategy.

It takes two positional arguments, the first is the name of the test target
as a string, the second is a build target of the D language (Executable, Library).

It takes the following keyword arguments:
  - `d_args`: arguments to compile the new d executable with (passed to executable)
  - `link_args`: arguments to link the new d executable with (passed to executable)

```meson
exe = executable(...)

dlang = import('dlang')
dlang.test('exe_test', exe)
```
