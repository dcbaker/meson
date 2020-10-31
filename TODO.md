Cargo to meson.build:
    - Completed:
        - dependencies
        - binaries
        - libraries
        - features

    - TODO:
        - targets
        - build-dependencies
        - example
        - bench
        - profile
        - patch
        - test for default_options being set correctly
        - binaries:
            - test for auto bin and manual bin collision
            - targets required features
            - doctest?
            - bench
        - libraries
            - targets required features
            - proc-macro
            - doctest?
            - bench
        - Add test for invalid feature names
        - extend test 15 to cover test, exampeles, and benches
        - is the use of a disabler() for dev-dependencies smart?

Wrap
    - TODO:
        - workspaces
        - fetching crates
        - generating .wraps from crates

Overall:
    - Figure out what to do about multiple versions of the same crate
    - Add a mechanism to test.json to verify that the correct tests are being run
    - Come up with a better solution for subprojects affecting each-others options
    - how to handle recursive subprojects
