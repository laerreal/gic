__all__ = [
    "GGB_IBY",
    "CommitDesc"
]

# Iterations Between Yields of Git Graph Building task
GGB_IBY = 100

class CommitDesc(object):
    def __init__(self, sha, parents, children):
        self.sha = sha
        self.parents = parents
        self.children = children
        self.heads = []

        # serial number according to the topological sorting
        self.num = None
        # roots bit mask
        self.roots = 0

    @classmethod
    def co_build_git_graph(klass, repo, commit_desc_nodes,
        skip_remotes = False,
        skip_stashes = False,
        refs = None
    ):
        # iterations to yield
        i2y = GGB_IBY

        # n is serial number according to the topology sorting
        n = 0
        # to_enum is used during topological sorting
        # it contains commit to enumerate
        to_enum = None
        # build_stack contains edges represented by tuples
        # (parent, child), where parent is instance of
        # git.Commit, child is instance of CommitDesc
        build_stack = []
        # Each history root is represented by a bit in CommitDesc.roots of each
        # commit. root_bit is value for next found root.
        root_bit = 1

        for head in repo.references:
            if skip_remotes and head.path.startswith("refs/remotes/"):
                continue
            if skip_stashes and head.path.startswith("refs/stash"):
                continue
            if refs and head.path not in refs:
                continue

            try:
                head_desc = commit_desc_nodes[head.commit.hexsha]
            except KeyError:
                head_desc = klass(head.commit.hexsha, [], [])
                head_desc.heads.append(head)
            else:
                head_desc.heads.append(head)
                continue

            commit_desc_nodes[head.commit.hexsha] = head_desc
            # add edges connected to head being processed
            for p in head.commit.parents:
                build_stack.append((p, head_desc))

            while build_stack:
                parent, child_commit_desc = build_stack.pop()

                try:
                    parent_desc = commit_desc_nodes[parent.hexsha]
                except KeyError:
                    parent_desc = klass(parent.hexsha, [], [])
                    commit_desc_nodes[parent.hexsha] = parent_desc

                    if parent.parents:
                        for p in parent.parents:
                            build_stack.append((p, parent_desc))
                    else:
                        # current edge parent is an elder commit in the tree,
                        # that is why we should enumerate starting from it
                        to_enum = parent_desc
                        # parent is a root
                        parent_desc.roots = root_bit
                        root_bit <<= 1
                else:
                    # the existence of parent_desc means that parent has been
                    # enumerated before. Hence, we starts enumeration from
                    # it's child
                    to_enum = child_commit_desc
                    # This parent-to-child link is just being created. So, the
                    # root bits had not been propagated during enumeration
                    to_enum.roots |= parent_desc.roots
                finally:
                    parent_desc.children.append(child_commit_desc)
                    child_commit_desc.parents.append(parent_desc)

                if i2y <= 0:
                    yield True
                    i2y = GGB_IBY
                else:
                    i2y -= 1

                # numbering is performed from the 'to_enum' to either a leaf
                # commit or a commit just before a merge which have at least
                # one parent without number (except the commit)
                while to_enum is not None:
                    e = to_enum
                    to_enum = None
                    # if the number of parents in the CommitDesc
                    # is equal to the number of parents in the git.Commit,
                    # then all parents were numbered (added) earlier
                    # according to the graph building algorithm,
                    # else we cannot assign number to the commit yet
                    if len(e.parents) == len(repo.commit(e.sha).parents):
                        e.num = n
                        n = n + 1

                        roots = e.roots # cache the value

                        # according to the algorithm, only one child
                        # have no number. Other children either have
                        # been enumerated already or are not added yet
                        chiter = iter(e.children)
                        for c in chiter:
                            c.roots |= roots
                            if c.num is None:
                                to_enum = c
                                break

                        # but roots must be propagated to all children
                        for c in chiter:
                            c.roots |= roots

                    if i2y <= 0:
                        yield True
                        i2y = GGB_IBY
                    else:
                        i2y -= 1
