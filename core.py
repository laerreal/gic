__all__ = [
    "GICCommitDesc"
  , "plan"
  , "load_context"
]

from common import CommitDesc

from actions import *

from os.path import abspath

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
        "skipped",
        "processed",
        "cloned_sha"
    ]

    def __init__(self, *args):
        super(GICCommitDesc, self).__init__(*args)

        self.cloned_sha = None
        self.processed = False
        self.skipped = False

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

def plan_heads(c, dst_repo_path):
    for h in c.heads:
        if h.path.startswith("refs/heads/"):
            CreateHead(
                path = dst_repo_path,
                name = h.name
            )
        elif h.path.startswith("refs/tags/"):
            CreateTag(
                path = dst_repo_path,
                name = h.name
            )

def get_actual_parents(orig_parent, sha2commit):
    """ A parent of a merge commit could be skipped. But a replacement have to
be provided. This function looks it up. As a merge commit could be skipped too,
one parent could be replaced with several parents.
    """

    if not sha2commit[orig_parent.hexsha].skipped:
        return [orig_parent]

    ret = []
    # Parent order is reversed to preserve main stream (zero index) commit
    # priority in course of depth-first graph traversal.
    stack = list(reversed(orig_parent.parents))
    while stack:
        p = stack.pop()

        if sha2commit[p.hexsha].skipped:
            stack.extend(reversed(p.parents))
        else:
            ret.append(p)

    return ret

CLONED_REPO_NAME = "__cloned__"

