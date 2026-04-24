#! /usr/bin/env python3
import sys

if (l := len(sys.argv)) != 4:
    print('Got the wrong number of arguments. Got', l, 'but expected 4', file=sys.stderr)

with open(sys.argv[1], 'r', encoding='utf-8') as f:
    for l in f:
        l = l.rstrip()
        print(l.replace(sys.argv[2], sys.argv[3]))
