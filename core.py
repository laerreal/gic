__all__ = [
    "GICCommitDesc"
  , "plan"
  , "load_context"
]

from common import CommitDesc

from actions import *

from six import PY2
if not PY2:
    def execfile(filename, globals = None, locals = None):
        f = open(filename, "rb")
        content = f.read()
        f.close()
        obj = compile(content, filename, "exec")
        exec(content, globals, locals)

class GICCommitDesc(CommitDesc):
    __slots__ = [
        "processed",
        "cloned_sha"
    ]

    def __init__(self, *args):
        super(GICCommitDesc, self).__init__(*args)

        self.cloned_sha = None
        self.processed = False

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

def orphan(n):
    return "__orphan__%d" % n

CLONED_REPO_NAME = "__cloned__"

def plan(repo, sha2commit, dstRepoPath,
    main_stream_bits = 0,
    breaks = None,
    skips = None
):
    breaks = set() if breaks is None else set(breaks)
    skips = set() if skips is None else set(skips)

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

        if main_stream_bits and not (c.roots & main_stream_bits):
            # this commit will be used as is
            c.cloned_sha = c.sha
            continue

        m = repo.commit(c.sha)

        if prev_c is not None:
            if not c.parents:
                CheckoutOrphan(
                    name = orphan(orphan_counter),
                    path = dstRepoPath
                )
                orphan_counter += 1
                at_least_one_in_trunk = False
            else:
                # get real parents order
                main_stream_sha = m.parents[0].hexsha
                if main_stream_sha != prev_c.sha:
                    # jump to main stream commit
                    CheckoutCloned(
                        path = dstRepoPath,
                        commit_sha = main_stream_sha
                    )
                    at_least_one_in_trunk = False

        skipping = c.sha in skips

        if skipping:
            for h in c.heads:
                if h.path.startswith("refs/heads/"):
                    if at_least_one_in_trunk:
                        # Skipping a commits moves its head on first
                        # non-skipped ancestor.
                        CreateHead(
                            path = dstRepoPath,
                            name = h.name
                        )
                    else:
                        print("Head '%s' will be skipped because no commits "
                            "of this trunk are copied." % h.name
                        )
                elif h.path.startswith("refs/tags/"):
                    print("Tag '%s' will be skipped with its commit!" % h.name)
        else:
            at_least_one_in_trunk = True

            if len(c.parents) > 1:
                subtree_prefix = None if len(c.parents) != 2 else is_subtree(m)

                SetAuthor(
                    author_name = m.author.name.encode("utf-8"),
                    author_email = m.author.email,
                    authored_date = m.authored_date,
                    author_tz_offset = m.author_tz_offset
                )
                SetCommitter(
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )

                if subtree_prefix is None:
                    MergeCloned(
                        path = dstRepoPath,
                        commit_sha = c.sha,
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
                        message = m.message,
                        parent_sha = m.parents[1].hexsha,
                        prefix = subtree_prefix
                    )

                ResetAuthor()
                ResetCommitter()

            else:
                # Note that author is set by cherry-pick
                SetCommitter(
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )
                CherryPick(
                    path = dstRepoPath,
                    commit_sha = c.sha,
                    message = m.message
                )
                ResetCommitter()

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

        if c.sha in breaks:
            if at_least_one_in_trunk:
                Interrupt(reason = "Interrupting as requested...")

                # Update committer name, e-mail and date after user actions.
                SetCommitter(
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )
                ContinueCommitting(
                    path = dstRepoPath,
                    commit_sha = c.sha
                )
                ResetCommitter()
            else:
                print("Cannot interrupt on '%s' because no commits "
                    "of this trunk are copied." % c.sha
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

def load_context(file_name):
    loaded = {}

    execfile(file_name, globals(), loaded)

    for ctx in loaded.values():
        if isinstance(ctx, GitContext):
            return ctx

    # no saved context found among loaded objects
    raise RuntimeError("No context found in file '%s'" % file_name)
