#!/usr/bin/python3

from argparse import \
    ArgumentTypeError, \
    ArgumentParser
from os.path import isdir

def arg_type_directory(string):
    if not isdir(string):
        raise ArgumentTypeError(
            "{} is not directory".format(string))
    return string

def main():
    print("Git Interactive Cloner")

    ap = ArgumentParser()
    ap.add_argument("source", type = arg_type_directory, nargs = 1)
    ap.add_argument("-d", "--destination", type = arg_type_directory, nargs = 1)

    args = ap.parse_args()

if __name__ == "__main__":
    ret = main()
    exit(0 if ret is None else ret)
