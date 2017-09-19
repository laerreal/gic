#!/usr/bin/python3

from co_dispatcher import callco
from git_tools import CommitDesc
from git import Repo
from argparse import (
    ArgumentTypeError,
    ArgumentParser
)
from os.path import isdir

class GICCommitDesc(CommitDesc):
    def __init__(self, *args):
        super(GICCommitDesc, self).__init__(*args)

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

    srcRepoPath = args.source[0]

    print("Building graph of repository: " + srcRepoPath)

    repo = Repo(srcRepoPath)
    sha2commit = {}
    callco(
        GICCommitDesc.co_build_git_graph(repo, sha2commit,
            skip_remotes = True,
            skip_stashes = True
        )
    )

    print("Total commits: %d" % len(sha2commit))

    destination = args.destination
    if destination is None:
        print("No destination specified. Dry run.")
        return

    dstRepoPath = destination[0]

    print("The repository will be cloned to: " + dstRepoPath)

if __name__ == "__main__":
    ret = main()
    exit(0 if ret is None else ret)