def plan(repo, sha2commit, dstRepoPath,
    main_stream_bits = 0,
    breaks = None,
    skips = None,
    insertions = None
):
    """
insertions:
    List of commits to insert. Each insertion is described by a tuple of
    an existing commit SHA1 and inserted commit content:

    ("...SHA1...", content)

    Supported content:
    - name of the patch file in `git am` compatible format.

    The commit is inserted _before_ the commit identified by SHA1.

    Multiple insertions for one SHA1 are supported. The order is preserved.

    A commit can be inserted before skipped one.

    If a main stream is set then insertions before non-main stream commits are
    ignored.

    XXX: insertion before a merge commit is buggy, except for that merge is
    skipped.
    """
    breaks = set() if breaks is None else set(breaks)
    skips = set() if skips is None else set(skips)

    # Group insertions by SHA1 for fastest search. Order of insertions for one
    # SHA1 must be preserved.
    insertion_table = {}
    if insertions:
        for sha1, insertion in insertions:
            insertion_table.setdefault(sha1, []).append(insertion)

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
    FetchRemote(
        path = dstRepoPath,
        name = CLONED_REPO_NAME,
        tags = True
    )

    iqueue = iter(queue)

    orphan_counter = 0

    prev_c = None

    for c in iqueue:
        c.processed = True
        c_sha = c.sha # attribute getting optimization

        if main_stream_bits and not (c.roots & main_stream_bits):
            # this commit will be used as is
            c.cloned_sha = c_sha
            # TODO: heads and tags of such commits
            continue

        m = repo.commit(c_sha)

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
                main_stream = m.parents[0]
                main_stream_sha = main_stream.hexsha
                if main_stream_sha != prev_c.sha:
                    # main stream parent of the commit could be skipped...
                    aps = get_actual_parents(main_stream, sha2commit)
                    actual_main_stream_parent_sha = aps[0].hexsha

                    if actual_main_stream_parent_sha != main_stream_sha:
                        print("Main stream parent %s of %s is not available. "
                            "Its ancestor %s will become a new trunk "
                            "instead." % (
                                main_stream_sha, c_sha,
                                actual_main_stream_parent_sha
                            )
                        )

                    # jump to main stream commit
                    CheckoutCloned(
                        path = dstRepoPath,
                        commit_sha = actual_main_stream_parent_sha
                    )
                    at_least_one_in_trunk = False

        # `pop` is used to detect unused insert positions
        insertions = insertion_table.pop(c_sha, [])
        for i in insertions:
            abs_i = abspath(i)
            ApplyPatchFile(
                path = dstRepoPath,
                patch_name = abs_i
            )

        if c_sha in skips:
            skipping = True

            skips.remove(c_sha) # Detection of unused skips
        else:
            skipping = False

        if not skipping and len(c.parents) > 1:
            # Handle merge commit parent skipping.
            extra_parents = []
            for p in m.parents[1:]:
                aps = get_actual_parents(p, sha2commit)

                if aps:
                    if aps[0] != p:
                        print("Parent %s of %s is skipped and will be "
                            "substituted with %s" % (
                                p.hexsha, c_sha,
                                ", ".join(pp.hexsha for pp in aps)
                            )
                        )
                else:
                    print("Parent %s of %s is skipped and cannot be "
                        "replaced" % (p.hexsha, c_sha)
                    )

                extra_parents.extend(aps)

            if not extra_parents:
                print("Merge commit %s is skipping because its parents are "
                    "skipped leaving it with only one parent" % c_sha
                )
                skipping = True

        if skipping:
            c.skipped = True
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
                    author_name = m.author.name,
                    author_email = m.author.email,
                    authored_date = m.authored_date,
                    author_tz_offset = m.author_tz_offset
                )
                SetCommitter(
                    committer_name = m.committer.name,
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )

                if subtree_prefix is None:
                    MergeCloned(
                        path = dstRepoPath,
                        commit_sha = c_sha,
                        message = m.message,
                        # original parents order is significant
                        extra_parents = [
                            p.hexsha for p in extra_parents
                        ]
                    )
                else:
                    SubtreeMerge(
                        path = dstRepoPath,
                        commit_sha = c_sha,
                        message = m.message,
                        parent_sha = extra_parents[0].hexsha,
                        prefix = subtree_prefix
                    )

                ResetAuthor()
                ResetCommitter()

            else:
                # Note that author is set by cherry-pick
                SetCommitter(
                    committer_name = m.committer.name,
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )
                CherryPick(
                    path = dstRepoPath,
                    commit_sha = c_sha,
                    message = m.message
                )
                ResetCommitter()

            plan_heads(c, dstRepoPath)

        if c_sha in breaks:
            breaks.remove(c_sha) # Detection of unused breaks

            if at_least_one_in_trunk:
                # Note that SHA1 of the cloned commit is unknown now.
                # Hence, use its message to identify it for a user.
                try:
                    msg = m.message.split("\n")[0]
                except IndexError:
                    msg = " after empty message commit %s" % c_sha
                else:
                    msg = " after '%s'" % msg
                Interrupt(reason = "Interrupting%s as requested..." % msg)

                # Update committer name, e-mail and date after user actions.
                SetCommitter(
                    committer_name = m.committer.name,
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )
                ContinueCommitting(
                    path = dstRepoPath,
                    commit_sha = c_sha
                )
                ResetCommitter()
            else:
                print("Cannot interrupt on '%s' because no commits "
                    "of this trunk are copied." % c_sha
                )

        prev_c = c

    # delete temporary branch names
    for o in range(0, orphan_counter):
        DeleteHead(path = dstRepoPath, name = orphan(o))

    # delete tags of non-cloned commits
    for tag in repo.references:
        if not tag.path.startswith("refs/tags/"):
            continue

        # Note that, no commit descriptors could be created for a trunk.
        c = sha2commit.get(tag.commit.hexsha, None)
        if c is None or c.skipped:
            DeleteTag(path = dstRepoPath, name = tag.name)

    CheckoutCloned(
        path = dstRepoPath,
        commit_sha = repo.head.commit.hexsha
    )
    RemoveRemote(path = dstRepoPath, name = CLONED_REPO_NAME)
    CollectGarbage(path = dstRepoPath)

    for c in sha2commit.values():
        if not c.processed:
            print("Commit %s was not cloned!" % str(c.sha))

    if breaks:
        raise RuntimeError("Unused break(s): " + ", ".join(breaks))
    if skips:
        raise RuntimeError("Unused skip(s): " + ", ".join(skips))
    if insertion_table:
        raise RuntimeError("Unused insertion(s): " + ", ".join(
            ("'%s'" % val + " before " + sha1)
                for (sha1, vals) in insertion_table.items()
                    for val in vals
        ))

def load_context(file_name):
    loaded = {}

    execfile(file_name, globals(), loaded)

    for ctx in loaded.values():
        if isinstance(ctx, GitContext):
            return ctx

    # no saved context found among loaded objects
    raise RuntimeError("No context found in file '%s'" % file_name)
