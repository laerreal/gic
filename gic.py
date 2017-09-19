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

def is_subtree(c, acceptable = 4):
    """ Heuristically detect a subtree merge.

    @acceptable:
    if the parent of @c have N files with same content but different names,
    the Git can be confused about name correspondence:

    E.g., let sys/time.h == time.h, then

    sys/time.h -> prefix/time.h
    time.h     -> prefix/sys/time.h

    is a correct Diff record (for version control system). While the assumption
    of the heuristic is violated.

    @acceptable is a threshold to handle such cases.
    """

    p1 = c.parents[1]
    d = p1.diff(c)

    # suggest a prefix
    for probe in d:
        if probe.renamed:
            break
    else:
        return None

    if probe.b_path.endswith(probe.a_path):
        prefix = probe.b_path[:-len(probe.a_path)]
    else:
        return None

    # Were all parent files renamed using same prefix?
    for po in p1.tree.traverse():
        if po.type != "blob":
            continue

        new_path = prefix + po.path

        for check in d:
            if check.renamed:
                if check.rename_from == po.path \
                and check.rename_to == new_path:
                    break
            elif check.new_file:
                if check.b_path == new_path:
                    break
        else:
            # no such difference
            if not acceptable:
                return None
            else:
                acceptable -= 1
                # print(po.path + " ACC")
                continue

        # print(po.path + " OK")

    return prefix

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
