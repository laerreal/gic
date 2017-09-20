#!/usr/bin/python3

from co_dispatcher import callco
from git_tools import CommitDesc
from git import Repo
from argparse import (
    ArgumentTypeError,
    ArgumentParser
)
from actions import *
from os.path import isdir

class GICCommitDesc(CommitDesc):
    __slots__ = [
        "processed"
        "cloned_sha"
    ]

    def __init__(self, *args):
        super(GICCommitDesc, self).__init__(*args)

        self.cloned_sha = None
        self.processed = False

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

CLONED_REPO_NAME = "__cloned__"

def orphan(n):
    return "__orphan__%d" % n

def plan(repo, sha2commit, dstRepoPath):
    srcRepoPath = repo.working_dir

    queue = sorted(sha2commit.values(), key = lambda c : c.num)

    RemoveDirectory(path = dstRepoPath)
    ProvideDirectory(path = dstRepoPath)
    InitRepo(path = dstRepoPath)
    AddRemote(
        path = dstRepoPath,
        name = CLONED_REPO_NAME,
        address = srcRepoPath
    )
    FetchRemote(path = dstRepoPath, name = CLONED_REPO_NAME)

    iqueue = iter(queue)

    orphan_counter = 0

    prev_c = None

    for c in iqueue:
        c.processed = True

        m = repo.commit(c.sha)

        if prev_c is not None:
            if not c.parents:
                CheckoutOrphan(
                    name = orphan(orphan_counter),
                    path = dstRepoPath
                )
                orphan_counter += 1
            else:
                # get real parents order
                main_stream_sha = m.parents[0].hexsha
                if main_stream_sha != prev_c.sha:
                    # jump to main stream commit
                    CheckoutCloned(
                        path = dstRepoPath,
                        commit_sha = main_stream_sha
                    )

        if len(c.parents) > 1:
            subtree_prefix = None if len(c.parents) != 2 else is_subtree(m)

            if subtree_prefix is None:
                MergeCloned(
                    path = dstRepoPath,
                    commit_sha = c.sha,
                    author_name = m.author.name.encode("utf-8"),
                    author_email = m.author.email,
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset,
                    authored_date = m.authored_date,
                    author_tz_offset = m.author_tz_offset,
                    message = m.message,
                    # original parents order is significant
                    extra_parents = [
                        p.hexsha for p in m.parents[1:]
                    ]
                )
            else:
                SubtreeMerge(
                    path = dstRepoPath,
                    commit_sha = c.sha,
                    author_name = m.author.name.encode("utf-8"),
                    author_email = m.author.email,
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset,
                    authored_date = m.authored_date,
                    author_tz_offset = m.author_tz_offset,
                    message = m.message,
                    parent_sha = m.parents[1].hexsha,
                    prefix = subtree_prefix
                )

        else:
            CherryPick(
                path = dstRepoPath,
                commit_sha = c.sha,
                committer_name = m.committer.name.encode("utf-8"),
                committer_email = m.committer.email,
                message = m.message,
                committed_date = m.committed_date,
                committer_tz_offset = m.committer_tz_offset
            )

        for h in c.heads:
            if h.path.startswith("refs/heads/"):
                CreateHead(
                    path = dstRepoPath,
                    name = h.name
                )
            elif h.path.startswith("refs/tags/"):
                CreateTag(
                    path = dstRepoPath,
                    name = h.name
                )

        prev_c = c

    # delete temporary branch names
    for o in range(0, orphan_counter):
        DeleteHead(path = dstRepoPath, name = orphan(o))

    CheckoutCloned(
        path = dstRepoPath,
        commit_sha = repo.head.commit.hexsha
    )
    RemoveRemote(path = dstRepoPath, name = CLONED_REPO_NAME)
    CollectGarbage(path = dstRepoPath)

    for c in sha2commit.values():
        if not c.processed:
            print("Commit %s was not cloned!" % str(c.sha))

def main():
    print("Git Interactive Cloner")

    ap = ArgumentParser()
    ap.add_argument("source", type = arg_type_directory, nargs = 1)
    ap.add_argument("-d", "--destination", type = arg_type_directory, nargs = 1)

    args = ap.parse_args()

    srcRepoPath = args.source[0]

    print("Building graph of repository: " + srcRepoPath)

    ctx = GitContext(src_repo_path = srcRepoPath)
    repo = Repo(srcRepoPath)
    sha2commit = ctx._sha2commit
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

    # Planing
    switch_context(ctx)

    plan(repo, sha2commit, dstRepoPath)

    ctx.do()

if __name__ == "__main__":
    ret = main()
    exit(0 if ret is None else ret)
