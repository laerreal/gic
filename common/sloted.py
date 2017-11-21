__all__ = ["sloted"]

class sloted(object):
    __slots__ = ["__dfs_visited__"]

    def __init__(self, **kw):
        for klass in type(self).__mro__:
            try:
                slots = klass.__slots__
            except AttributeError:
                continue

            for attr in slots:
                if attr.startswith("_"):
                    continue
                setattr(self, attr, kw[attr])

    def gen_by_slots(self, gen, **extra):
        """ Helper for implementation of __gen_code__ for PyGenerator API. """
        all_slots = []
        for klass in type(self).__mro__:
            try:
                slots = klass.__slots__
            except AttributeError:
                continue

            for attr in reversed(slots):
                if attr.startswith("_"):
                    continue
                if attr in all_slots:
                    continue
                all_slots.append(attr)

        gen.reset_gen(self)

        for attr in reversed(all_slots):
            gen.gen_field(attr + " = ")
            try:
                gen.pprint(getattr(self, attr))
            except BaseException as e:
                raise e

        for k, v in extra.items():
            gen.gen_field(k + " = " + gen.gen_const(v))

        gen.gen_end()
